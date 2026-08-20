#!/usr/bin/env python3
"""Start all FOL services as detached daemons.

Uses double-fork + setsid so the processes survive the launching shell
(basher kills the whole process group on exit). Logs go to /tmp.

Usage:
    python3 scripts/start_services.py          # start all three backends
    python3 scripts/start_services.py --web    # also start Next.js on :3000
    python3 scripts/start_services.py --swift  # also start the SwiftUI app
    python3 scripts/start_services.py --status # show what's running
    python3 scripts/start_services.py --stop   # stop everything
"""

import os
import socket
import subprocess
import sys
from typing import Optional

ROOT = "/Users/abulakimabdimanapov/Desktop/Fol"

SERVICES = [
    ("orchestrator", 8420, ["python3", "orchestrator/server.py"], "orchestrator.log"),
    ("agent", 8421, ["python3", "agent-server/server.py"], "agent_server.log"),
    ("fol", 8754, ["python3", "fol/run_api_server.py"], "fol_server.log"),
]

WEB_PORT = 3000


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def daemonize(cmd: list[str], log_path: str, cwd: Optional[str] = None) -> Optional[int]:
    """Double-fork + setsid so the child survives shell exit."""
    pid = os.fork()
    if pid > 0:
        return pid  # parent returns the intermediate pid
    # first child
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    # grandchild — fully detached
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.chdir(cwd or ROOT)
    try:
        os.execvp(cmd[0], cmd)
    except Exception as e:
        with open(log_path, "a") as f:
            f.write(f"Failed to exec {cmd}: {e}\n")
        os._exit(1)


def find_pids() -> dict:  # name -> Optional[int]
    """Map service name -> pid listening on its port (if any)."""
    result = {}
    for name, port, _, _ in SERVICES:
        pid = None
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            pid = int(out.splitlines()[0]) if out else None
        except Exception:
            pid = None
        result[name] = pid
    return result


def stop_all():
    for name, port, _, _ in SERVICES:
        pids = find_pids()
        pid = pids.get(name)
        if pid:
            print(f"  stopping {name} (pid {pid})")
            subprocess.run(["kill", str(pid)], capture_output=True)
    print("Done.")


def status():
    pids = find_pids()
    for name, port, _, _ in SERVICES:
        pid = pids.get(name)
        if pid:
            print(f"  [RUNNING] {name} :{port} (pid {pid})")
        else:
            print(f"  [STOPPED] {name} :{port}")
    if port_busy(WEB_PORT):
        print(f"  [RUNNING] web :{WEB_PORT}")
    else:
        print(f"  [STOPPED] web :{WEB_PORT}")


def main():
    args = sys.argv[1:]
    if "--status" in args:
        status()
        return 0
    if "--stop" in args:
        stop_all()
        return 0

    want_web = "--web" in args
    want_swift = "--swift" in args

    print("Starting FOL services...")
    for name, port, cmd, log in SERVICES:
        if port_busy(port):
            print(f"  [SKIP] {name} already running on :{port}")
            continue
        pid = daemonize(cmd, os.path.join("/tmp", log))
        print(f"  [START] {name} :{port} (forked pid {pid}, log /tmp/{log})")

    if want_web:
        if port_busy(WEB_PORT):
            print(f"  [SKIP] web already running on :{WEB_PORT}")
        else:
            pid = daemonize(["npm", "run", "dev"], "/tmp/nextjs.log")
            print(f"  [START] web :{WEB_PORT} (forked pid {pid}, log /tmp/nextjs.log)")

    if want_swift:
        pid = daemonize(["swift", "run"], "/tmp/secondself_swift.log",
                        cwd=os.path.join(ROOT, "fol-app"))
        print(f"  [START] SwiftUI app (forked pid {pid}, log /tmp/secondself_swift.log)")

    print("\nDone. Check with: python3 scripts/start_services.py --status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
