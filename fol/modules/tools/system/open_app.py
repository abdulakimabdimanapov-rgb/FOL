"""Open macOS applications."""

from __future__ import annotations

import subprocess
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult


class OpenApp(AbstractTool):
    """Open an application by name."""

    name = "open_app"
    description = "Open a macOS application by name (e.g. Safari, Terminal, Finder)."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Application name to open",
            },
        },
        "required": ["name"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        app_name = params.get("name", "").strip()
        if not app_name:
            return ToolResult(success=False, error="No application name provided.")

        try:
            subprocess.run(["open", "-a", app_name], check=True, timeout=10)
            return ToolResult(success=True, output=f"Opened {app_name}.")
        except subprocess.CalledProcessError:
            return ToolResult(success=False, error=f"Unable to open '{app_name}'. Check the app name.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
