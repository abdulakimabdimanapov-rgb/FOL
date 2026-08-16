"""Text input module — direct text input from CLI/API."""

from __future__ import annotations

import logging

from modules.input.base import AbstractInputModule, UserInput

logger = logging.getLogger(__name__)


class TextInput(AbstractInputModule):
    """Handles direct text input."""

    name = "text_input"

    async def initialize(self) -> None:
        logger.info("TextInput module initialized")

    async def shutdown(self) -> None:
        logger.info("TextInput module shut down")

    async def capture(self) -> UserInput:
        """Capture is not used for text input — use feed() instead."""
        return UserInput(text="", source="text")

    def feed(self, text: str) -> UserInput:
        """Create a UserInput from raw text."""
        logger.debug("Text input received", length=len(text))
        return UserInput(text=text.strip(), source="text", confidence=1.0)
