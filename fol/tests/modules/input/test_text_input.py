"""Tests for TextInput module."""

from __future__ import annotations

import pytest
from modules.input.text_input import TextInput


@pytest.mark.asyncio
async def test_initialize():
    ti = TextInput()
    await ti.initialize()


@pytest.mark.asyncio
async def test_shutdown():
    ti = TextInput()
    await ti.shutdown()


def test_feed():
    ti = TextInput()
    result = ti.feed("hello world")
    assert result.text == "hello world"
    assert result.source == "text"
    assert result.confidence == 1.0


def test_feed_strips_whitespace():
    ti = TextInput()
    result = ti.feed("  hello  ")
    assert result.text == "hello"
