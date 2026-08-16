"""
Dashboard — System metrics collector.

Collects CPU, RAM, disk, network, and process metrics using macOS
built-in commands (sysctl, vm_stat, df, top, ps) to avoid external
dependencies like psutil.

Phase 7 additions:
  - Deterministic HTTP health checks for every service (never fake healthy).
  - Ollama status (:11434 /api/tags).
  - LLM chain / fallback status via orchestrator /api/runtime.
  - Memory status (~/.secondself files + Obsidian).
  - Service uptime.
  - Automatic DEGRADED/DOWN state detection.

All functions are synchronous and designed to be called via
asyncio.to_thread() from async endpoints.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

# Cache for expensive metrics
_cache: dict[str, Any] = {"time": 0.0, "data": {}}
_CACHE_TTL = 5.0  # seconds (matches WebSocket push interval)

# Dashboard process start time — for dashboard uptime
_DASHBOARD_START = time.time()

# ---------------------------------------------------------------------------
# Service registry — every service with its health endpoint
# ---------------------------------------------------------------------------
# name → {port, health_path, critical}
# critical=True  → if DOWN, the whole system is DOWN (cannot operate)
# critical=False → if DOWN, the system is DEGRADED but still usable
SERVICES: dict[str, dict[str, Any]] = {
    "orchestrator": {"port": 8420, "health": "/health", "critical": True},
    "agent_server": {"port": 8421, "health": "/health", "critical": True},
    "bridge": {"port": 8422, "health": "/health", "critical": False},
    "dashboard": {"port": 8423, "health": "/health", "critical": False},
    "fol": {"port": 8754, "health": "/health", "critical": True},
    "nextjs": {"port": 3000, "health": None, "critical": False},
    "fastapi": {"port": 8000, "health": "/health", "critical": False},
    "ollama": {"port": 11434, "health": "/api/tags", "critical": False},
}


def _run(cmd: list[str]) -> str:
    """Run a shell command and return stdout, or empty string on failure."""
    try:
        return subprocess.check_output(cmd, timeout=5, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _parse_int(s: str) -> int:
    """Parse a string to int, returning 0 on failure."""
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0


def _parse_float(s: str) -> float:
    """Parse a string to float, returning 0.0 on failure."""
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# HTTP helpers (deterministic health checks)
# ---------------------------------------------------------------------------

def http_get_json(url: str, timeout: float = 3.0) -> tuple[int, dict | None, str]:
    """GET a URL and parse JSON. Returns (status_code, json_or_None, error)."""
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(body), ""
            except (ValueError, TypeError):
                return resp.status, None, "invalid-json"
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace")), ""
        except Exception:
            return e.code, None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return 0, None, f"unreachable: {e.reason}"
    except Exception as e:
        return 0, None, str(e)


def check_port(port: int) -> bool:
    """Check if a local TCP port is listening."""
    try:
        sock = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        return result == 0
    except Exception:
        return False


def check_service_health(name: str) -> dict[str, Any]:
    """Deterministic health check for ONE service.

    Returns:
        {
          "name", "port", "critical",
          "status": "ok" | "degraded" | "down",   # never faked
          "detail": human-readable reason,
          "http": int | None,                     # last HTTP status
          "latency_ms": int | None,
        }

    Rules:
      - port not listening            → "down"
      - port up, no health endpoint   → "ok" (port is the signal)
      - port up, /health returns 200  → "ok"
      - port up, /health 5xx/error    → "degraded"
      - orchestrator: additionally DEGRADED when agent-server is unreachable
    """
    cfg = SERVICES.get(name)
    if not cfg:
        return {"name": name, "status": "down", "detail": "unknown service"}

    port = cfg["port"]
    health_path = cfg.get("health")
    critical = cfg.get("critical", False)

    if not check_port(port):
        return {
            "name": name, "port": port, "critical": critical,
            "status": "down", "detail": "port not listening", "http": None, "latency_ms": None,
        }

    if not health_path:
        return {
            "name": name, "port": port, "critical": critical,
            "status": "ok", "detail": "listening (no /health)", "http": None, "latency_ms": None,
        }

    start = time.time()
    code, data, err = http_get_json(f"http://127.0.0.1:{port}{health_path}", timeout=3.0)
    latency_ms = int((time.time() - start) * 1000)

    if code == 200:
        detail = "healthy"
        status = "ok"
        # Orchestrator is DEGRADED when its own /health reports agent-server down.
        if name == "orchestrator":
            agent = (data or {}).get("agent_server") or {}
            if isinstance(agent, dict) and agent.get("status") not in (None, "ok"):
                status = "degraded"
                detail = "orchestrator up, agent-server unhealthy"
        # FOL API /health uses "healthy" (v2) vs "starting"
        if name == "fol":
            s = (data or {}).get("status")
            if s == "starting":
                status = "degraded"
                detail = "FOL starting (not yet initialized)"
        return {
            "name": name, "port": port, "critical": critical,
            "status": status, "detail": detail, "http": code, "latency_ms": latency_ms,
        }

    return {
        "name": name, "port": port, "critical": critical,
        "status": "degraded", "detail": f"/health HTTP {code}: {err}" if err else f"/health HTTP {code}",
        "http": code, "latency_ms": latency_ms,
    }


def compute_system_state(services: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Automatic degraded-state detection across all services.

    Returns:
        {
          "state": "ok" | "degraded" | "down",
          "down_services": [...], "degraded_services": [...],
          "critical_down": bool,
        }

    - Any critical service DOWN  → "down"
    - Any service DOWN/DEGRADED  → "degraded"
    - Otherwise                  → "ok"
    """
    down = [n for n, s in services.items() if s.get("status") == "down"]
    degraded = [n for n, s in services.items() if s.get("status") == "degraded"]
    critical_down = [
        n for n in down
        if SERVICES.get(n, {}).get("critical")
    ]
    if critical_down:
        state = "down"
    elif down or degraded:
        state = "degraded"
    else:
        state = "ok"
    return {
        "state": state,
        "down_services": down,
        "degraded_services": degraded,
        "critical_down": critical_down,
    }


# ---------------------------------------------------------------------------
# LLM status (via orchestrator /api/runtime — no secrets)
# ---------------------------------------------------------------------------

def get_llm_status() -> dict[str, Any]:
    """Fetch LLM chain / fallback status from the orchestrator.

    Returns a dict that always describes the real state — never faked:
      - orchestrator unreachable → {"status": "unknown", "reason": "orchestrator down"}
    """
    code, data, err = http_get_json("http://127.0.0.1:8420/api/runtime", timeout=3.0)
    if code != 200 or not data:
        return {"status": "unknown", "reason": err or f"HTTP {code}"}
    llm = data.get("llm") or {}
    return {
        "status": llm.get("status", "unknown"),
        "model_chain": llm.get("model_chain", []),
        "providers": llm.get("providers", []),
        "fallback_log": llm.get("fallback_log", []),
        "last_fallback_error": llm.get("last_fallback_error", ""),
        "tavily_configured": llm.get("tavily_configured", False),
    }


# ---------------------------------------------------------------------------
# Ollama status
# ---------------------------------------------------------------------------

def get_ollama_status() -> dict[str, Any]:
    """Check Ollama (:11434) — /api/tags lists installed models."""
    code, data, err = http_get_json("http://127.0.0.1:11434/api/tags", timeout=2.0)
    if code != 200 or not data:
        return {"status": "down", "reason": err or f"HTTP {code}", "models": []}
    models = [m.get("name", "") for m in (data.get("models") or [])]
    return {
        "status": "ok" if models else "degraded",
        "models": models,
        "count": len(models),
        "reason": "" if models else "running but no models installed",
    }


# ---------------------------------------------------------------------------
# Memory status
# ---------------------------------------------------------------------------

def get_memory_status() -> dict[str, Any]:
    """Memory status: ~/.secondself files + Obsidian connectivity flag.

    Obsidian connectivity is reported by the orchestrator's /api/runtime
    (it runs in the user session where the vault lives).
    """
    mem_dir = pathlib.Path.home() / ".secondself"
    files: dict[str, Any] = {}
    for name in ("identity", "preferences", "episodic"):
        p = mem_dir / f"{name}.md"
        try:
            files[name] = {
                "exists": p.exists(),
                "size": p.stat().st_size if p.exists() else 0,
            }
        except OSError:
            files[name] = {"exists": False, "size": 0}

    obsidian_connected = None
    code, data, err = http_get_json("http://127.0.0.1:8420/api/runtime", timeout=3.0)
    if code == 200 and data:
        obsidian_connected = bool((data.get("memory") or {}).get("obsidian_connected"))

    return {
        "dir": str(mem_dir),
        "files": files,
        "obsidian_connected": obsidian_connected,
    }


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------

def get_cpu_usage() -> dict[str, Any]:
    """Get CPU usage metrics via sysctl and top."""
    # Number of cores
    cores = _parse_int(_run(["sysctl", "-n", "hw.ncpu"]).strip())

    # Load average (1, 5, 15 min)
    load_raw = _run(["sysctl", "-n", "vm.loadavg"]).strip()
    load_match = re.search(r"\{([^}]+)\}", load_raw)
    load_avg = [0.0, 0.0, 0.0]
    if load_match:
        parts = load_match.group(1).split()
        load_avg = [_parse_float(p) for p in parts[:3]]

    # CPU usage percent from top (brief sample)
    top_out = _run(["top", "-l", "1", "-n", "0", "-stats", "cpu"])
    cpu_user = 0.0
    cpu_sys = 0.0
    cpu_idle = 0.0
    # Parse "CPU: user 12.34, sys 5.67, idle 81.99" from top output
    for line in top_out.splitlines():
        if line.startswith("CPU:"):
            m = re.search(r"user\s+([\d.]+)", line)
            if m: cpu_user = _parse_float(m.group(1))
            m = re.search(r"sys\s+([\d.]+)", line)
            if m: cpu_sys = _parse_float(m.group(1))
            m = re.search(r"idle\s+([\d.]+)", line)
            if m: cpu_idle = _parse_float(m.group(1))
            break

    return {
        "cores": cores,
        "load_avg_1min": round(load_avg[0], 2),
        "load_avg_5min": round(load_avg[1], 2),
        "load_avg_15min": round(load_avg[2], 2),
        "load_percent": round((load_avg[0] / cores * 100) if cores else 0, 1),
        "user_percent": round(cpu_user, 1),
        "sys_percent": round(cpu_sys, 1),
        "idle_percent": round(cpu_idle, 1),
    }


# ---------------------------------------------------------------------------
# Memory (RAM)
# ---------------------------------------------------------------------------

def get_memory_usage() -> dict[str, Any]:
    """Get RAM usage via vm_stat and sysctl."""
    # Total physical memory in bytes → GB
    total_bytes = _parse_int(_run(["sysctl", "-n", "hw.memsize"]).strip())
    total_gb = round(total_bytes / (1024**3), 1)

    # vm_stat for page counts
    vm_out = _run(["vm_stat"])

    page_size = 16384  # Will be overwritten by vm_stat parsing
    for line in vm_out.splitlines():
        m = re.search(r"page size of (\d+) bytes", line)
        if m:
            page_size = _parse_int(m.group(1))
            break
    else:
        # vm_stat didn't report page size; try sysctl as fallback
        hw_pagesize = _run(["sysctl", "-n", "hw.pagesize"]).strip()
        if hw_pagesize:
            page_size = _parse_int(hw_pagesize)

    pages_active = 0
    pages_wired = 0
    pages_compressed = 0
    pages_free = 0
    pages_speculative = 0
    pages_purgeable = 0

    for line in vm_out.splitlines():
        m = re.match(r"Pages active:\s+(\d+)", line)
        if m: pages_active = _parse_int(m.group(1))
        m = re.match(r"Pages wired down:\s+(\d+)", line)
        if m: pages_wired = _parse_int(m.group(1))
        m = re.match(r"Pages (?:stored in )?compressor:\s+(\d+)", line)
        if m: pages_compressed = _parse_int(m.group(1))
        m = re.match(r"Pages free:\s+(\d+)", line)
        if m: pages_free = _parse_int(m.group(1))
        m = re.match(r"Pages speculative:\s+(\d+)", line)
        if m: pages_speculative = _parse_int(m.group(1))
        m = re.match(r"Pages purgeable:\s+(\d+)", line)
        if m: pages_purgeable = _parse_int(m.group(1))

    used_bytes = (pages_active + pages_wired + pages_compressed) * page_size
    used_gb = round(used_bytes / (1024**3), 1)
    free_bytes = (pages_free + pages_speculative + pages_purgeable) * page_size
    free_gb = round(free_bytes / (1024**3), 1)
    used_percent = round((used_bytes / total_bytes * 100) if total_bytes else 0, 1)

    return {
        "total_gb": total_gb,
        "used_gb": used_gb,
        "free_gb": free_gb,
        "used_percent": used_percent,
        "free_percent": round(100 - used_percent, 1),
        "page_size": page_size,
        "pages_active": pages_active,
        "pages_wired": pages_wired,
        "pages_compressed": pages_compressed,
    }


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------

def get_disk_usage() -> dict[str, Any]:
    """Get disk usage via df."""
    df_out = _run(["df", "-k", "/"])
    lines = df_out.splitlines()
    if len(lines) < 2:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "used_percent": 0}

    parts = lines[1].split()
    if len(parts) < 4:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "used_percent": 0}

    total_kb = _parse_int(parts[1])
    used_kb = _parse_int(parts[2])
    free_kb = _parse_int(parts[3])
    used_percent_raw = parts[4] if len(parts) > 4 else "0%"

    return {
        "total_gb": round(total_kb / (1024**2), 1),
        "used_gb": round(used_kb / (1024**2), 1),
        "free_gb": round(free_kb / (1024**2), 1),
        "used_percent": _parse_float(used_percent_raw.replace("%", "")),
    }


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

def _detect_primary_interface() -> str:
    """Detect the primary network interface via route table."""
    route_out = _run(["route", "get", "default"])
    for line in route_out.splitlines():
        line = line.strip()
        if line.startswith("interface:"):
            iface = line.split(":", 1)[1].strip()
            if iface:
                return iface
    # Fallback: try common interfaces
    for iface in ["en0", "en1", "en2", "ap1"]:
        if _run(["ifconfig", iface]).strip():
            return iface
    return "en0"


def get_network_stats() -> dict[str, Any]:
    """Get basic network stats via netstat."""
    iface = _detect_primary_interface()
    net_out = _run(["netstat", "-ib", "-I", iface])
    lines = net_out.splitlines()

    packets_in = 0
    packets_out = 0
    bytes_in = 0
    bytes_out = 0

    for line in lines[1:]:  # Skip header
        parts = line.split()
        if len(parts) >= 8:
            packets_in += _parse_int(parts[4])
            packets_out += _parse_int(parts[5])
            bytes_in += _parse_int(parts[6])
            bytes_out += _parse_int(parts[7])

    def _fmt_bytes(b: int) -> str:
        if b > 10**9:
            return f"{b / 10**9:.1f} GB"
        elif b > 10**6:
            return f"{b / 10**6:.1f} MB"
        elif b > 10**3:
            return f"{b / 10**3:.1f} KB"
        return f"{b} B"

    return {
        "packets_in": packets_in,
        "packets_out": packets_out,
        "bytes_in": _fmt_bytes(bytes_in),
        "bytes_out": _fmt_bytes(bytes_out),
        "bytes_in_raw": bytes_in,
        "bytes_out_raw": bytes_out,
    }


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

def get_system_info() -> dict[str, Any]:
    """Get basic system information."""
    os_ver = _run(["sw_vers", "-productVersion"]).strip()
    build = _run(["sw_vers", "-buildVersion"]).strip()
    uptime_raw = _run(["sysctl", "-n", "kern.boottime"]).strip()

    # Parse boot time
    boot_ts = 0
    m = re.search(r"sec = (\d+)", uptime_raw)
    if m:
        boot_ts = _parse_int(m.group(1))

    now = time.time()
    uptime_seconds = now - boot_ts if boot_ts else 0
    uptime_days = uptime_seconds / 86400

    hostname = _run(["scutil", "--get", "ComputerName"]).strip()

    return {
        "os": f"macOS {os_ver}",
        "build": build,
        "hostname": hostname,
        "uptime_seconds": int(uptime_seconds),
        "uptime_days": round(uptime_days, 1),
        "uptime_str": _format_uptime(uptime_seconds),
        "time": datetime.now(timezone.utc).isoformat(),
    }


def _format_uptime(seconds: float) -> str:
    """Format uptime seconds into a human-readable string."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    elif hours > 0:
        return f"{hours}h {mins}m"
    else:
        return f"{mins}m"


def get_dashboard_uptime() -> dict[str, Any]:
    """Dashboard process uptime."""
    seconds = time.time() - _DASHBOARD_START
    return {
        "uptime_seconds": int(seconds),
        "uptime_str": _format_uptime(seconds),
    }


# ---------------------------------------------------------------------------
# Process list (top processes by CPU)
# ---------------------------------------------------------------------------

def get_top_processes(count: int = 5) -> list[dict[str, Any]]:
    """Get top N processes by CPU usage via ps."""
    ps_out = _run([
        "ps", "axo", "pid,pcpu,pmem,comm",
        "--sort=-pcpu",
    ])
    lines = ps_out.splitlines()

    processes = []
    for line in lines[1:count+1]:  # Skip header
        parts = line.strip().split(None, 3)
        if len(parts) >= 4:
            processes.append({
                "pid": _parse_int(parts[0]),
                "cpu_percent": _parse_float(parts[1]),
                "mem_percent": _parse_float(parts[2]),
                "name": parts[3],
            })
    return processes


# ---------------------------------------------------------------------------
# Orchestrator status proxy
# ---------------------------------------------------------------------------

def get_orchestrator_status() -> dict[str, Any]:
    """Fetch current orchestrator status via HTTP."""
    try:
        req = urllib.request.Request("http://localhost:8420/status", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def get_orchestrator_health() -> dict[str, Any]:
    """Fetch orchestrator health info."""
    try:
        req = urllib.request.Request("http://localhost:8420/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def get_orchestrator_runtime() -> dict[str, Any]:
    """Fetch orchestrator /api/runtime (Phase 7)."""
    code, data, err = http_get_json("http://127.0.0.1:8420/api/runtime", timeout=3.0)
    if code != 200 or not data:
        return {"error": err or f"HTTP {code}"}
    return data


# ---------------------------------------------------------------------------
# Recent events from episodic memory
# ---------------------------------------------------------------------------

def get_recent_events(count: int = 10) -> list[dict[str, Any]]:
    """Read recent events from episodic.md."""
    episodic_path = pathlib.Path.home() / ".secondself" / "episodic.md"
    if not episodic_path.exists():
        return []

    events = []
    try:
        text = episodic_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Parse: - 2026-03-28 | category | summary
            parts = line.split(" | ", 2)
            if len(parts) >= 3:
                events.append({
                    "date": parts[0].lstrip("- "),
                    "category": parts[1],
                    "summary": parts[2],
                })
            elif len(parts) >= 2:
                events.append({
                    "date": parts[0].lstrip("- "),
                    "category": parts[1],
                    "summary": "",
                })
    except Exception:
        pass

    return events[-count:]


# ---------------------------------------------------------------------------
# Combined collector (with caching)
# ---------------------------------------------------------------------------

def collect_all() -> dict[str, Any]:
    """Collect all metrics at once with caching."""
    now = time.time()
    if now - _cache["time"] < _CACHE_TTL:
        return _cache["data"]

    services = {name: check_service_health(name) for name in SERVICES}
    data = {
        "cpu": get_cpu_usage(),
        "memory": get_memory_usage(),
        "disk": get_disk_usage(),
        "network": get_network_stats(),
        "system": get_system_info(),
        "top_processes": get_top_processes(),
        "services": services,
        "system_state": compute_system_state(services),
        "llm": get_llm_status(),
        "ollama": get_ollama_status(),
        "memory_status": get_memory_status(),
        "dashboard_uptime": get_dashboard_uptime(),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    _cache["time"] = now
    _cache["data"] = data
    return data
