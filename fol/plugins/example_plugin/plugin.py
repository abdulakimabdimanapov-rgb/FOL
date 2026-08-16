"""Example FOL plugin — demonstrates the plugin API."""

from __future__ import annotations

import logging
from typing import Any

from core.event_bus import Event
from modules.plugins.base import FOLPlugin

logger = logging.getLogger(__name__)


class HelloWorldPlugin(FOLPlugin):
    """Simple example plugin that greets the user and logs events."""

    name = "hello-world"
    version = "0.1.0"
    description = "Example plugin demonstrating FOL plugin API"

    async def on_load(self) -> None:
        logger.info("HelloWorld plugin loaded!")

    async def on_unload(self) -> None:
        logger.info("HelloWorld plugin unloaded!")

    async def on_enable(self) -> None:
        logger.info("HelloWorld plugin enabled!")

    async def on_disable(self) -> None:
        logger.info("HelloWorld plugin disabled!")

    async def on_event(self, event: Event) -> None:
        """Log all events."""
        logger.debug("HelloWorld saw event: %s from %s", event.type.name, event.source)

    async def on_user_input(self, text: str) -> str | None:
        """Example: modify input — add a prefix if it starts with 'hello'."""
        if text.lower().startswith("hello"):
            return f"[Plugin-modified] {text}"
        return None

    async def after_llm_response(self, response: str) -> str:
        """Example: append a tag to all responses."""
        return f"{response}\n[hello-world plugin active]"
