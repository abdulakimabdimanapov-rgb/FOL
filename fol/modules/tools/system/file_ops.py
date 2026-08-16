"""File operations — search, read, write, list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult


class SearchFiles(AbstractTool):
    """Search for files by name pattern."""

    name = "search_files"
    description = "Search for files matching a pattern in a directory."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
            "directory": {"type": "string", "description": "Directory to search in (default: home)"},
        },
        "required": ["pattern"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        pattern = params.get("pattern", "")
        directory = params.get("directory", str(Path.home()))
        if not pattern:
            return ToolResult(success=False, error="No pattern provided.")
        try:
            matches = list(Path(directory).glob(pattern))
            if not matches:
                return ToolResult(success=True, output="No files found.")
            lines = [str(m) for m in matches[:50]]
            return ToolResult(success=True, output="\n".join(lines))
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class ReadFile(AbstractTool):
    """Read file contents."""

    name = "read_file"
    description = "Read the contents of a file."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
        },
        "required": ["path"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        if not path:
            return ToolResult(success=False, error="No path provided.")
        try:
            content = Path(path).read_text(encoding="utf-8")
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            return ToolResult(success=True, output=content)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class WriteFile(AbstractTool):
    """Write content to a file."""

    name = "write_file"
    description = "Write content to a file (creates or overwrites)."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "")
        content = params.get("content", "")
        if not path:
            return ToolResult(success=False, error="No path provided.")
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Written to {path} ({len(content)} bytes).")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
