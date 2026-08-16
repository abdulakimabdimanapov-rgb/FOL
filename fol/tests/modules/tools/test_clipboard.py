"""Tests for clipboard tools."""

from __future__ import annotations

import pytest
from modules.tools.system.clipboard import ReadClipboard, WriteClipboard


@pytest.mark.asyncio
async def test_write_and_read():
    writer = WriteClipboard()
    reader = ReadClipboard()
    result = await writer.execute({"text": "hello clipboard"})
    assert result.success
    result = await reader.execute({})
    assert result.success
    assert "hello clipboard" in result.output


@pytest.mark.asyncio
async def test_write_empty():
    tool = WriteClipboard()
    result = await tool.execute({"text": ""})
    assert not result.success
