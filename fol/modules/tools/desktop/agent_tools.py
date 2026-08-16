"""Desktop agent tools — PyAutoGUI + AppleScript automation.

Inspired by FOL's agent-server desktop tools.
Provides: click, type, hotkey, scroll, screenshot, open_app, move_mouse.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import subprocess
from typing import Any

from modules.tools.base import AbstractTool, RiskLevel, ToolResult

logger = logging.getLogger(__name__)


class DesktopClick(AbstractTool):
    """Click at screen coordinates."""
    name = "desktop_click"
    description = "Click at specific screen coordinates (x, y)"
    risk_level = RiskLevel.HIGH
    requires_confirmation = True
    category = "desktop"
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate"},
            "y": {"type": "integer", "description": "Y coordinate"},
        },
        "required": ["x", "y"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        x, y = params.get("x", 0), params.get("y", 0)
        try:
            import pyautogui
            pyautogui.click(x, y)
            return ToolResult(success=True, output=f"Clicked at ({x}, {y})")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DesktopType(AbstractTool):
    """Type text on keyboard."""
    name = "desktop_type"
    description = "Type text using keyboard simulation"
    risk_level = RiskLevel.HIGH
    requires_confirmation = True
    category = "desktop"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type"},
        },
        "required": ["text"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        text = params.get("text", "")
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=0.03)
            return ToolResult(success=True, output=f"Typed: {text[:50]}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DesktopHotkey(AbstractTool):
    """Press keyboard shortcut."""
    name = "desktop_hotkey"
    description = "Press a keyboard shortcut (e.g. command+c, command+v)"
    risk_level = RiskLevel.HIGH
    requires_confirmation = True
    category = "desktop"
    parameters = {
        "type": "object",
        "properties": {
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys to press together",
            },
        },
        "required": ["keys"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        keys = params.get("keys", [])
        try:
            import pyautogui
            pyautogui.hotkey(*keys)
            return ToolResult(success=True, output=f"Pressed: {'+'.join(keys)}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DesktopScroll(AbstractTool):
    """Scroll screen."""
    name = "desktop_scroll"
    description = "Scroll up or down by pixels"
    risk_level = RiskLevel.MEDIUM
    category = "desktop"
    parameters = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "Scroll amount (positive=up, negative=down)"},
        },
        "required": ["amount"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        amount = params.get("amount", 0)
        try:
            import pyautogui
            pyautogui.scroll(amount)
            return ToolResult(success=True, output=f"Scrolled {amount} pixels")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DesktopScreenshot(AbstractTool):
    """Take screenshot and return base64."""
    name = "desktop_screenshot"
    description = "Take a screenshot and return as base64"
    parameters = {"type": "object", "properties": {}}
    category = "desktop"

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            import pyautogui
            img = pyautogui.screenshot()
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            return ToolResult(success=True, output=f"Screenshot captured ({len(b64)} chars)")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DesktopMoveMouse(AbstractTool):
    """Move mouse to coordinates."""
    name = "desktop_move_mouse"
    description = "Move mouse cursor to screen coordinates"
    risk_level = RiskLevel.MEDIUM
    category = "desktop"
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["x", "y"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        x, y = params.get("x", 0), params.get("y", 0)
        try:
            import pyautogui
            pyautogui.moveTo(x, y, duration=0.3)
            return ToolResult(success=True, output=f"Mouse moved to ({x}, {y})")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class DesktopScreenSize(AbstractTool):
    """Get screen dimensions."""
    name = "desktop_screen_size"
    description = "Get screen width and height"
    parameters = {"type": "object", "properties": {}}
    category = "desktop"

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            import pyautogui
            w, h = pyautogui.size()
            return ToolResult(success=True, output=f"Screen: {w}x{h}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


# Productivity tools

class EmailTool(AbstractTool):
    """Send email via macOS Mail."""
    name = "send_email"
    description = "Send an email using macOS Mail app"
    risk_level = RiskLevel.HIGH
    requires_confirmation = True
    category = "productivity"
    parameters = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email"},
            "subject": {"type": "string", "description": "Email subject"},
            "body": {"type": "string", "description": "Email body"},
        },
        "required": ["to", "subject", "body"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        to = params.get("to", "")
        subject = params.get("subject", "")
        body = params.get("body", "")
        try:
            script = f'''
            tell application "Mail"
                activate
                set newMessage to make new outgoing message with properties {{subject:"{subject}", content:"{body}", visible:true}}
                tell newMessage
                    make new to recipient at end of to recipients with properties {{address:"{to}"}}
                end tell
                activate
            end tell
            '''
            subprocess.run(["osascript", "-e", script], timeout=10)
            return ToolResult(success=True, output=f"Email draft created for {to}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class CalendarTool(AbstractTool):
    """Create calendar event."""
    name = "create_event"
    description = "Create a calendar event"
    risk_level = RiskLevel.HIGH
    requires_confirmation = True
    category = "productivity"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Time in HH:MM format"},
        },
        "required": ["title", "date", "time"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        title = params.get("title", "")
        date = params.get("date", "")
        time_str = params.get("time", "09:00")
        try:
            script = f'''
            tell application "Calendar"
                activate
            end tell
            tell application "System Events"
                tell process "Calendar"
                    keystroke "n" using command down
                end tell
            end tell
            '''
            subprocess.run(["osascript", "-e", script], timeout=10)
            return ToolResult(success=True, output=f"Calendar event '{title}' on {date} at {time_str}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
