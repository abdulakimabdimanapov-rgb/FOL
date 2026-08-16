"""Abstract base class for output channels (TTS, Telegram, …)."""

from __future__ import annotations

import abc


class OutputChannel(abc.ABC):
    """Canonical output boundary — everything FOL speaks through.

    Output channels are pluggable sinks for assistant text: speech synthesis,
    messengers, dashboards, etc. New output systems should implement this
    interface and be registered on the FOL app.
    """

    name: str = "base_output"

    @property
    def is_available(self) -> bool:
        """Whether this channel is configured and can send messages."""
        return True

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Set up the channel (load voices, open connections, …)."""

    @abc.abstractmethod
    async def send(self, text: str) -> bool:
        """Send text through the channel. Returns True on success."""

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources."""


# Backward-compatible alias — pre-existing output channels
# (e.g. ``clipboard_out.py``) import this name.
AbstractOutputModule = OutputChannel
