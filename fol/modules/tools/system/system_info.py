"""System information tools."""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult


class SystemInfo(AbstractTool):
    """Get system information."""

    name = "system_info"
    description = "Get information about the system (OS, CPU, memory)."
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What info to get: 'all', 'cpu', 'memory', 'disk', 'os'",
            },
        },
    }
    required_permissions = [Permission.LOW]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "all")
        try:
            info = {
                "os": f"{platform.system()} {platform.release()}",
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python": platform.python_version(),
            }

            if query in ("all", "memory"):
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    bytes_val = int(result.stdout.strip())
                    info["memory_gb"] = round(bytes_val / (1024**3), 1)

            if query in ("all", "disk"):
                result = subprocess.run(
                    ["df", "-h", "/"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) > 1:
                        parts = lines[1].split()
                        info["disk_total"] = parts[1] if len(parts) > 1 else "unknown"
                        info["disk_used"] = parts[2] if len(parts) > 2 else "unknown"
                        info["disk_avail"] = parts[3] if len(parts) > 3 else "unknown"

            if query in ("all", "cpu"):
                result = subprocess.run(
                    ["sysctl", "-n", "hw.ncpu"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    info["cpu_cores"] = int(result.stdout.strip())

            lines = [f"{k}: {v}" for k, v in info.items()]
            return ToolResult(success=True, output="\n".join(lines))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
