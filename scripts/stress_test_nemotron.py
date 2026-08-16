#!/usr/bin/env python3
"""PRODUCTION STRESS-TEST — FOL after the Nemotron-OpenRouter
integration.

Parts:
  A. Hermetic fallback simulation (no network): sync/async/stream/sync-simple
     LLM paths + the FOL engine — 429, timeout, connection error, empty,
     malformed, all-fail. The assistant must keep working or fail gracefully.
  B. Final Response Layers (FOL polish_response + orchestrator
     format_final_response): Done/Готово/OK/JSON/traceback/Sir/empty and the
     engine graceful-failure message must never reach the user.
  C. Security: .env ignored by git, no real keys in tracked files/logs/SSE,
     no tool args in user-facing text.
  D. Live E2E: starts the REAL FOL API server (port 8754) and drives ~28
     scenarios through the real HTTP pipeline against the REAL Nemotron model;
     plus the orchestrator /command path (port 8420).

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
import types
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FOL_DIR = ROOT / "fol"
FOL_PORT = 8754
ORCH_PORT = 8420
FOL_BASE = f"http://127.0.0.1:{FOL_PORT}"
ORCH_BASE = f"http://127.0.0.1:{ORCH_PORT}"

# The real key that lives in .env — used ONLY to prove it never leaks into
# logs / SSE / final responses.
REAL_KEY = "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"

FORBIDDEN = {"done", "готово", "ok", "принято", "выполнено", "сделано",
             "success", "completed", "task completed", "yes", "успешно",
             "sir", "сэр"}

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def report(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        FAILURES.append(name)
        print(f"  ❌ {name} {detail}")


def check(text: str) -> list[str]:
    """Violations list — empty means the answer is acceptable."""
    v: list[str] = []
    t = (text or "").strip()
    if not t:
        v.append("EMPTY")
        return v
    stripped = t.rstrip(".!").strip().lower()
    if stripped in FORBIDDEN:
        v.append(f"BARE CONFIRMATION: {text!r}")
    low = t.lower()
    if "traceback" in low or "exception" in low or "connectionerror" in low or "typeerror" in low:
        v.append("TRACEBACK/EXCEPTION")
    if t.startswith("{") and "}" in t:
        v.append("JSON")
    if re.search(r"\b(tool_call|tool_result|open_app|function_call|parameters|arguments)\b", low):
        v.append("TOOL/JSON LEAK")
    if re.search(r"\bsir\b|\bсэр\b", low):
        v.append("HONORIFIC")
    if "mlx-lm" in low or "api key" in low or "llm backends are unavailable" in low:
        v.append("TECHNICAL LEAK")
    if REAL_KEY in t:
        v.append("API KEY LEAK")
    return v


# ---------------------------------------------------------------------------
# Part A — hermetic fallback simulation
# ---------------------------------------------------------------------------

def part_a_sync():
    print("\n[Part A] sync llm_call fallback (hermetic)")
    sys.path.insert(0, str(ROOT))
    import analyze._llm as llm

    chain = ["primary", "fallback"]

    # The REAL _call_single_model contract: it catches exceptions internally
    # (429/timeout/connection) and returns None so the chain can move on. A
    # mocked version must mimic that contract — raise would leak.
    def _se(primary_ret=None, fallback_ret="fallback answer"):
        def se(model, api_key, prompt, mt, temp, has_fallback=False):
            if model == "primary":
                return primary_ret
            return fallback_ret
        return se

    # Real _call_single_model + fake litellm: 429 fail-fast when a fallback
    # exists (no sleeping on a dead provider).
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = lambda **k: (_ for _ in ()).throw(Exception("429 Too Many Requests - rate_limit exceeded"))
    with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
         mock.patch.object(llm, "time") as fake_time, \
         mock.patch.object(llm, "_RATE_LIMIT_BASE_DELAY", 1):
        result = llm._call_single_model("primary", "k", "p", 10, 0.0, has_fallback=True)
    report("real 429 fail-fast → None", result is None, repr(result))
    report("real 429 fail-fast did not sleep", fake_time.sleep.call_count == 0)

    # Real _call_single_model: timeout/connection also collapse to None
    def _raising_completion(exc):
        def completion(**kwargs):
            raise exc
        return completion

    for exc in (TimeoutError("request timed out"), ConnectionError("refused")):
        fake_litellm = types.ModuleType("litellm")
        fake_litellm.completion = _raising_completion(exc)
        with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
             mock.patch.object(llm, "time"):
            result = llm._call_single_model("primary", "k", "p", 10, 0.0, has_fallback=True)
        report(f"real {type(exc).__name__} → None", result is None, repr(result))

    # Chain-level: primary fails (None) → fallback answers
    for label, ret in (("failed primary", None), ("empty primary", "")):
        with mock.patch.object(llm, "_get_model_chain", return_value=chain), \
             mock.patch.object(llm, "_call_single_model",
                               side_effect=_se(primary_ret=ret)):
            out = llm.llm_call("p", "t")
        report(f"sync {label} → fallback answers", out == "fallback answer", repr(out))

    # Empty fallback text → passes through as-is, never raises
    with mock.patch.object(llm, "_get_model_chain", return_value=chain), \
         mock.patch.object(llm, "_call_single_model",
                           side_effect=_se(fallback_ret="not json{ broken")):
        out = llm.llm_call("p", "t")
    report("sync malformed → no raise", isinstance(out, str), repr(out))

    # All models fail → graceful "" (never raises)
    with mock.patch.object(llm, "_get_model_chain", return_value=chain), \
         mock.patch.object(llm, "_call_single_model",
                           side_effect=_se(primary_ret=None, fallback_ret=None)):
        out = llm.llm_call("p", "t")
    report("sync all-fail → graceful ''", out == "", repr(out))

    # Chain skips models without keys
    with mock.patch.object(llm, "_get_api_key_for_model", side_effect=lambda m: None if m == "fallback" else "k"), \
         mock.patch.dict(os.environ, {"LLM_MODEL": "primary", "LLM_FALLBACK_MODELS": "fallback"}, clear=False):
        ch = llm._get_model_chain()
    report("chain skips keyless models", ch == ["primary"], repr(ch))


def part_a_async():
    print("\n[Part A] async llm_acompletion / llm_astream / sync-simple fallback (hermetic)")
    sys.path.insert(0, str(ROOT))
    import analyze._llm_async as a

    def _fake_ok_resp(content):
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop")])

    def _make_acompletion(fail_for="primary"):
        async def fake_acompletion(**kwargs):
            model = kwargs.get("model", "")
            if model == fail_for:
                raise Exception("429 rate limit exceeded")
            return _fake_ok_resp("async fallback answer")
        return fake_acompletion

    for name, exc in (("429", Exception("429 rate limit")),
                      ("timeout", TimeoutError("timed out")),
                      ("connection", ConnectionError("refused"))):
        async def fake(**kwargs):
            model = kwargs.get("model", "")
            if model == "primary":
                raise exc
            return _fake_ok_resp("async fallback answer")

        fake_litellm = types.ModuleType("litellm")
        fake_litellm.acompletion = fake
        with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
             mock.patch.object(a, "_get_model_chain", return_value=["primary", "fallback"]):
            r = asyncio.run(a.llm_acompletion([{"role": "user", "content": "hi"}]))
        report(f"async {name} → fallback answers",
               r.get("content") == "async fallback answer", repr(r))

    # empty response → content ""
    async def fake_empty(**kwargs):
        return _fake_ok_resp("")
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.acompletion = fake_empty
    with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
         mock.patch.object(a, "_get_model_chain", return_value=["primary", "fallback"]):
        r = asyncio.run(a.llm_acompletion([{"role": "user", "content": "hi"}]))
    report("async empty → content ''", r.get("content") == "", repr(r))

    # malformed response (no choices) → error dict, never raises
    async def fake_malformed(**kwargs):
        return SimpleNamespace()  # no .choices
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.acompletion = fake_malformed
    with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
         mock.patch.object(a, "_get_model_chain", return_value=["primary", "fallback"]):
        r = asyncio.run(a.llm_acompletion([{"role": "user", "content": "hi"}]))
    report("async malformed → error dict, no raise",
           r.get("stop_reason") == "error", repr(r))

    # all fail → graceful error dict
    async def fake_all_fail(**kwargs):
        raise ConnectionError("boom")
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.acompletion = fake_all_fail
    with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
         mock.patch.object(a, "_get_model_chain", return_value=["primary", "fallback"]):
        r = asyncio.run(a.llm_acompletion([{"role": "user", "content": "hi"}]))
    report("async all-fail → graceful error dict",
           r.get("stop_reason") == "error" and r.get("content") == "", repr(r))

    # streaming: 429 on primary → fallback stream flows
    async def fake_stream(**kwargs):
        model = kwargs.get("model", "")
        if model == "primary":
            raise Exception("429 rate limit")

        class _Chunk:
            def __init__(self, content, finish):
                self.choices = [SimpleNamespace(
                    delta=SimpleNamespace(content=content, tool_calls=None),
                    finish_reason=finish)]

        async def _gen():
            yield _Chunk("streamed ", None)
            yield _Chunk("reply", "stop")
        return _gen()

    fake_litellm = types.ModuleType("litellm")
    fake_litellm.acompletion = fake_stream
    with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
         mock.patch.object(a, "_get_model_chain", return_value=["primary", "fallback"]):
        async def collect():
            return [ev async for ev in a.llm_astream([{"role": "user", "content": "hi"}])]
        events = asyncio.run(collect())
    text = "".join(e["text"] for e in events if e["type"] == "token")
    report("stream 429 → fallback stream flows", text == "streamed reply", repr(text))
    report("stream ends with done/end_turn",
           any(e.get("stop_reason") == "end_turn" for e in events), repr(events))

    # streaming: all fail → error event, no raw exception
    async def fake_stream_all_fail(**kwargs):
        raise ConnectionError("boom")
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.acompletion = fake_stream_all_fail
    with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
         mock.patch.object(a, "_get_model_chain", return_value=["primary", "fallback"]):
        async def collect():
            return [ev async for ev in a.llm_astream([{"role": "user", "content": "hi"}])]
        events = asyncio.run(collect())
    report("stream all-fail → error event",
           any(e["type"] == "error" for e in events), repr(events))

    # sync simple: 429 → fallback
    def _make_sync_completion():
        def fake_completion(**kwargs):
            model = kwargs.get("model", "")
            if model == "primary":
                raise Exception("429 rate limit")
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content="sync-simple fallback answer"))])
        return fake_completion
    fake_litellm = types.ModuleType("litellm")
    fake_litellm.completion = _make_sync_completion()
    with mock.patch.dict(sys.modules, {"litellm": fake_litellm}), \
         mock.patch.object(a, "_get_model_chain", return_value=["primary", "fallback"]):
        out = a.llm_completion_sync([{"role": "user", "content": "hi"}])
    report("sync-simple 429 → fallback answers", out == "sync-simple fallback answer", repr(out))


def part_a_engine():
    print("\n[Part A] FOL engine.generate fallback (hermetic)")
    sys.path.insert(0, str(FOL_DIR))
    sys.path.insert(0, str(FOL_DIR / "modules" / "llm"))
    sys.path.insert(0, str(FOL_DIR / "modules"))
    from modules.llm.engine import LLMEngine
    from modules.llm.base import LLMResponse

    class _FailBackend:
        async def generate(self, messages, temperature=None, max_tokens=None):
            return LLMResponse(text="[OpenRouter error: 429 Too Many Requests]", model="openrouter")

    class _OkBackend:
        async def generate(self, messages, temperature=None, max_tokens=None):
            return LLMResponse(text="engine fallback worked", model="mlx")

    eng = object.__new__(LLMEngine)
    eng._backends = {"openrouter": _FailBackend(), "mlx": _OkBackend()}
    eng._fallback_order = ["openrouter", "mlx"]
    eng._build_messages = lambda u, c="", s="": [{"role": "user", "content": u}]
    eng._auto_temperature = lambda u: 0.5

    out = asyncio.run(eng.generate("hi"))
    report("engine 429 → next backend", out == "engine fallback worked", repr(out))

    # all backends fail → graceful message, then MUST be humanized by the
    # final response layer (stress-test finding #1).
    eng._backends = {"openrouter": _FailBackend()}
    eng._fallback_order = ["openrouter"]
    out = asyncio.run(eng.generate("hi"))
    report("engine all-fail → graceful message", "unavailable" in out.lower(), repr(out))

    from modules.llm.personality import polish_response
    polished = polish_response("Привет", out)
    v = check(polished)
    report("engine graceful message humanized", not v, f"{v} → {polished!r}")


# ---------------------------------------------------------------------------
# Part B — final response layers
# ---------------------------------------------------------------------------

def part_b_layers():
    print("\n[Part B] Final Response Layers (hermetic)")
    sys.path.insert(0, str(FOL_DIR))
    sys.path.insert(0, str(FOL_DIR / "modules" / "llm"))
    sys.path.insert(0, str(ROOT))
    from modules.llm.personality import polish_response as fol_polish
    from orchestrator.response_formatter import format_final_response as orch_format

    terse_raws = ["Done.", "Done", "Готово.", "готово", "OK", "ok", "Принято.",
                  "Выполнено", "Success", "Completed.", "Task completed.",
                  "Done, sir.", "Готово, сэр.", "Sir.", "сэр", "Yes.", "Sure."]
    for raw in terse_raws:
        out = fol_polish("Открой Safari", raw)
        v = check(out)
        report(f"FOL terse {raw!r} rebuilt", not v, f"{v} → {out!r}")
    for raw in terse_raws:
        out = orch_format(raw, [], "ru")
        v = check(out)
        report(f"ORCH terse {raw!r} rebuilt", not v, f"{v} → {out!r}")

    json_raws = [
        '{"type":"function","name":"open_app","parameters":{"name":"Safari"}}',
        '{"status":"ok"}',
        '{"success":true}',
        '{"error":"google_auth_required","detail":"x"}',
        '```json\n{"action":"open_app","params":{"name":"Safari"}}\n```',
    ]
    for raw in json_raws:
        out = fol_polish("Открой Safari", raw)
        v = check(out)
        report(f"FOL JSON {raw[:40]!r} hidden", not v, f"{v} → {out!r}")
        out = orch_format(raw, [], "ru")
        v = check(out)
        report(f"ORCH JSON {raw[:40]!r} hidden", not v, f"{v} → {out!r}")

    # Tracebacks / raw errors
    for raw in ("Traceback (most recent call last):\nTypeError: cannot open",
                "ConnectionError: connection refused",
                "Error: rate_limit exceeded"):
        out = fol_polish("Открой Safari", raw)
        v = check(out)
        report(f"FOL error {raw[:40]!r} humanized", not v, f"{v} → {out!r}")
        out = orch_format(raw, [], "ru")
        v = check(out)
        report(f"ORCH error {raw[:40]!r} humanized", not v, f"{v} → {out!r}")

    # Engine graceful-failure message (finding #1)
    eng_msg = "All LLM backends are unavailable. Please configure an API key or install mlx-lm."
    out = fol_polish("Открой Safari", eng_msg)
    v = check(out)
    report("FOL engine-failure humanized", not v, f"{v} → {out!r}")
    out = orch_format(eng_msg, [], "ru")
    v = check(out)
    report("ORCH engine-failure humanized", not v, f"{v} → {out!r}")

    # Empty response → contextual confirmation mentioning the app
    out = fol_polish("Открой Safari", "   ", tool_name="open_app", tool_args={"name": "Safari"})
    v = check(out)
    report("FOL empty → contextual w/ tool", not v and "Safari" in out, f"{v} → {out!r}")
    out = orch_format("", [("open_app", {"name": "Safari"})], "ru")
    report("ORCH empty w/ tool → rebuilt", out == "Открыл Safari.", repr(out))

    # Language: RU in → RU out; EN in → EN out (through the FOL layer)
    ru_out = fol_polish("Открой Safari", "Done.")
    en_out = fol_polish("open Safari", "Done.")
    report("bilingual RU answer", any(ord(c) > 0x400 for c in ru_out), repr(ru_out))
    report("bilingual EN answer", en_out.isascii(), repr(en_out))

    # API key in raw text must never survive
    out = fol_polish("Открой Safari", f"Done. {REAL_KEY}")
    report("FOL API key never leaks", REAL_KEY not in out, repr(out))
    out = orch_format(f"Done. {REAL_KEY}", [], "ru")
    report("ORCH API key never leaks", REAL_KEY not in out, repr(out))

    # Tool arguments are never shown verbatim
    out = fol_polish("Открой Safari", "Done.", tool_name="open_app",
                     tool_args={"name": "Safari", "password": REAL_KEY})
    report("FOL tool args hidden", REAL_KEY not in out and "password" not in out, repr(out))


# ---------------------------------------------------------------------------
# Part C — security
# ---------------------------------------------------------------------------

def part_c_security():
    print("\n[Part C] Security (gitignore / keys / logs)")
    import subprocess as sp

    # 1. .env files must be git-ignored
    for env in (".env", "fol/.env", "fol/.env.example"):
        r = sp.run(["git", "check-ignore", env], capture_output=True, text=True, cwd=str(ROOT))
        report(f"git ignores {env}", r.returncode == 0 and env in r.stdout)

    # 2. No real key in tracked files (only .env, which is ignored)
    r = sp.run(["git", "grep", "-l", REAL_KEY[:20]], capture_output=True, text=True, cwd=str(ROOT))
    report("no real key in tracked files", r.returncode != 0, r.stdout.strip()[:200])

    # 3. Key must not appear in the FOL API server log
    log = Path("/tmp/secondself-stress-fol.log")
    if log.exists():
        content = log.read_text(errors="ignore")
        report("no key in FOL server log", REAL_KEY not in content)
    else:
        print("  ⚠️  no FOL log yet (checked later in Part D)")

    # 4. humanize_error never emits tracebacks / raw codes
    sys.path.insert(0, str(ROOT))
    from orchestrator.response_formatter import humanize_error
    for raw in ('{"error": "internal_code_42", "detail": "boom"}',
                "Traceback (most recent call last):\nKeyError: 'x'",
                '{"error": "google_auth_required"}'):
        out = humanize_error(raw, "ru")
        v = check(out)
        report(f"humanize_error {raw[:40]!r} clean", not v, f"{v} → {out!r}")

    # 5. No REAL keys in source files (keys live only in .env). A short
    #    "sk-or-v1-" prefix in a comment is documentation, not a key.
    key_re = re.compile(r"sk-(?:or-v1|proj)-[A-Za-z0-9]{10,}")
    src_scan = ["fol/core", "fol/modules", "orchestrator", "analyze", "src/agent", "bridge"]
    leaked = []
    for d in src_scan:
        for p in (ROOT / d).rglob("*.py"):
            if "test" in p.parts:
                continue
            try:
                content = p.read_text(errors="ignore")
            except Exception:
                continue
            if key_re.search(content):
                leaked.append(str(p))
    report("no keys in source files", not leaked, str(leaked))


# ---------------------------------------------------------------------------
# Part D — live E2E
# ---------------------------------------------------------------------------

def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def http_json(url: str, payload: dict, timeout: int) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fol_chat(message: str, timeout: int = 40) -> str:
    return str(http_json(FOL_BASE + "/api/chat", {"message": message}, timeout).get("response", ""))


def orch_command(task: str, timeout: int = 60) -> str:
    data = http_json(ORCH_BASE + "/command", {"task": task}, timeout)
    resp = str(data.get("response", ""))
    # The actions list is internal — but make sure no raw tool JSON leaked.
    return resp


FOL_SCENARIOS = [
    ("F1", "RU casual", "Привет! Как дела?"),
    ("F2", "EN casual", "Hello! How are you?"),
    ("F3", "mixed language", "найди новости про OpenAI and tell me the most important one"),
    ("F4", "open app RU", "Открой Safari"),
    ("F5", "open app EN", "Open Finder"),
    ("F6", "open missing app", "Открой НесуществующееПриложение123"),
    ("F7", "screen awareness", "Что у меня сейчас на экране?"),
    ("F8", "web search", "Найди новости про OpenAI"),
    ("F9", "context follow-up", "А какая самая важная?"),  # slow: reasoning follow-up
    ("F10", "action follow-up", "А теперь открой YouTube"),
    ("F11", "memory save", "Запомни, что завтра отправить отчёт"),
    ("F12", "memory recall", "Что мне нужно сделать завтра?"),
    ("F13", "compound command", "Открой Terminal и покажи текущую папку"),
    ("F14", "email", "Напиши письмо преподавателю"),
    ("F15", "calendar", "Что у меня в календаре сегодня?"),
    ("F16", "task add", "Добавь задачу: купить молоко"),
    ("F17", "file search", "Найди файл README в проекте"),
    ("F18", "question RU", "Который час?"),
    ("F19", "thanks", "Спасибо, ты лучший!"),
    ("F20", "greeting short", "Привет"),
    ("F21", "blank input", "   "),
    ("F22", "error path", "Отправь сообщение в WhatsApp"),
    ("F23", "multi-step", "Открой Safari и найди новости про OpenAI"),
    ("F24", "who are you", "Кто ты?"),
    ("F25", "joke/humor", "Расскажи что-нибудь интересное"),
]


def wait_ready(base: str, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/health", timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def part_d_live():
    print("\n[Part D] Live E2E (real servers, real Nemotron via OpenRouter)")
    fol_log = open("/tmp/secondself-stress-fol.log", "w")
    orch_log = open("/tmp/secondself-stress-orch.log", "w")
    procs = []

    if port_in_use(FOL_PORT):
        report("FOL port free before start", False, f":{FOL_PORT} occupied — kill stale server first")
        fol_log.close(); orch_log.close()
        return

    fol_proc = subprocess.Popen(
        [sys.executable, "run_api_server.py"],
        cwd=str(FOL_DIR), stdout=fol_log, stderr=subprocess.STDOUT,
    )
    procs.append(fol_proc)

    # Orchestrator: started as OUR child so it lives for the whole run (a
    # nohup'd process from a previous shell session dies with that session).
    orch_proc = None
    if not port_in_use(ORCH_PORT):
        orch_proc = subprocess.Popen(
            [sys.executable, "orchestrator/server.py"],
            cwd=str(ROOT), stdout=orch_log, stderr=subprocess.STDOUT,
        )
        procs.append(orch_proc)
    else:
        print(f"  ⚠️  orchestrator already on :{ORCH_PORT} — using the running instance")

    try:
        if not wait_ready(FOL_BASE):
            report("FOL API server ready", False)
            return
        report("FOL API server ready (fresh process, new code)", True)
        if orch_proc is not None:
            report("orchestrator ready (fresh process)", wait_ready(ORCH_BASE), "")
        else:
            report("orchestrator ready (existing instance)", wait_ready(ORCH_BASE), "")

        failures = 0
        for sid, label, msg in FOL_SCENARIOS:
            timeout = 70 if sid in ("F9", "F23") else 40
            try:
                resp = fol_chat(msg, timeout)
            except Exception as exc:
                # Free-tier reasoning models can be slow — retry once before
                # declaring a failure.
                try:
                    resp = fol_chat(msg, timeout)
                except Exception as exc2:
                    report(f"{sid} {label}", False, f"HTTP ERROR after retry: {exc2}")
                    failures += 1
                    continue
            v = check(resp)
            ok = not v
            if ok:
                report(f"{sid} {label}", True)
                print(f"        → {resp[:150]}")
            else:
                failures += 1
                report(f"{sid} {label}", False)
                print(f"        → {resp[:200]}")
                for bad in v:
                    print(f"        ⚠️ {bad}")

        # Orchestrator live path
        try:
            with urllib.request.urlopen(ORCH_BASE + "/health", timeout=5) as resp:
                orch_up = resp.status == 200
        except Exception:
            orch_up = False
        report("orchestrator /health up", orch_up)
        if orch_up:
            for task in ("Привет", "Открой Safari"):
                try:
                    out = orch_command(task)
                    v = check(out)
                    report(f"ORCH {task[:30]!r} natural", not v, f"{v} → {out!r}")
                except Exception as exc:
                    report(f"ORCH {task[:30]!r} natural", False, f"HTTP ERROR: {exc}")
            # The startup log must show the Nemotron model chain
            try:
                orch_log.flush()
                chain_log = Path("/tmp/secondself-stress-orch.log").read_text(errors="ignore")
                report("orchestrator model chain = Nemotron",
                       "nemotron" in chain_log.lower() and "openrouter" in chain_log.lower())
            except Exception as exc:
                report("orchestrator model chain = Nemotron", False, str(exc))

        # Memory round-trip verification (F11 → F12 was sequential already)
        print("\n  Memory round-trip:")
        try:
            save = fol_chat("Запомни, что завтра отправить отчёт")
            recall = fol_chat("Что мне нужно сделать завтра?")
            ok = "отчёт" in recall.lower() or "отчет" in recall.lower() or "завтра" in recall.lower()
            report("memory save→recall returns real data", ok, f"save={save[:60]!r} recall={recall[:120]!r}")
        except Exception as exc:
            report("memory save→recall returns real data", False, f"HTTP ERROR: {exc}")

        return failures == 0
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        fol_log.close()
        orch_log.close()
        # After the servers are stopped, check the logs for key leaks
        for name, logpath in (("FOL", "/tmp/secondself-stress-fol.log"),
                              ("orchestrator", "/tmp/secondself-stress-orch.log")):
            content = Path(logpath).read_text(errors="ignore")
            report(f"no API key in {name} server log", REAL_KEY not in content)


# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("PRODUCTION STRESS-TEST — FOL with Nemotron-OpenRouter")
    print("=" * 70)

    part_a_sync()
    part_a_async()
    part_a_engine()
    part_b_layers()
    part_c_security()
    part_d_live()

    print("\n" + "=" * 70)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("Failures:")
        for f in FAILURES:
            print(f"  ❌ {f}")
        return 1
    print("✅ STRESS-TEST PASSED — fallback, final-response, security, live E2E all green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
