"""Tests for ExecuteCommand tool."""

from __future__ import annotations

import pytest
from modules.tools.system.execute_command import ExecuteCommand


@pytest.mark.asyncio
async def test_execute_echo():
    tool = ExecuteCommand()
    result = await tool.execute({"command": "echo hello"})
    assert result.success
    assert "hello" in result.output


@pytest.mark.asyncio
async def test_blocked_command():
    tool = ExecuteCommand()
    result = await tool.execute({"command": "sudo rm -rf /"})
    assert not result.success
    assert "blocked" in result.error.lower()


@pytest.mark.asyncio
async def test_empty_command():
    tool = ExecuteCommand()
    result = await tool.execute({"command": ""})
    assert not result.success
