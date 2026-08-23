"""Cross-platform STT fallback — auto-selects the best provider for the current OS.

Provider priority by platform:
  macOS:   mlx_whisper (local, offline) → groq_whisper (cloud, free) → speech_recognition
  Windows: groq_whisper (cloud, free) → speech_recognition
  Linux:   groq_whisper (cloud, free) → speech_recognition

This module is used by the STT router when no explicit provider is set.
"""

from __future__ import annotations

import logging
import os
import sys

from modules.input.voice.interface import STTProvider

logger = logging.getLogger(__name__)


def get_best_stt_provider() -> STTProvider:
    """Select the best STT provider for the current platform.

    Returns the first available provider in the platform-specific priority chain.
    """
    # Check explicit override first
    explicit = os.environ.get("FOL_STT_PROVIDER", "").strip().lower()
    if explicit:
        return _resolve_explicit(explicit)

    # Platform-specific chain
    if sys.platform == "darwin":
        return _macos_chain()
    elif sys.platform == "win32":
        return _windows_chain()
    else:
        return _linux_chain()


def _resolve_explicit(name: str) -> STTProvider:
    """Resolve an explicitly requested provider."""
    from modules.input.voice.providers.mlx_whisper import MLXWhisperSTT
    from modules.input.voice.providers.groq_whisper import GroqWhisperSTT
    from modules.input.voice.providers.elevenlabs import ElevenLabsSTT

    if name in ("groq", "groq_whisper", "whisper_api"):
        p = GroqWhisperSTT()
        if p.is_available:
            return p
        logger.info("Groq STT requested but no GROQ_API_KEY — trying fallback")

    if name in ("elevenlabs", "cloud", "scribe"):
        p = ElevenLabsSTT()
        if p.is_available:
            return p
        logger.info("ElevenLabs STT requested but no ELEVENLABS_API_KEY — trying fallback")

    if name in ("mlx_whisper", "local", "mlx", "whisper"):
        p = MLXWhisperSTT()
        if p.is_available:
            return p
        logger.info("MLX Whisper requested but not available — trying fallback")

    # Fallback to platform chain
    return get_best_stt_provider()


def _macos_chain() -> STTProvider:
    """macOS STT chain: mlx_whisper → groq → speech_recognition."""
    from modules.input.voice.providers.mlx_whisper import MLXWhisperSTT
    from modules.input.voice.providers.groq_whisper import GroqWhisperSTT

    # 1. Local MLX Whisper (offline, fast, Apple Silicon)
    mlx = MLXWhisperSTT()
    if mlx.is_available:
        logger.info("STT: using mlx_whisper (local, offline)")
        return mlx

    # 2. Groq Whisper (cloud, free, fast)
    groq = GroqWhisperSTT()
    if groq.is_available:
        logger.info("STT: using groq_whisper (cloud, free)")
        return groq

    # 3. Fallback to speech_recognition (built-in)
    logger.info("STT: using speech_recognition (built-in fallback)")
    return mlx  # MLXWhisperSTT falls back to speech_recognition internally


def _windows_chain() -> STTProvider:
    """Windows STT chain: groq → speech_recognition."""
    from modules.input.voice.providers.groq_whisper import GroqWhisperSTT
    from modules.input.voice.providers.mlx_whisper import MLXWhisperSTT

    # 1. Groq Whisper (cloud, free, fast) — best on Windows
    groq = GroqWhisperSTT()
    if groq.is_available:
        logger.info("STT: using groq_whisper (cloud, free)")
        return groq

    # 2. Fallback to speech_recognition (built-in)
    logger.info("STT: no GROQ_API_KEY — using speech_recognition (fallback)")
    return MLXWhisperSTT()  # Falls back to speech_recognition internally


def _linux_chain() -> STTProvider:
    """Linux STT chain: groq → speech_recognition."""
    from modules.input.voice.providers.groq_whisper import GroqWhisperSTT
    from modules.input.voice.providers.mlx_whisper import MLXWhisperSTT

    # 1. Groq Whisper (cloud, free, fast) — best on Linux
    groq = GroqWhisperSTT()
    if groq.is_available:
        logger.info("STT: using groq_whisper (cloud, free)")
        return groq

    # 2. Fallback to speech_recognition (built-in)
    logger.info("STT: no GROQ_API_KEY — using speech_recognition (fallback)")
    return MLXWhisperSTT()  # Falls back to speech_recognition internally


__all__ = ["get_best_stt_provider"]
