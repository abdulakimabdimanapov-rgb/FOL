"""Browser automation — navigate, search, get page content."""

from __future__ import annotations

import asyncio
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult


class BrowserNavigate(AbstractTool):
    """Open a URL in the default browser."""

    name = "browser_navigate"
    description = "Open a URL in the default web browser."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to open"},
        },
        "required": ["url"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        url = params.get("url", "")
        if not url:
            return ToolResult(success=False, error="No URL provided.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            proc = await asyncio.create_subprocess_exec(
                "open", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return ToolResult(success=True, output=f"Opened: {url}")
            return ToolResult(success=False, error="Failed to open URL.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class BrowserSearch(AbstractTool):
    """Search the web via default browser."""

    name = "browser_search"
    description = "Search the web using the default browser."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    }
    required_permissions = [Permission.MEDIUM]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        query = params.get("query", "")
        if not query:
            return ToolResult(success=False, error="No search query provided.")

        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "open", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                return ToolResult(success=True, output=f"Searching: {query}")
            return ToolResult(success=False, error="Search failed.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))


class GetPageContent(AbstractTool):
    """Extract text content from a URL using curl."""

    name = "get_page_content"
    description = "Fetch and extract text content from a web page."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "max_chars": {"type": "integer", "description": "Max characters to return (default 5000)"},
        },
        "required": ["url"],
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 15.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        url = params.get("url", "")
        max_chars = params.get("max_chars", 5000)
        if not url:
            return ToolResult(success=False, error="No URL provided.")

        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-sL", "--max-time", "10", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            html = stdout.decode(errors="ignore")

            # Simple HTML tag stripping
            import re
            text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()

            if len(text) > max_chars:
                text = text[:max_chars] + "..."

            return ToolResult(success=True, output=text or "No content extracted.")
        except asyncio.TimeoutError:
            return ToolResult(success=False, error="Request timed out.")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
