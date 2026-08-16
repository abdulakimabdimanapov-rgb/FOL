#!/usr/bin/env python3
"""Live verification: FOL engine + orchestrator chain now use
nvidia/nemotron-3-ultra-550b-a55b:free via OpenRouter."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOL_DIR = ROOT / "fol"
PORT = 8754
BASE = f"http://127.0.0.1:{PORT}"


def port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    # 1) Orchestrator / analyze model chain — must show Nemotron via OpenRouter
    sys.path.insert(0, str(ROOT))
    from analyze._llm import _get_model_chain, _get_api_key_for_model

    chain = _get_model_chain()
    print("ORCHESTRATOR model chain:", [m for m in chain if m])
    primary = chain[0] if chain else ""
    print("  primary:", primary)
    key = _get_api_key_for_model(primary)
    print("  primary key configured:", bool(key), "(provider: openrouter)" if "openrouter" in primary else "")

    # 2) FOL engine settings
    sys.path.insert(0, str(FOL_DIR))
    from config.settings import settings

    print("\nFOL settings: backend=%s openrouter_model=%s" % (
        settings.llm_backend,
        settings.openrouter_model,
    ))

    # 3) Start the real FOL API server and chat through it
    if port_in_use(PORT):
        print(f"\n❌ Port {PORT} busy — kill the stale server first")
        return 1

    proc = subprocess.Popen(
        [sys.executable, "run_api_server.py"],
        cwd=str(FOL_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(BASE + "/health", timeout=3) as r:
                    if r.status == 200:
                        break
            except Exception:
                time.sleep(1)
        else:
            print("❌ server not ready")
            return 1

        with urllib.request.urlopen(BASE + "/api/status", timeout=5) as r:
            status = json.loads(r.read().decode())
        print("\nFOL /api/status llm backends:", status.get("llm"))
        print("FOL tools:", status.get("tools"))

        for msg in ("Привет! Как дела?",
                    "Открой Safari",
                    "Что такое OpenRouter?"):
            body = json.dumps({"message": msg}).encode()
            req = urllib.request.Request(BASE + "/api/chat", data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    resp = json.loads(r.read().decode()).get("response", "")
                print(f"\n  «{msg}»\n  → {resp[:220]}")
            except Exception as exc:
                print(f"\n  «{msg}» → ⚠️ {exc}")

        print("\n✅ LIVE CHECK DONE")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
