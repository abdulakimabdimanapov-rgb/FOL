"""TTS output — ONE interface, provider-based.

Providers behind :class:`TTSProvider`:

- :class:`MacOSSayProvider` — default. Uses the macOS ``say`` binary; always
  available on macOS, degrades gracefully elsewhere.
- :class:`ElevenLabsProvider` — OPT-IN cloud (``FOL_TTS_PROVIDER=elevenlabs``
  + ``ELEVENLABS_API_KEY``). Fetches MP3 audio and plays it via ``afplay``.
  Falls back to macOS ``say`` when credentials are missing or the call fails.

Selection happens in :func:`get_tts` (``FOL_TTS_PROVIDER`` env). Providers
never raise — a failure degrades to ``False`` and the caller can fall back.
``TTSModule`` keeps the canonical ``OutputChannel`` contract used by the FOL
core app and delegates to the selected provider.
"""

from __future__ import annotations

import abc
import asyncio
import logging
import os
import shutil
import subprocess
from typing import Any

from modules.output.base import OutputChannel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TTSProvider — canonical interface
# ---------------------------------------------------------------------------

class TTSProvider(abc.ABC):
    """Canonical text-to-speech contract. Never raises."""

    name: str = "base"

    @property
    @abc.abstractmethod
    def is_available(self) -> bool:
        """True when this provider can speak right now."""

    @abc.abstractmethod
    async def speak(self, text: str) -> bool:
        """Speak ``text``. Returns True when speech was started."""


# ---------------------------------------------------------------------------
# MacOSSayProvider — default, no dependencies
# ---------------------------------------------------------------------------

class MacOSSayProvider(TTSProvider):
    """Speaks via the macOS ``say`` command (fire-and-forget)."""

    name = "say"

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

    async def speak(self, text: str) -> bool:
        if not self.is_available or not text:
            return False
        cmd = ["say"]
        if self._voice:
            cmd += ["-v", self._voice]
        if self._rate:
            cmd += ["-r", str(self._rate)]
        cmd.append(text)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._processes.add(proc)
            return True
        except Exception as exc:
            logger.warning("MacOSSayProvider speak failed: %s", exc)
            return False

    async def stop(self) -> None:
        for proc in list(self._processes):
            if getattr(proc, "returncode", None) is None:
                try:
                    await proc.kill()
                except Exception:
                    pass
        self._processes.clear()
        self._probed = None


# ---------------------------------------------------------------------------
# ElevenLabsProvider — opt-in cloud (JARVIS-class voices)
# ---------------------------------------------------------------------------

class ElevenLabsProvider(TTSProvider):
    """Cloud TTS via ElevenLabs (opt-in, ``FOL_TTS_PROVIDER=elevenlabs``).

    Reads ``ELEVENLABS_API_KEY`` and ``ELEVENLABS_VOICE_ID`` from the
    environment — never hardcoded, never logged. Downloads MP3 audio and
    plays it with ``afplay``.
    """

    name = "elevenlabs"

    DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # "George" — JARVIS-like baritone
    ENDPOINT = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    MODEL = "eleven_multilingual_v2"

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("ELEVENLABS_API_KEY", "")
        self._voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "") or self.DEFAULT_VOICE_ID

    @property
    def is_available(self) -> bool:
        return bool(self._api_key) and shutil.which("afplay") is not None

    async def speak(self, text: str) -> bool:
        trimmed = (text or "").strip()
        if not self.is_available or not trimmed:
            return False
        import json
        import os
        import tempfile
        import urllib.error
        import urllib.request
        from pathlib import Path

        body = json.dumps({
            "text": trimmed,
            "model_id": self.MODEL,
            "voice_settings": {
                "stability": 0.7,
                "similarity_boost": 0.75,
                "style": 0.1,
                "use_speaker_boost": True,
            },
        }).encode("utf-8")
        req = urllib.request.Request(
            self.ENDPOINT.format(voice_id=self._voice_id),
            data=body,
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                audio = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read()[:200]
            except Exception:
                detail = b""
            logger.warning("ElevenLabs TTS HTTP %s: %s", exc.code, detail)
            return False
        except Exception as exc:
            logger.warning("ElevenLabs TTS network error: %s", exc)
            return False
        if not audio:
            return False

        fd, tmp_name = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            tmp.write_bytes(audio)
            proc = await asyncio.create_subprocess_exec(
                "afplay", str(tmp),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as exc:
            logger.warning("ElevenLabs TTS playback failed: %s", exc)
            return False
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Factory — ONE selection point
# ---------------------------------------------------------------------------

def get_tts(provider: str | None = None, *, voice: str | None = None, rate: int | None = None) -> TTSProvider:
    """Select the TTS provider.

    Resolution: explicit ``provider`` → ``FOL_TTS_PROVIDER`` env → ``say``.
    A requested cloud provider silently falls back to macOS ``say`` when its
    credentials are missing (cloud is opt-in, never a requirement).
    """
    cfg = (provider or os.environ.get("FOL_TTS_PROVIDER", "") or "say").strip().lower()

    if cfg in ("elevenlabs", "cloud"):
        cloud = ElevenLabsProvider()
        if cloud.is_available:
            return cloud
        logger.info("ElevenLabs TTS requested but not configured — using macOS say")
        return MacOSSayProvider(voice=voice, rate=rate)

    return MacOSSayProvider(voice=voice, rate=rate)


def available_providers() -> list[str]:
    """Providers that could be used (order = preference)."""
    providers = ["say"]
    if ElevenLabsProvider().is_available:
        providers.append("elevenlabs")
    return providers


# ---------------------------------------------------------------------------
# TTSModule — canonical OutputChannel, delegates to the selected provider
# ---------------------------------------------------------------------------

class TTSModule(OutputChannel):
    """Speaks assistant text aloud through the selected TTS provider.

    Matches the interface expected by ``core.app.FOL`` (initialize / send /
    shutdown) and the canonical ``OutputChannel`` contract.
    """

    name = "tts"

    def __init__(self, voice: str | None = None, rate: int | None = None) -> None:
        self._voice = voice
        self._rate = rate
        self._provider: TTSProvider = get_tts(voice=voice, rate=rate)

    @property
    def is_available(self) -> bool:
        return self._provider.is_available

    async def initialize(self) -> None:
        self._provider = get_tts(voice=self._voice, rate=self._rate)
        logger.info("TTS initialized (provider=%s, available=%s)", self._provider.name, self.is_available)

    async def send(self, text: str) -> bool:
        return await self._provider.speak(text)

    async def shutdown(self) -> None:
        if isinstance(self._provider, MacOSSayProvider):
            await self._provider.stop()


__all__ = [
    "TTSProvider",
    "MacOSSayProvider",
    "ElevenLabsProvider",
    "get_tts",
    "available_providers",
    "TTSModule",
]
