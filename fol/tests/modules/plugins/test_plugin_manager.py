"""Tests for PluginManager."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.plugins.manager import PluginManager
from modules.plugins.base import FOLPlugin, PluginManifest
from core.event_bus import EventBus


class SamplePlugin(FOLPlugin):
    name = "test-plugin"
    version = "0.1.0"
    loaded = False
    enabled = False

    async def on_load(self):
        SamplePlugin.loaded = True

    async def on_unload(self):
        SamplePlugin.loaded = False

    async def on_enable(self):
        SamplePlugin.enabled = True

    async def on_disable(self):
        SamplePlugin.enabled = False


@pytest.fixture
def manager() -> PluginManager:
    return PluginManager(event_bus=EventBus())


@pytest.mark.asyncio
async def test_register_plugin(manager: PluginManager):
    plugin = SamplePlugin()
    manifest = PluginManifest(name="test-plugin", version="0.1.0")
    await manager.register_plugin(plugin, manifest)
    assert manager.get_plugin("test-plugin") is plugin
    assert SamplePlugin.loaded


@pytest.mark.asyncio
async def test_unregister_plugin(manager: PluginManager):
    plugin = SamplePlugin()
    await manager.register_plugin(plugin)
    await manager.unregister_plugin("test-plugin")
    assert manager.get_plugin("test-plugin") is None
    assert not SamplePlugin.loaded


@pytest.mark.asyncio
async def test_enable_disable(manager: PluginManager):
    plugin = SamplePlugin()
    await manager.register_plugin(plugin)
    await manager.enable_plugin("test-plugin")
    assert SamplePlugin.enabled
    await manager.disable_plugin("test-plugin")
    assert not SamplePlugin.enabled


@pytest.mark.asyncio
async def test_list_plugins(manager: PluginManager):
    plugin = SamplePlugin()
    manifest = PluginManifest(name="test-plugin", version="1.0", description="Test")
    await manager.register_plugin(plugin, manifest)
    await manager.enable_plugin("test-plugin")
    plugins = manager.list_plugins()
    assert len(plugins) == 1
    assert plugins[0]["name"] == "test-plugin"
    assert plugins[0]["enabled"] is True


@pytest.mark.asyncio
async def test_discover_plugins(manager: PluginManager, tmp_path: Path):
    plugin_dir = tmp_path / "test_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text('{"name": "discovered", "version": "0.1.0"}')
    (plugin_dir / "plugin.py").write_text("""
from modules.plugins.base import FOLPlugin
class DiscoveredPlugin(FOLPlugin):
    name = "discovered"
    version = "0.1.0"
    async def on_load(self): pass
    async def on_unload(self): pass
""")
    manager.add_plugin_directory(tmp_path)
    loaded = await manager.discover_and_load()
    assert loaded >= 1
