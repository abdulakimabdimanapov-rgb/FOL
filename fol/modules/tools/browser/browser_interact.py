"""Browser interaction — full automation with Playwright.

Provides tools for navigating websites, clicking elements, filling forms,
scrolling, taking screenshots, and extracting content. FOL can now
interact with any website when given a command.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.tools.base import AbstractTool, Permission, ToolResult

logger = logging.getLogger(__name__)

# Shared browser instance (lazy singleton)
_browser = None
_page = None


async def _get_page():
    """Get or create the shared Playwright page."""
    global _browser, _page  # noqa: PLW0603

    if _page is not None and not _page.is_closed():
        return _page

    try:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        _browser = await pw.chromium.launch(headless=True)
        context = await _browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        _page = await context.new_page()
        return _page
    except Exception as exc:
        logger.error("Failed to launch browser: %s", exc)
        return None


class BrowserOpen(AbstractTool):
    """Open a URL in the headless browser."""

    name = "browser_open"
    description = "Open a website URL in the headless browser. Use this to navigate to any website."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to open (e.g. https://google.com)"},
        },
        "required": ["url"],
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 30.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        url = params.get("url", "")
        if not url:
            return ToolResult(success=False, error="No URL provided.")
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        page = await _get_page()
        if page is None:
            return ToolResult(success=False, error="Could not launch browser.")

        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            title = await page.title()
            status = response.status if response else "unknown"
            return ToolResult(
                success=True,
                output=f"Opened: {url}\nTitle: {title}\nStatus: {status}",
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"Failed to open {url}: {exc}")


class BrowserClick(AbstractTool):
    """Click an element on the page by CSS selector or text."""

    name = "browser_click"
    description = "Click an element on the current page. Use CSS selector or visible text."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector or text to click (e.g. 'button.submit', 'Sign In', '#login-btn')",
            },
        },
        "required": ["selector"],
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 15.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        selector = params.get("selector", "")
        if not selector:
            return ToolResult(success=False, error="No selector provided.")

        page = await _get_page()
        if page is None:
            return ToolResult(success=False, error="Browser not running. Open a URL first.")

        try:
            # Try CSS selector first, with scroll into view
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.scroll_into_view_if_needed()
                    await el.click(timeout=5000)
                    return ToolResult(success=True, output=f"Clicked: {selector}")
            except Exception:
                pass

            # Try text selector
            try:
                await page.click(f"text={selector}", timeout=5000)
                return ToolResult(success=True, output=f"Clicked text: {selector}")
            except Exception:
                pass

            # Try role selector (button, link, etc.)
            try:
                await page.click(f"role=button[name='{selector}']", timeout=3000)
                return ToolResult(success=True, output=f"Clicked button: {selector}")
            except Exception:
                pass

            return ToolResult(success=False, error=f"Could not find element: {selector}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Click failed: {exc}")


class BrowserType(AbstractTool):
    """Type text into an input field."""

    name = "browser_type"
    description = "Type text into an input field or text area on the current page."
    parameters = {
        "type": "object",
        "properties": {
            "selector": {
                "type": "string",
                "description": "CSS selector of the input field (e.g. 'input[name=q]', '#search')",
            },
            "text": {"type": "string", "description": "Text to type"},
            "clear": {
                "type": "boolean",
                "description": "Clear the field first (default true)",
                "default": True,
            },
            "press_enter": {
                "type": "boolean",
                "description": "Press Enter after typing (default false)",
                "default": False,
            },
        },
        "required": ["selector", "text"],
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 10.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        selector = params.get("selector", "")
        text = params.get("text", "")
        clear = params.get("clear", True)
        press_enter = params.get("press_enter", False)

        if not selector or not text:
            return ToolResult(success=False, error="Selector and text are required.")

        page = await _get_page()
        if page is None:
            return ToolResult(success=False, error="Browser not running.")

        try:
            await page.click(selector, timeout=5000)
            if clear:
                await page.fill(selector, "")
            await page.type(selector, text, delay=30)
            if press_enter:
                await page.press(selector, "Enter")
            return ToolResult(success=True, output=f"Typed '{text}' into {selector}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Type failed: {exc}")


class BrowserScroll(AbstractTool):
    """Scroll the page up or down."""

    name = "browser_scroll"
    description = "Scroll the current page up or down, or to a specific element."
    parameters = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down", "top", "bottom"],
                "description": "Scroll direction",
            },
            "amount": {
                "type": "integer",
                "description": "Pixels to scroll (default 500)",
                "default": 500,
            },
        },
        "required": ["direction"],
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 10.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        direction = params.get("direction", "down")
        amount = params.get("amount", 500)

        page = await _get_page()
        if page is None:
            return ToolResult(success=False, error="Browser not running.")

        try:
            if direction == "down":
                await page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                await page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "top":
                await page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            return ToolResult(success=True, output=f"Scrolled {direction}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Scroll failed: {exc}")


class BrowserScreenshot(AbstractTool):
    """Take a screenshot of the current page."""

    name = "browser_screenshot"
    description = "Take a screenshot of the current page and save it."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to save screenshot (default: /tmp/fol_screenshot.png)",
            },
        },
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 10.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        path = params.get("path", "/tmp/fol_screenshot.png")

        page = await _get_page()
        if page is None:
            return ToolResult(success=False, error="Browser not running.")

        try:
            await page.screenshot(path=path, full_page=False)
            return ToolResult(success=True, output=f"Screenshot saved: {path}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Screenshot failed: {exc}")


class BrowserExtract(AbstractTool):
    """Extract text or links from the current page."""

    name = "browser_extract"
    description = "Extract text content, links, or specific elements from the current page."
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["text", "links", "html", "elements"],
                "description": "What to extract (default: text)",
                "default": "text",
            },
            "selector": {
                "type": "string",
                "description": "CSS selector to extract specific elements (for 'elements' mode)",
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return (default 5000)",
                "default": 5000,
            },
        },
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 10.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        mode = params.get("mode", "text")
        selector = params.get("selector", "")
        max_chars = params.get("max_chars", 5000)

        page = await _get_page()
        if page is None:
            return ToolResult(success=False, error="Browser not running.")

        try:
            if mode == "text":
                text = await page.inner_text("body")
                if len(text) > max_chars:
                    text = text[:max_chars] + "..."
                return ToolResult(success=True, output=text or "No text found.")

            elif mode == "links":
                links = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                        text: a.innerText.trim(),
                        href: a.href
                    })).filter(l => l.text && l.href).slice(0, 50)
                """)
                if not links:
                    return ToolResult(success=True, output="No links found.")
                lines = [f"- {l['text']}: {l['href']}" for l in links]
                return ToolResult(success=True, output="\n".join(lines))

            elif mode == "html":
                html = await page.content()
                if len(html) > max_chars:
                    html = html[:max_chars] + "..."
                return ToolResult(success=True, output=html)

            elif mode == "elements" and selector:
                elements = await page.evaluate(f"""
                    () => Array.from(document.querySelectorAll('{selector}')).map(el => ({{
                        tag: el.tagName,
                        text: el.innerText?.trim() || '',
                        id: el.id || '',
                        class: el.className || ''
                    }})).slice(0, 30)
                """)
                if not elements:
                    return ToolResult(success=True, output=f"No elements found for: {selector}")
                lines = []
                for el in elements:
                    text = el['text'][:80] if el['text'] else '(empty)'
                    lines.append(f"<{el['tag']} id='{el['id']}'> {text}")
                return ToolResult(success=True, output="\n".join(lines))

            return ToolResult(success=False, error=f"Unknown mode: {mode}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Extract failed: {exc}")


class BrowserClose(AbstractTool):
    """Close the browser session."""

    name = "browser_close"
    description = "Close the headless browser and free resources."
    parameters = {"type": "object", "properties": {}}
    required_permissions = [Permission.LOW]

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        global _browser, _page
        try:
            if _page and not _page.is_closed():
                await _page.close()
            if _browser:
                await _browser.close()
            _page = None
            _browser = None
            return ToolResult(success=True, output="Browser closed.")
        except Exception as exc:
            _page = None
            _browser = None
            return ToolResult(success=False, error=f"Close failed: {exc}")


class BrowserRefresh(AbstractTool):
    """Reload the current page in the browser."""

    name = "browser_refresh"
    description = "Reload/refresh the current page in the headless browser."
    parameters = {"type": "object", "properties": {}}
    required_permissions = [Permission.MEDIUM]
    timeout = 15.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        global _page
        if _page is None or _page.is_closed():
            return ToolResult(success=False, error="Browser not running. Open a URL first.")
        try:
            await _page.reload(wait_until="domcontentloaded", timeout=15000)
            title = await _page.title()
            return ToolResult(success=True, output=f"Page reloaded. Title: {title}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Refresh failed: {exc}")


class BrowserPressKey(AbstractTool):
    """Press a key in the browser (Enter, Tab, Escape, etc.)."""

    name = "browser_press_key"
    description = "Press a keyboard key in the browser page."
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Key to press (Enter, Tab, Escape, ArrowDown, etc.)"},
        },
        "required": ["key"],
    }
    required_permissions = [Permission.MEDIUM]
    timeout = 5.0

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        global _page
        key = params.get("key", "Enter")
        if _page is None or _page.is_closed():
            return ToolResult(success=False, error="Browser not running.")
        try:
            await _page.keyboard.press(key)
            return ToolResult(success=True, output=f"Pressed: {key}")
        except Exception as exc:
            return ToolResult(success=False, error=f"Key press failed: {exc}")
