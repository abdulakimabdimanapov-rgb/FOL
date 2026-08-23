"""Cross-platform text-to-speech.

macOS:   say command (built-in)
Windows: PowerShell SAPI
Linux:   espeak / espeak-ng / festival
Cloud:   ElevenLabs (any platform, opt-in via ELEVENLABS_API_KEY)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


class TTSProvider:
    """Base TTS provider interface."""
    name: str = "base"

    def speak(self, text: str) -> bool:
        raise NotImplementedError

    @property
    def is_available(self) -> bool:
        return False


class MacOSSayProvider(TTSProvider):
    """macOS built-in TTS via `say` command."""
    name = "macos_say"

    def __init__(self, voice: str = "Alex", rate: int = 200):
        self._voice = voice
        self._rate = rate

    @property
    def is_available(self) -> bool:
        return sys.platform == "darwin" and shutil.which("say") is not None

    def speak(self, text: str) -> bool:
        if not self.is_available or not text:
            return False
        try:
            subprocess.Popen(
                ["say", "-v", self._voice, "-r", str(self._rate), text],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.warning("macOS say failed: %s", exc)
            return False


class WindowsSAPIProvider(TTSProvider):
    """Windows built-in TTS via PowerShell SAPI."""
    name = "windows_sapi"

    @property
    def is_available(self) -> bool:
        return sys.platform == "win32"

    def speak(self, text: str) -> bool:
        if not self.is_available or not text:
            return False
        try:
            ps = f"$s = New-Object -ComObject SAPI.SPVoice; $s.Speak('{text}')"
            subprocess.Popen(
                ["powershell", "-Command", ps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.warning("Windows SAPI failed: %s", exc)
            return False


class ESpeakProvider(TTSProvider):
    """Linux TTS via espeak / espeak-ng."""
    name = "espeak"

    def __init__(self, voice: str = "en", speed: int = 160):
        self._voice = voice
        self._speed = speed
        self._binary = self._find_binary()

    def _find_binary(self) -> str | None:
        for name in ("espeak-ng", "espeak"):
            path = shutil.which(name)
            if path:
                return path
        return None

    @property
    def is_available(self) -> bool:
        return self._binary is not None

    def speak(self, text: str) -> bool:
        if not self.is_available or not text:
            return False
        try:
            subprocess.Popen(
                [self._binary, "-v", self._voice, "-s", str(self._speed), text],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception as exc:
            logger.warning("espeak failed: %s", exc)
            return False


def get_tts_provider() -> TTSProvider:
    """Get the best available TTS provider for the current platform."""
    # Check for cloud TTS (ElevenLabs)
    if os.environ.get("ELEVENLABS_API_KEY", "").strip():
        try:
            from modules.input.voice.providers.elevenlabs import ElevenLabsTTS
            provider = ElevenLabsTTS()
            if provider.is_available:
                return provider
        except ImportError:
            pass

    # Platform-specific local providers
    if sys.platform == "darwin":
        return MacOSSayProvider()
    elif sys.platform == "win32":
        return WindowsSAPIProvider()
    else:
        espeak = ESpeakProvider()
        if espeak.is_available:
            return espeak

    # Fallback: no TTS
    return TTSProvider()


def speak(text: str) -> bool:
    """Speak text using the best available TTS provider."""
    provider = get_tts_provider()
    return provider.speak(text)


__all__ = [
    "TTSProvider",
    "MacOSSayProvider",
    "WindowsSAPIProvider",
    "ESpeakProvider",
    "get_tts_provider",
    "speak",
]
