"""Web scraper tool — extract content from web pages."""

from __future__ import annotations

import logging
from typing import Any

from modules.tools.base import AbstractTool, ToolResult

logger = logging.getLogger(__name__)


class WebScraper(AbstractTool):
    """Extract text content from web pages."""

    name = "web_scraper"
    description = "Scrape text content from a URL. Returns the main text content of the page."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to scrape"},
            "selector": {
                "type": "string",
                "description": "CSS selector to extract specific content (optional)",
            },
            "max_length": {
                "type": "integer",
                "description": "Maximum characters to return",
                "default": 5000,
            },
        },
        "required": ["url"],
    }

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Scrape content from a URL."""
        url = params.get("url", "")
        max_length = params.get("max_length", 5000)

        if not url:
            return ToolResult(success=False, error="URL is required")

        try:
            import urllib.request
            import re

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "FOL/0.1.0 (Personal AI Assistant)"},
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                html = response.read().decode("utf-8", errors="replace")

            # Simple HTML to text extraction
            text = self._html_to_text(html)
            if len(text) > max_length:
                text = text[:max_length] + "..."

            return ToolResult(
                success=True,
                output=text,
                metadata={"url": url, "length": len(text)},
            )

        except Exception as exc:
            logger.error("Web scraping failed", url=url, error=str(exc))
            return ToolResult(success=False, error=f"Scraping failed: {exc}")

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text (simple extraction)."""
        import re

        # Remove script and style elements
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Decode common HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")

        return text
