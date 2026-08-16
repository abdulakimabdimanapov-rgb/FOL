"""Tests for mouse/keyboard tools."""

from __future__ import annotations

import pytest
from modules.tools.mouse_keyboard.keyboard_controller import TypeText, PressKey


@pytest.mark.asyncio
async def test_type_text_empty():
    tool = TypeText()
    result = await tool.execute({"text": ""})
    assert not result.success


@pytest.mark.asyncio
async def test_press_key_empty():
    tool = PressKey()
    result = await tool.execute({"key": ""})
    assert not result.success


def test_key_code_mapping():
    tool = PressKey()
    assert tool._get_key_code("return") == 36
    assert tool._get_key_code("tab") == 48
    assert tool._get_key_code("a") == 0
