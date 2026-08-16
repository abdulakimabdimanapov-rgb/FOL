"""Tests for ToolRegistry."""

from __future__ import annotations

import pytest
from modules.tools.registry import ToolRegistry
from modules.tools.base import AbstractTool, ToolResult
from typing import Any


class DummyTool(AbstractTool):
    name = "dummy"
    description = "A dummy tool"
    parameters = {"type": "object", "properties": {"msg": {"type": "string"}}}

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, output=f"echo: {params.get('msg', '')}")


def test_register_and_get():
    reg = ToolRegistry()
    tool = DummyTool()
    reg.register(tool)
    assert reg.get("dummy") is tool


def test_unregister():
    reg = ToolRegistry()
    reg.register(DummyTool())
    reg.unregister("dummy")
    assert reg.get("dummy") is None


def test_list_all():
    reg = ToolRegistry()
    reg.register(DummyTool())
    tools = reg.list_all()
    assert len(tools) == 1
    assert tools[0].name == "dummy"


@pytest.mark.asyncio
async def test_execute():
    reg = ToolRegistry()
    reg.register(DummyTool())
    result = await reg.execute("dummy", {"msg": "hello"})
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_execute_not_found():
    reg = ToolRegistry()
    result = await reg.execute("nonexistent", {})
    assert not result.success
    assert "not found" in result.error


def test_to_openai_tools():
    reg = ToolRegistry()
    reg.register(DummyTool())
    tools = reg.to_openai_tools()
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "dummy"
