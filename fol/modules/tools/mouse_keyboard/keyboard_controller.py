"""Keyboard controller — type text, press keys, hotkeys."""

from __future__ import annotations

import asyncio
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult


class TypeText(AbstractTool):
    """Type text as if typed on keyboard."""

    name = "type_text"
    description = "Type a string of text character by character."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type"},
            "delay": {"type": "number", "description": "Delay between keystrokes in seconds (default 0.02)"},
        },
        "required": ["text"],
    }
    required_permissions = [Permission.HIGH]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        text = params.get("text", "")
        delay = params.get("delay", 0.02)
        if not text:
            return ToolResult(success=False, error="No text provided.")

        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e",
                f'tell application "System Events" to keystroke "{text}"',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return ToolResult(success=True, output=f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}")
            return ToolResult(success=False, error="Type failed.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class PressKey(AbstractTool):
    """Press a single key or key combination."""

    name = "press_key"
    description = "Press a key or key combination (e.g. 'return', 'tab', 'cmd+c')."
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key or combination (e.g. 'return', 'cmd+a', 'ctrl+alt+delete')"},
        },
        "required": ["key"],
    }
    required_permissions = [Permission.HIGH]

    # Map common names to AppleScript key codes
    KEY_MAP = {
        "return": "return",
        "enter": "return",
        "tab": "tab",
        "escape": "escape",
        "esc": "escape",
        "delete": "delete",
        "backspace": "delete",
        "space": "space",
        "up": "up arrow",
        "down": "down arrow",
        "left": "left arrow",
        "right": "right arrow",
        "home": "home",
        "end": "end",
        "pageup": "page up",
        "pagedown": "page down",
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        key = params.get("key", "").lower().strip()
        if not key:
            return ToolResult(success=False, error="No key provided.")

        try:
            # Handle combinations like "cmd+c"
            if "+" in key:
                parts = key.split("+")
                modifier_map = {
                    "cmd": "command", "command": "command",
                    "ctrl": "control", "control": "control",
                    "alt": "option", "option": "option",
                    "shift": "shift",
                }
                modifiers = []
                key_name = parts[-1]
                for p in parts[:-1]:
                    if p in modifier_map:
                        modifiers.append(modifier_map[p])

                if modifiers:
                    mod_str = " and ".join(f"{m} down" for m in modifiers)
                    key_display = self.KEY_MAP.get(key_name, key_name)
                    script = f'tell application "System Events" to keystroke "{key_display}" using {{{mod_str} down}}'
                else:
                    key_display = self.KEY_MAP.get(key_name, key_name)
                    script = f'tell application "System Events" to key code {self._get_key_code(key_display)}'
            else:
                key_display = self.KEY_MAP.get(key, key)
                script = f'tell application "System Events" to key code {self._get_key_code(key_display)}'

            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return ToolResult(success=True, output=f"Pressed: {key}")
            return ToolResult(success=False, error=f"Failed to press key: {key}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    def _get_key_code(self, key: str) -> int:
        """Get AppleScript key code for common keys."""
        codes = {
            "return": 36, "tab": 48, "escape": 53, "space": 49,
            "delete": 51, "up arrow": 126, "down arrow": 125,
            "left arrow": 123, "right arrow": 124,
            "home": 115, "end": 119, "page up": 116, "page down": 121,
            "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3,
            "g": 5, "h": 4, "i": 34, "j": 38, "k": 40, "l": 37,
            "m": 46, "n": 45, "o": 31, "p": 35, "q": 12, "r": 15,
            "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
            "y": 16, "z": 6, "0": 29, "1": 18, "2": 19, "3": 20,
            "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
        }
        return codes.get(key, 36)  # Default to return
