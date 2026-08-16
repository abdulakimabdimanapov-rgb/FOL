"""Clipboard tools — read/write system clipboard."""

from __future__ import annotations

import asyncio
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult


class ReadClipboard(AbstractTool):
    """Read the system clipboard."""

    name = "read_clipboard"
    description = "Read the current contents of the system clipboard."
    parameters = {"type": "object", "properties": {}}
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pbpaste",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text = stdout.decode(errors="ignore").strip()
            return ToolResult(success=True, output=text or "(clipboard is empty)")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class WriteClipboard(AbstractTool):
    """Write to the system clipboard."""

    name = "write_clipboard"
    description = "Write text to the system clipboard."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to copy to clipboard"},
        },
        "required": ["text"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        text = params.get("text", "")
        if not text:
            return ToolResult(success=False, error="No text provided.")
        try:
            proc = await asyncio.create_subprocess_exec(
                "pbcopy",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate(input=text.encode())
            return ToolResult(success=True, output=f"Copied {len(text)} chars to clipboard.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
