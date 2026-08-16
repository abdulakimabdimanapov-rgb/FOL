"""Tests for plugin hooks."""

from __future__ import annotations

import pytest
from modules.plugins.manager import PluginManager
from modules.plugins.base import FOLPlugin
from core.event_bus import EventBus


class InputHookPlugin(FOLPlugin):
    name = "input-hook"
    version = "0.1.0"

    async def on_user_input(self, text: str) -> str | None:
        return f"hooked:{text}"

    async def on_load(self): pass
    async def on_unload(self): pass


class ResponseHookPlugin(FOLPlugin):
    name = "response-hook"
    version = "0.1.0"

    async def after_llm_response(self, response: str) -> str:
        return f"{response} [modified]"

    async def on_load(self): pass
    async def on_unload(self): pass


@pytest.fixture
def manager_with_hooks() -> PluginManager:
    return PluginManager(event_bus=EventBus())


@pytest.mark.asyncio
async def test_user_input_hook(manager_with_hooks: PluginManager):
    plugin = InputHookPlugin()
    await manager_with_hooks.register_plugin(plugin)
    await manager_with_hooks.enable_plugin("input-hook")
    result = await manager_with_hooks.run_user_input_hooks("hello")
    assert result == "hooked:hello"


@pytest.mark.asyncio
async def test_after_llm_hook(manager_with_hooks: PluginManager):
    plugin = ResponseHookPlugin()
    await manager_with_hooks.register_plugin(plugin)
    await manager_with_hooks.enable_plugin("response-hook")
    result = await manager_with_hooks.run_after_llm_hooks("original")
    assert result == "original [modified]"
