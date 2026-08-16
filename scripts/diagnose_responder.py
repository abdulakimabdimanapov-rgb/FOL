#!/usr/bin/env python3
"""
diagnose_responder.py — Проверка «почему FOL не отвечает / не выполняет команды».

Прогоняет всю цепочку ответа ассистента и печатает PASS/FAIL по каждому звену:

  1. Health всех сервисов (orchestrator 8420, agent-server 8421, bridge 8422,
     dashboard 8423, FOL 8754, fastapi 8000, ollama 11434)
  2. Состояние job state machine orchestrator (застрял ли в thinking/working)
  3. POST /chat (SSE) — стриминговый ответ: приходят ли токены, чем завершается
  4. POST /command (sync) — синхронный ответ: есть ли natural-language message
  5. Прямой вызов LLM через llm_bridge — работает ли модель вообще
  6. FOL /api/chat — отвечает ли ядро FOL на встроенные команды (time/status)
  7. Agent-server /tool/* — исполняются ли десктопные инструменты
  8. /api/runtime — какие ошибки orchestrator записал в лог (LLM/tools)

Запуск (скрипт):
    python3 scripts/diagnose_responder.py

Импорт (pytest): функции и константы этого модуля переиспользуются в
``tests/test_diagnose_responder.py``.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ORCH = "http://127.0.0.1:8420"
AGENT = "http://127.0.0.1:8421"
BRIDGE = "http://127.0.0.1:8422"
DASH = "http://127.0.0.1:8423"
FOL = "http://127.0.0.1:8754"
FASTAPI = "http://127.0.0.1:8000"
OLLAMA = "http://127.0.0.1:11434"

PASS, FAIL, SKIP = "✅ PASS", "❌ FAIL", "⏭ SKIP"
_results: list[tuple[str, str, str]] = []  # (section, message, status)

# The canned fallback that the Response Formatter emits when the model
# produced no usable text (empty / bare confirmation / tool-call JSON).
# Its presence in a response means the LLM chain failed — a key symptom.
# KEEP IN SYNC with orchestrator/response_formatter._natural_final_fallback.
_CANNED_FALLBACKS = (
    "Сделано. Могу помочь с чем-то ещё?",
    "All set. Anything else I can help with?",
    "All 1 model(s) failed",
)


def is_canned_stub(text: str) -> bool:
    """True when ``text`` contains a known canned-fallback stub.

    The stub is emitted by the Response Formatter when the model produced no
    usable text — its presence means the LLM chain degraded. Used both by the
    CLI diagnostics and by the pytest auto-check (a live response must never
    be a stub).
    """
    return any(m in (text or "") for m in _CANNED_FALLBACKS)


def check(section: str, msg: str, ok: bool, detail: str = "") -> None:
    status = PASS if ok else FAIL
    _results.append((section, msg, status))
    line = f"  {status}  {msg}"
    if detail:
        line += f"  —  {detail[:300]}"
    print(line)


def reset_results() -> None:
    """Clear collected results (used by the pytest wrapper for isolation)."""
    _results.clear()


def _http(url: str, body: dict | None = None, timeout: float = 10) -> tuple[int, dict]:
    """GET (body=None) or POST JSON. Returns (status, parsed_json_or_text)."""
    req = urllib.request.Request(url, method="GET" if body is None else "POST")
    if body is not None:
        req.data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, {"_raw": raw[:500]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"_raw": raw[:500]}
    except Exception as e:
        return 0, {"error": str(e)}


def sse_post(url: str, body: dict, timeout: float = 45) -> tuple[int, list[dict], str]:
    """POST /chat and parse SSE events. Returns (status, events, raw_tail)."""
    req = urllib.request.Request(url, method="POST")
    req.data = json.dumps(body).encode()
    req.add_header("Content-Type", "application/json")
    events: list[dict] = []
    raw_tail = ""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buf = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buf += chunk
                # parse complete SSE blocks
                while b"\n\n" in buf:
                    block, buf = buf.split(b"\n\n", 1)
                    event = {"event": "message", "data": ""}
                    for line in block.decode("utf-8", "replace").splitlines():
                        if line.startswith("event:"):
                            event["event"] = line[6:].strip()
                        elif line.startswith("data:"):
                            event["data"] = line[5:].strip()
                    try:
                        parsed = json.loads(event["data"]) if event["data"] else {}
                        events.append({"event": event["event"], **parsed})
                    except Exception:
                        events.append({"event": event["event"], "data": event["data"]})
            raw_tail = buf.decode("utf-8", "replace")[:500]
            return resp.status, events, raw_tail
    except Exception as e:
        return 0, events, str(e)


def get(path: str, timeout: float = 10) -> tuple[int, dict]:
    return _http(path, timeout=timeout)


def post(path: str, body: dict, timeout: float = 90) -> tuple[int, dict]:
    return _http(path, body, timeout=timeout)


# ---------------------------------------------------------------------------
# Sections — each returns True when its checks all passed
# ---------------------------------------------------------------------------

def run_health() -> bool:
    print("\n[1] Здоровье сервисов")
    services = [
        ("orchestrator", ORCH + "/health", True),
        ("agent-server", AGENT + "/health", True),
        ("bridge", BRIDGE + "/health", True),
        ("dashboard", DASH + "/health", True),
        ("fol-api", FOL + "/health", True),
        ("fastapi", FASTAPI + "/health", True),
        ("ollama", OLLAMA + "/api/tags", False),
    ]
    all_ok = True
    for name, url, required in services:
        st, data = get(url, timeout=3)
        ok = st == 200
        all_ok = all_ok and ok
        detail = ""
        if isinstance(data, dict):
            if "status" in data:
                detail = f"status={data['status']}"
            elif "version" in data:
                detail = f"version={data.get('version')}"
            else:
                detail = str(data)[:120]
        elif isinstance(data, dict) and "_raw" in data:
            detail = data["_raw"][:120]
        check("health", name, ok, detail)
        if not ok and required:
            print(f"\n  ⛔ {name} недоступен — дальнейшие проверки могут быть неинформативны")
    return all_ok


def run_job_state() -> bool:
    print("\n[2] Состояние job state machine (orchestrator)")
    st, data = get(ORCH + "/status", timeout=5)
    if st == 200 and isinstance(data, dict):
        state = data.get("state", "?")
        ok = state in ("idle", "complete", "error")
        check("job", f"state={state}", ok, f"task={str(data.get('task'))[:80]}")
        if state in ("thinking", "working"):
            print("  ⚠️  Orchestrator ЗАСТРЯЛ в состоянии", state,
                  "— новые сообщения будут поставлены в очередь (HTTP 202 queued)")
        return ok
    check("job", f"/status -> HTTP {st}", False, str(data)[:200])
    return False


def run_chat_sse() -> bool:
    print("\n[3] POST /chat (SSE стриминг) — 'Привет, как дела?'")
    t0 = time.time()
    st, events, tail = sse_post(ORCH + "/chat", {"message": "Привет, как дела?"}, timeout=60)
    dt = time.time() - t0
    ok = True
    if st == 200 and events:
        kinds = [e.get("event") for e in events]
        text = "".join(e.get("text", "") for e in events if e.get("text"))
        final_state = next((e.get("state") for e in reversed(events) if e.get("state")), None)
        check("chat", f"HTTP 200, {len(events)} events, {dt:.1f}s", True,
              f"events={kinds[:6]} final_state={final_state}")
        check("chat", f"есть текстовые токены ({len(text)} chars)", bool(text.strip()),
              repr(text[:150]))
        if text.strip():
            bad_leak = any(m in text for m in ("<invoke>", "tool_use", "```json", "❌", "Error:"))
            check("chat", "ответ — чистый natural language (без JSON/ошибок)", not bad_leak,
                  repr(text[:150]))
            if not bad_leak:
                canned = is_canned_stub(text)
                check("chat", "ответ — НЕ заготовка-заглушка «Сделано…»", not canned,
                      repr(text[:150]))
                ok = not canned
        else:
            ok = False
    elif st == 202:
        check("chat", "HTTP 202 QUEUED (orchestrator занят)", False, str(events)[:200] + tail[:100])
        ok = False
    else:
        check("chat", f"HTTP {st} / {dt:.1f}s", False, str(events)[:200] + tail[:200])
        ok = False
    return ok


def run_command() -> bool:
    print("\n[4] POST /command (синхронный) — 'Открой Калькулятор' (требует инструмент open_app)")
    t0 = time.time()
    st, data = post(ORCH + "/command", {"task": "Открой Калькулятор"}, timeout=90)
    dt = time.time() - t0
    ok = False
    if st == 200 and isinstance(data, dict):
        resp = data.get("response", "")
        actions = data.get("actions", [])
        check("command", f"HTTP 200, {dt:.1f}s, response={len(resp)} chars", bool(resp.strip()),
              repr(resp[:150]))
        tool_calls = [a for a in (actions or []) if a.get("type") == "tool_call"]
        if tool_calls:
            check("command", f"инструменты вызваны: {[a.get('tool') for a in tool_calls]}", True)
            failed = [a for a in tool_calls
                      if isinstance(a.get("result"), dict) and "error" in a["result"]]
            check("command",
                  f"вызовы инструментов без ошибок ({len(tool_calls) - len(failed)}/{len(tool_calls)})",
                  not failed)
            ok = not failed
        else:
            # Нет вызова инструмента — но это нормально, если модель дала
            # осмысленный ответ (напр. приложение уже открыто). Критично,
            # чтобы ответ НЕ был заготовкой-заглушкой «Сделано…».
            canned = is_canned_stub(resp)
            check("command", "ответ осмысленный (без вызова инструмента)",
                  bool(resp.strip()) and not canned, repr(resp[:120]))
            ok = bool(resp.strip()) and not canned
    else:
        check("command", f"HTTP {st} / {dt:.1f}s", False, str(data)[:250])
    return ok


def run_llm() -> bool:
    print("\n[5] Прямой вызов LLM (llm_bridge.llm_completion_sync)")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from llm_bridge import llm_completion_sync
        t0 = time.time()
        out = llm_completion_sync([{"role": "user", "content": "Скажи: привет"}],
                                  system="Отвечай одним словом.")
        dt = time.time() - t0
        ok = bool(out.strip()) and not is_canned_stub(out)
        check("llm", f"llm_completion_sync вернул текст ({len(out)} chars, {dt:.1f}s)", ok,
              repr(out[:150]))
        return ok
    except Exception as e:
        check("llm", "llm_completion_sync не отработал", False, str(e)[:250])
        return False


def run_fol_chat() -> bool:
    print("\n[6] FOL /api/chat (встроенные команды ядра)")
    ok = True
    for cmd in ("time", "status"):
        t0 = time.time()
        st, data = post(FOL + "/api/chat", {"message": cmd}, timeout=60)
        dt = time.time() - t0
        resp = data.get("response", "") if isinstance(data, dict) else str(data)
        good = st == 200 and bool(resp.strip()) and not resp.startswith("Error:")
        ok = ok and good
        check("fol", f"'{cmd}' -> {dt:.1f}s", good, repr(resp[:150]))
    return ok


def run_agent_tools() -> bool:
    print("\n[7] Agent-server: исполнение инструментов")
    ok = True
    for endpoint, body in [
        ("/tool/clipboard_get", {}),
        ("/tool/screen_size", {}),
    ]:
        st, data = post(AGENT + endpoint, body, timeout=15)
        good = st == 200 and not (isinstance(data, dict) and "error" in data)
        ok = ok and good
        detail = str(data)[:150]
        if endpoint == "/tool/clipboard_get" and isinstance(data, dict) and data.get("text"):
            # Не выводим содержимое буфера обмена пользователя в лог.
            data = {**data, "text": "<truncated>"}
            detail = str(data)[:150]
        check("agent-tool", f"{endpoint} -> HTTP {st}", good, detail)
    return ok


def run_runtime() -> bool:
    print("\n[8] /api/runtime — ошибки, записанные orchestrator'ом")
    st, data = get(ORCH + "/api/runtime", timeout=5)
    ok = True
    if st == 200 and isinstance(data, dict):
        errors = data.get("errors", []) or data.get("error_log", [])
        tools = data.get("tools", []) or data.get("tool_calls", []) or data.get("tool_call_log", [])
        if errors:
            for e in errors[-10:]:
                print(f"  ❌ [{e.get('source')}] {e.get('message', '')[:160]}")
            check("runtime", f"записано ошибок: {len(errors)}", False,
                  f"последняя: {str(errors[-1])[:150]}")
            ok = False
        else:
            check("runtime", "ошибок в логе нет", True)
        if tools:
            fails = [t for t in tools if not t.get("ok", True)]
            print(f"  ℹ️  инструментов вызвано: {len(tools)}, из них неудачных: {len(fails)}")
            if fails:
                check("runtime", f"неудачных вызовов инструментов: {len(fails)}", False,
                      str(fails[-3:]))
                ok = False
    else:
        check("runtime", f"/api/runtime -> HTTP {st}", False, str(data)[:200])
        ok = False
    return ok


def run_all() -> bool:
    """Run every diagnostic section; returns True when all checks passed."""
    reset_results()
    print("=" * 72)
    print("FOL RESPONDER DIAGNOSTICS — проверка «не отвечает / не выполняет»")
    print("=" * 72)
    run_health()
    run_job_state()
    run_chat_sse()
    run_command()
    run_llm()
    run_fol_chat()
    run_agent_tools()
    run_runtime()

    print("\n" + "=" * 72)
    fails = [r for r in _results if r[2] == FAIL]
    print(f"ИТОГ: {len(_results) - len(fails)}/{len(_results)} проверок прошло"
          + (f", {len(fails)} НЕ ПРОШЛО" if fails else ""))
    if fails:
        print("\nПроваленные проверки:")
        for section, msg, status in fails:
            print(f"  {status}  [{section}] {msg}")
    print("=" * 72)
    return not fails


def main() -> int:
    return 0 if run_all() else 1


if __name__ == "__main__":
    sys.exit(main())
