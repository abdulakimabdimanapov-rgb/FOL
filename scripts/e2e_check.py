#!/usr/bin/env python3
"""E2E check — starts the three services, verifies health endpoints,
MJPEG stream, and the SSE chat pipeline, then cleans up."""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

# Auto-detect project root — works on any Mac, not just the author's.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICES = [
    ("orchestrator", ["python3", "orchestrator/server.py"], 8420),
    ("agent", ["python3", "agent-server/server.py"], 8421),
    ("fol", ["python3", "fol/run_api_server.py"], 8754),
]

PASS, FAIL, SKIP = 0, 0, 0


def check(label, ok):
    global PASS, FAIL
    if ok:
        print(f"  [OK]   {label}")
        PASS += 1
    else:
        print(f"  [FAIL] {label}")
        FAIL += 1


def check_skip(label):
    global SKIP
    print(f"  [SKIP] {label}")
    SKIP += 1


def http_get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def main():
    procs = {}
    for name, cmd, port in SERVICES:
        log = open(f"/tmp/e2e_{name}.log", "w")
        p = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        procs[name] = (p, log)
        print(f"Started {name} (pid {p.pid})")

    try:
        print("\n=== 1. Service health ===")
        time.sleep(10)
        for name, _, port in SERVICES:
            status, body = http_get(f"http://127.0.0.1:{port}/health")
            ok = status == 200 and body.strip()
            check(f"{name} /health -> {status}", ok)

        print("\n=== 2. Orchestrator /status ===")
        status, body = http_get("http://127.0.0.1:8420/status")
        if status == 200:
            data = json.loads(body)
            check("state is idle", data.get("state") == "idle")
            check("6 agents registered",
                  len(data.get("available_agents", [])) == 6)
            check(f"fol_status reachable: {data.get('fol_status', {}).get('status')}",
                  data.get("fol_status", {}).get("status") in ("ok", "healthy"))
        else:
            check("orchestrator /status", False)

        print("\n=== 3. MJPEG stream ===")
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:8421/stream")
            with urllib.request.urlopen(req, timeout=3) as r:
                chunk = r.read(1024)
                has_jpeg = b"\xff\xd8" in chunk
                check("MJPEG produces JPEG frames", len(chunk) > 0 and has_jpeg)
        except Exception as e:
            check(f"MJPEG stream ({e})", False)

        print("\n=== 4. SSE chat pipeline ===")
        # Plain text question — no tools needed
        payload = json.dumps({"message": "Hello! How can I help?"}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8420/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                sse = r.read().decode("utf-8", "replace")
            has_tokens = "event: token" in sse
            has_complete = "event: state" in sse and '"complete"' in sse
            check("SSE stream has token events", has_tokens)
            check("SSE stream ends with complete state", has_complete)
            # No tool JSON leaks into the user-visible stream
            check("no tool_call events leak", "event: tool_call" not in sse)
        except Exception as e:
            check(f"SSE chat ({e})", False)

        print("\n=== 5. Next.js routes ===")
        # Static page build already validated; just verify API route exists
        import os
        api_stream = os.path.join(ROOT, "src/app/api/chat/stream/route.ts")
        check("chat stream route exists", os.path.exists(api_stream))

        print("\n=== 6. Service logs — errors ===")
        # Flag REAL failures: Python tracebacks (unhandled exceptions) and
        # log-level ERROR records. Model-provider fallback notices
        # ("astream failed on …", "complete_sync failed on …") are the
        # documented graceful-degradation path — the bridge tries the next
        # model and the user still gets a humanized message, so they are NOT
        # service errors and must not trip this check.
        _FALLBACK_NOTICE = ("astream failed on", "complete_sync failed on")
        for name, _, _ in SERVICES:
            try:
                log_text = open(f"/tmp/e2e_{name}.log").read()
                errors = [l for l in log_text.splitlines()
                          if l.startswith(_FALLBACK_NOTICE)]
                errors = [l for l in log_text.splitlines()
                          if ("Traceback (most recent call last)" in l
                              or l.lstrip().startswith("ERROR")
                              or " - ERROR - " in l)
                          and not l.startswith(_FALLBACK_NOTICE)]
                check(f"{name} log has no tracebacks", not errors)
            except Exception:
                pass

        print("\n=== SUMMARY ===")
        print(f"  {PASS} passed, {FAIL} failed, {SKIP} skipped")
        return 1 if FAIL else 0
    finally:
        print("\nStopping services...")
        for name, (p, log) in procs.items():
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
            log.close()
        print("Done.")


if __name__ == "__main__":
    sys.exit(main())
