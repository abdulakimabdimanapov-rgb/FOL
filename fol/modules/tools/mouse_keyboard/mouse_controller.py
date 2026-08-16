"""Mouse controller — move, click, drag via CoreGraphics."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult

logger = logging.getLogger(__name__)

try:
    import subprocess
    HAS_APPLESCRIPT = True
except ImportError:
    HAS_APPLESCRIPT = False


class MoveMouse(AbstractTool):
    """Move the mouse cursor to coordinates."""

    name = "move_mouse"
    description = "Move the mouse cursor to specific screen coordinates."
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate"},
            "y": {"type": "integer", "description": "Y coordinate"},
        },
        "required": ["x", "y"],
    }
    required_permissions = [Permission.HIGH]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        x = params.get("x", 0)
        y = params.get("y", 0)
        try:
            script = f'''
            tell application "System Events"
                set position of mouse event to {{{x}, {y}}}
            end tell
            '''
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                return ToolResult(success=True, output=f"Mouse moved to ({x}, {y}).")
            # Fallback: use cliclick if available
            return await self._move_cliclick(x, y)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    async def _move_cliclick(self, x: int, y: int) -> ToolResult:
        """Fallback: use cliclick CLI tool."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "cliclick", f"m:{x},{y}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return ToolResult(success=True, output=f"Mouse moved to ({x}, {y}).")
            return ToolResult(success=False, error="Neither AppleScript nor cliclick available for mouse control.")
        except FileNotFoundError:
            return ToolResult(success=False, error="Install cliclick: brew install cliclick")


class Click(AbstractTool):
    """Click at current or specified position."""

    name = "click"
    description = "Click the mouse at current position or at (x, y)."
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate (optional)"},
            "y": {"type": "integer", "description": "Y coordinate (optional)"},
            "button": {"type": "string", "description": "Button: left, right, double", "default": "left"},
        },
    }
    required_permissions = [Permission.HIGH]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        x = params.get("x")
        y = params.get("y")
        button = params.get("button", "left")

        try:
            if button == "double":
                cmd = "cliclick dc:." if x is None else f"cliclick dc:{x},{y}"
            elif button == "right":
                cmd = "cliclick rc:." if x is None else f"cliclick rc:{x},{y}"
            else:
                cmd = "cliclick c:." if x is None else f"cliclick c:{x},{y}"

            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                pos = f"({x}, {y})" if x is not None else "current position"
                return ToolResult(success=True, output=f"{button} click at {pos}.")
            return ToolResult(success=False, error="Click failed. Install cliclick: brew install cliclick")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class Drag(AbstractTool):
    """Drag from one position to another."""

    name = "drag"
    description = "Drag from (x1,y1) to (x2,y2)."
    parameters = {
        "type": "object",
        "properties": {
            "x1": {"type": "integer", "description": "Start X"},
            "y1": {"type": "integer", "description": "Start Y"},
            "x2": {"type": "integer", "description": "End X"},
            "y2": {"type": "integer", "description": "End Y"},
        },
        "required": ["x1", "y1", "x2", "y2"],
    }
    required_permissions = [Permission.HIGH]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        x1, y1 = params.get("x1", 0), params.get("y1", 0)
        x2, y2 = params.get("x2", 0), params.get("y2", 0)
        try:
            proc = await asyncio.create_subprocess_shell(
                f"cliclick dd:{x1},{y1} du:{x2},{y2}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return ToolResult(success=True, output=f"Dragged from ({x1},{y1}) to ({x2},{y2}).")
            return ToolResult(success=False, error="Drag failed. Install cliclick.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
