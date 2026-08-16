"""Tests for browser tools."""

from __future__ import annotations

import pytest
from modules.tools.browser.browser_automation import BrowserNavigate, BrowserSearch, GetPageContent


@pytest.mark.asyncio
async def test_navigate_empty():
    tool = BrowserNavigate()
    result = await tool.execute({"url": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_search_empty():
    tool = BrowserSearch()
    result = await tool.execute({"query": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_get_page_empty():
    tool = GetPageContent()
    result = await tool.execute({"url": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_get_page_content():
    tool = GetPageContent()
    result = await tool.execute({"url": "https://httpbin.org/html", "max_chars": 500})
    assert result.success
    assert len(result.output) > 0
