"""Clipboard output module — copy responses to clipboard."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.output.base import AbstractOutputModule

logger = logging.getLogger(__name__)


class ClipboardOutput(AbstractOutputModule):
    """Copy text to the system clipboard."""

    name = "clipboard_out"
    description = "Copy text to the system clipboard"

    async def initialize(self) -> None:
        """Initialize clipboard output."""
        logger.info("Clipboard output initialized")

    async def send(self, text: str, **kwargs: Any) -> bool:
        """Copy text to clipboard."""
        try:
            process = await asyncio.create_subprocess_exec(
                "pbcopy",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.communicate(input=text.encode("utf-8"))
            logger.info("Text copied to clipboard", length=len(text))
            return True
        except Exception as exc:
            logger.error("Failed to copy to clipboard", error=str(exc))
            return False

    async def shutdown(self) -> None:
        """Shutdown clipboard output."""
        pass
