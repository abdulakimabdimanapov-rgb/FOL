"""Bookmarks tool — manage browser bookmarks."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from modules.tools.base import AbstractTool, ToolResult

logger = logging.getLogger(__name__)


class BookmarksTool(AbstractTool):
    """Manage browser bookmarks stored locally."""

    name = "bookmarks"
    description = "Manage bookmarks: add, remove, list, search."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "remove", "list", "search"],
                "description": "Bookmark action",
            },
            "url": {"type": "string", "description": "Bookmark URL (for add)"},
            "title": {"type": "string", "description": "Bookmark title (for add)"},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for the bookmark",
            },
            "query": {"type": "string", "description": "Search query (for search)"},
        },
        "required": ["action"],
    }

    def __init__(self, bookmarks_file: str = "~/.fol/bookmarks.json") -> None:
        self._path = Path(bookmarks_file).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._bookmarks: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        """Load bookmarks from disk."""
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                return []
        return []

    def _save(self) -> None:
        """Save bookmarks to disk."""
        self._path.write_text(json.dumps(self._bookmarks, indent=2, ensure_ascii=False))

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute a bookmarks action."""
        action = params.get("action", "")

        if action == "add":
            return self._add(params)
        elif action == "remove":
            return self._remove(params)
        elif action == "list":
            return self._list()
        elif action == "search":
            return self._search(params)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    def _add(self, params: dict[str, Any]) -> ToolResult:
        """Add a bookmark."""
        url = params.get("url", "")
        title = params.get("title", url)
        tags = params.get("tags", [])

        if not url:
            return ToolResult(success=False, error="URL is required")

        bookmark = {"url": url, "title": title, "tags": tags}
        self._bookmarks.append(bookmark)
        self._save()
        return ToolResult(success=True, output=f"Bookmark added: {title}")

    def _remove(self, params: dict[str, Any]) -> ToolResult:
        """Remove a bookmark by URL."""
        url = params.get("url", "")
        if not url:
            return ToolResult(success=False, error="URL is required")

        before = len(self._bookmarks)
        self._bookmarks = [b for b in self._bookmarks if b.get("url") != url]
        if len(self._bookmarks) < before:
            self._save()
            return ToolResult(success=True, output=f"Bookmark removed: {url}")
        return ToolResult(success=False, error=f"Bookmark not found: {url}")

    def _list(self) -> ToolResult:
        """List all bookmarks."""
        if not self._bookmarks:
            return ToolResult(success=True, output="No bookmarks saved")

        lines = []
        for b in self._bookmarks:
            tags = ", ".join(b.get("tags", []))
            tag_str = f" [{tags}]" if tags else ""
            lines.append(f"- {b['title']}: {b['url']}{tag_str}")

        return ToolResult(success=True, output="\n".join(lines))

    def _search(self, params: dict[str, Any]) -> ToolResult:
        """Search bookmarks by query."""
        query = params.get("query", "").lower()
        if not query:
            return self._list()

        matches = [
            b for b in self._bookmarks
            if query in b.get("title", "").lower()
            or query in b.get("url", "").lower()
            or any(query in t.lower() for t in b.get("tags", []))
        ]

        if not matches:
            return ToolResult(success=True, output=f"No bookmarks matching '{query}'")

        lines = [f"- {b['title']}: {b['url']}" for b in matches]
        return ToolResult(success=True, output="\n".join(lines))
