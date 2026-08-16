"""TTS output channel — macOS speech synthesis via the ``say`` command.

No third-party dependencies: on macOS the system ``say`` binary is always
available; on headless/CI environments the channel degrades gracefully
(``is_available`` is False and ``send`` becomes a no-op).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from typing import Any

from modules.output.base import OutputChannel

logger = logging.getLogger(__name__)


class TTSModule(OutputChannel):
    """Speaks assistant text aloud using macOS ``say``.

    Matches the interface expected by ``core.app.FOL`` (initialize / send /
    shutdown) and the canonical ``OutputChannel`` contract.
    """

    name = "tts"

    def __init__(self, voice: str | None = None, rate: int | None = None) -> None:
        self._voice = voice
        self._rate = rate
        self._probed: bool | None = None
        self._processes: set[Any] = set()

    @property
    def is_available(self) -> bool:
        if self._probed is None:
            self._probed = shutil.which("say") is not None
        return self._probed

    async def initialize(self) -> None:
        self._probed = shutil.which("say") is not None
        logger.info("TTS initialized (available=%s)", self.is_available)

    async def send(self, text: str) -> bool:
        if not self.is_available or not text:
            return False
        cmd = ["say"]
        if self._voice:
            cmd += ["-v", self._voice]
        if self._rate:
            cmd += ["-r", str(self._rate)]
        cmd.append(text)
        try:
            # Fire-and-forget: speech continues while the loop moves on.
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._processes.add(proc)
            return True
        except Exception as exc:
            logger.warning("TTS send failed: %s", exc)
            return False

    async def shutdown(self) -> None:
        """Kill any still-speaking ``say`` processes and reset state."""
        for proc in list(self._processes):
            if getattr(proc, "returncode", None) is None:
                try:
                    await proc.kill()
                except Exception:
                    pass
        self._processes.clear()
        self._probed = None
