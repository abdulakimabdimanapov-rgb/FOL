"""Voice interface — ONE speech-to-text abstraction.

Providers are interchangeable behind :class:`STTProvider`. Selection happens
in :func:`stt.get_stt` (default: local MLX Whisper — no API key required;
cloud ElevenLabs is opt-in). A provider NEVER raises: on any failure it
returns ``""`` and the router falls back to the next provider.
"""

from __future__ import annotations

import abc
from typing import Any


class STTProvider(abc.ABC):
    """Canonical STT contract."""

    name: str = "base"

    @property
    @abc.abstractmethod
    def is_available(self) -> bool:
        """True when this provider can actually transcribe right now."""

    @abc.abstractmethod
    def transcribe(self, audio_path: str) -> str:
        """Transcribe a WAV/audio file to text. Returns ``""`` on failure —
        never raises."""

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "available": self.is_available}


__all__ = ["STTProvider"]
