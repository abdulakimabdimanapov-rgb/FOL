"""Notification output channel — macOS notifications via ``osascript``.

Degrades gracefully on platforms without ``osascript`` (``send`` returns
``False`` and logs a warning).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess

from modules.output.base import OutputChannel

logger = logging.getLogger(__name__)


class NotificationModule(OutputChannel):
    """Sends a macOS notification banner with ``osascript display notification``."""

    name = "notification"

    def __init__(self, title: str = "FOL") -> None:
        self._title = title

    async def initialize(self) -> None:
        return None

    async def send(self, text: str) -> bool:
        if not text or shutil.which("osascript") is None:
            return False
        script = f'display notification "{text}" with title "{self._title}"'
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as exc:
            logger.warning("Notification send failed: %s", exc)
            return False

    async def shutdown(self) -> None:
        return None
