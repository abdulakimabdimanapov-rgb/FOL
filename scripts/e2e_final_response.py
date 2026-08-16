#!/usr/bin/env python3
"""E2E — FINAL RESPONSE LAYER acceptance (spec section 17).

Starts the REAL FOL API server (fol/run_api_server.py) and drives the
S1–S12 scenarios through the real HTTP pipeline (the same code the voice
and text UIs use). Every answer must be a natural, non-terse, honorific-free
sentence in the user's language.

NOTE: S1/S6/S8/S11 perform REAL Mac actions (open Safari, Google search,
Terminal, YouTube) — the spec explicitly requires testing them for real.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOL_DIR = ROOT / "fol"
PORT = 8754
BASE = f"http://127.0.0.1:{PORT}"

FORBIDDEN = {"done", "готово", "ok", "принято", "выполнено", "сделано",
             "success", "completed", "task completed", "yes", "успешно"}

SCENARIOS = [
    ("S1", "Открой Safari"),
    ("S2", "Открой проект FOL"),
    ("S3", "Запомни, что завтра отправить отчёт"),
    ("S4", "Что мне нужно сделать завтра?"),
    ("S5", "Что у меня сейчас на экране?"),
    ("S6", "Найди новости про OpenAI"),
    ("S7", "А какая самая важная?"),
    ("S8", "Открой Terminal и покажи текущую папку"),
    ("S9", "Напиши письмо преподавателю"),
    ("S10", "Привет, расскажи что-нибудь интересное"),
    ("S11a", "Открой Safari"),
    ("S11b", "А теперь YouTube"),
]


def check(text: str) -> list[str]:
    """Return a list of violations; empty means the answer is acceptable."""
    violations = []
    t = (text or "").strip()
    if not t:
        violations.append("EMPTY")
        return violations
    stripped = t.rstrip(".!").strip().lower()
    if stripped in FORBIDDEN:
        violations.append(f"BARE CONFIRMATION: {text!r}")
    if "traceback" in t.lower() or "exception" in t.lower():
        violations.append("TRACEBACK/EXCEPTION")
    if t.startswith("{") and "}" in t:
        violations.append("JSON")
    if re_search_tool_names(t):
        violations.append("TOOL/JSON LEAK")
    if re.search(r"\bsir\b|\bсэр\b", t, re.IGNORECASE):
        violations.append("HONORIFIC")
    return violations


def re_search_tool_names(t: str) -> bool:
    return bool(re.search(r"\b(tool_call|tool_result|open_app|function_call|parameters)\b", t, re.IGNORECASE))


def api_chat(message: str, timeout: int = 25) -> str:
    body = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        BASE + "/api/chat", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return str(data.get("response", ""))


def port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_ready(timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            time.sleep(1)
    return False


def main() -> int:
    # Fail loudly if another FOL server (possibly with OLD code) is already
    # listening — otherwise we would silently test the wrong process.
    if port_in_use(PORT):
        print(f"❌ Port {PORT} is already in use by another process.")
        print("   Kill it first (e.g. lsof -iTCP:8754 -sTCP:LISTEN) so this E2E")
        print("   runs against the freshly started server with the new code.")
        return 1
    proc = subprocess.Popen(
        [sys.executable, "run_api_server.py"],
        cwd=str(FOL_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_ready():
            print("❌ FOL API server did not become ready")
            return 1
        print(f"✅ FOL API server ready on :{PORT}\n")

        failures = 0
        for sid, msg in SCENARIOS:
            try:
                resp = api_chat(msg)
            except Exception as exc:
                print(f"  {sid:5s} «{msg}» → ⚠️ HTTP ERROR: {exc}")
                failures += 1
                continue
            v = check(resp)
            status = "✅" if not v else "❌"
            if v:
                failures += 1
            print(f"  {status} {sid:5s} «{msg}»")
            print(f"        → {resp[:160]}")
            for bad in v:
                print(f"        ⚠️ {bad}")

        # S12 — tool error path (direct, hermetic).
        print("\n  S12 tool-error path (hermetic):")
        from pathlib import Path as _P
        import sys as _sys

        _sys.path.insert(0, str(FOL_DIR))
        _sys.path.insert(0, str(FOL_DIR / "modules" / "llm"))
        from modules.llm.personality import polish_response

        for raw in (
            "Traceback (most recent call last):\nTypeError: cannot open",
            '{"error": "google_auth_required", "detail": "x"}',
            "Done.",
        ):
            out = polish_response("Открой Safari", raw)
            v = check(out)
            status = "✅" if not v else "❌"
            if v:
                failures += 1
            print(f"  {status} raw={raw[:50]!r}")
            print(f"        → {out[:120]}")
            for bad in v:
                print(f"        ⚠️ {bad}")

        print(f"\n{'=' * 60}")
        if failures:
            print(f"❌ {failures} scenario(s) failed")
            return 1
        print("✅ ALL E2E SCENARIOS PASSED — no bare Done/Готово/OK, no JSON, no sir")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
