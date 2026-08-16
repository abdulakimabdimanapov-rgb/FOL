"""Display output channel — prints assistant text to stdout.

Useful for terminal/CLI modes and as a fallback when no richer output
channel is configured.
"""

from __future__ import annotations

import logging

from modules.output.base import OutputChannel

logger = logging.getLogger(__name__)


class DisplayModule(OutputChannel):
    """Prints text to stdout."""

    name = "display"

    async def initialize(self) -> None:
        return None

    async def send(self, text: str) -> bool:
        if not text:
            return False
        print(text)
        return True

    async def shutdown(self) -> None:
        return None
