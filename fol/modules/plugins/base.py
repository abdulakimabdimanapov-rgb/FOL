"""Abstract base class for FOL plugins."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from core.event_bus import Event


@dataclass
class PluginManifest:
    """Plugin metadata from manifest.json."""

    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    min_fol_version: str = "0.1.0"
    dependencies: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        return cls(
            name=data.get("name", ""),
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            min_fol_version=data.get("min_fol_version", "0.1.0"),
            dependencies=data.get("dependencies", []),
            tools=data.get("tools", []),
        )


class FOLPlugin(abc.ABC):
    """Base class for all FOL plugins."""

    name: str = "base_plugin"
    version: str = "0.1.0"
    description: str = ""

    def __init__(self) -> None:
        self._enabled = False
        self._fol: Any = None  # Reference to FOL app, set on load

    @abc.abstractmethod
    async def on_load(self) -> None:
        """Called when the plugin is loaded."""

    @abc.abstractmethod
    async def on_unload(self) -> None:
        """Called when the plugin is unloaded."""

    async def on_enable(self) -> None:
        """Called when the plugin is enabled."""

    async def on_disable(self) -> None:
        """Called when the plugin is disabled."""

    async def on_event(self, event: Event) -> None:
        """Called when any event is published."""

    async def on_user_input(self, text: str) -> str | None:
        """Hook: called before LLM processes input. Return modified text or None."""
        return None

    async def before_llm_call(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Hook: called before sending to LLM. Can modify messages."""
        return messages

    async def after_llm_response(self, response: str) -> str:
        """Hook: called after LLM response. Can modify response."""
        return response

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name=self.name,
            version=self.version,
            description=self.description,
        )
