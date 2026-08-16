"""Plugin manager — manages plugin lifecycle, enable/disable, hooks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

from core.event_bus import Event, EventBus, EventType
from modules.plugins.base import FOLPlugin, PluginManifest
from modules.plugins.loader import PluginLoader

logger = logging.getLogger(__name__)

HookFunc = Callable[..., Coroutine[Any, Any, Any]]


class PluginManager:
    """Manages FOL plugins: loading, unloading, enable/disable, hooks."""

    def __init__(self, event_bus: EventBus, plugin_dirs: list[Path] | None = None) -> None:
        self._event_bus = event_bus
        self._loader = PluginLoader(plugin_dirs)
        self._plugins: dict[str, FOLPlugin] = {}
        self._manifests: dict[str, PluginManifest] = {}
        self._enabled: set[str] = set()

        # Hook lists
        self._before_llm_hooks: list[HookFunc] = []
        self._after_llm_hooks: list[HookFunc] = []
        self._user_input_hooks: list[HookFunc] = []

    def add_plugin_directory(self, path: Path) -> None:
        """Add a directory to scan for plugins."""
        self._loader.add_directory(path)

    async def discover_and_load(self) -> int:
        """Discover and load all plugins. Returns count loaded."""
        discovered = self._loader.discover()
        loaded = 0
        for plugin_dir in discovered:
            plugin, manifest = self._loader.load_plugin(plugin_dir)
            if plugin and manifest:
                await self.register_plugin(plugin, manifest)
                loaded += 1
        logger.info("Discovered and loaded %d plugins", loaded)
        return loaded

    async def register_plugin(self, plugin: FOLPlugin, manifest: PluginManifest | None = None) -> None:
        """Register a plugin."""
        name = plugin.name
        self._plugins[name] = plugin
        if manifest:
            self._manifests[name] = manifest

        # Subscribe plugin to events
        self._event_bus.subscribe(EventType.USER_INPUT_RECEIVED, plugin.on_event)
        self._event_bus.subscribe(EventType.LLM_RESPONSE_READY, plugin.on_event)

        # Collect hooks
        if hasattr(plugin, "on_user_input") and plugin.on_user_input is not FOLPlugin.on_user_input:
            self._user_input_hooks.append(plugin.on_user_input)
        if hasattr(plugin, "before_llm_call") and plugin.before_llm_call is not FOLPlugin.before_llm_call:
            self._before_llm_hooks.append(plugin.before_llm_call)
        if hasattr(plugin, "after_llm_response") and plugin.after_llm_response is not FOLPlugin.after_llm_response:
            self._after_llm_hooks.append(plugin.after_llm_response)

        await plugin.on_load()
        logger.info("Plugin registered: %s", name)

    async def unregister_plugin(self, name: str) -> None:
        """Unregister and unload a plugin."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return

        await plugin.on_disable()
        await plugin.on_unload()

        # Remove hooks
        self._user_input_hooks = [h for h in self._user_input_hooks if h.__self__ is not plugin]
        self._before_llm_hooks = [h for h in self._before_llm_hooks if h.__self__ is not plugin]
        self._after_llm_hooks = [h for h in self._after_llm_hooks if h.__self__ is not plugin]

        del self._plugins[name]
        self._manifests.pop(name, None)
        self._enabled.discard(name)
        logger.info("Plugin unregistered: %s", name)

    async def enable_plugin(self, name: str) -> bool:
        """Enable a plugin."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return False
        if name in self._enabled:
            return True

        await plugin.on_enable()
        plugin._enabled = True
        self._enabled.add(name)
        logger.info("Plugin enabled: %s", name)
        return True

    async def disable_plugin(self, name: str) -> bool:
        """Disable a plugin."""
        plugin = self._plugins.get(name)
        if plugin is None:
            return False

        await plugin.on_disable()
        plugin._enabled = False
        self._enabled.discard(name)
        logger.info("Plugin disabled: %s", name)
        return True

    def get_plugin(self, name: str) -> FOLPlugin | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all registered plugins with status."""
        result = []
        for name, plugin in self._plugins.items():
            manifest = self._manifests.get(name, plugin.manifest)
            result.append({
                "name": name,
                "version": manifest.version,
                "description": manifest.description,
                "enabled": name in self._enabled,
            })
        return result

    # Hook executors
    async def run_user_input_hooks(self, text: str) -> str:
        """Run all user input hooks. Returns modified text."""
        for hook in self._user_input_hooks:
            try:
                result = await hook(text)
                if result is not None:
                    text = result
            except Exception as exc:
                logger.error("User input hook error: %s", exc)
        return text

    async def run_before_llm_hooks(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Run all before-LLM hooks. Returns modified messages."""
        for hook in self._before_llm_hooks:
            try:
                messages = await hook(messages)
            except Exception as exc:
                logger.error("Before LLM hook error: %s", exc)
        return messages

    async def run_after_llm_hooks(self, response: str) -> str:
        """Run all after-LLM hooks. Returns modified response."""
        for hook in self._after_llm_hooks:
            try:
                result = await hook(response)
                if result is not None:
                    response = result
            except Exception as exc:
                logger.error("After LLM hook error: %s", exc)
        return response
