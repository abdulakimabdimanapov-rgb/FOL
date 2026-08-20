"""STT routing — ONE selection point for speech-to-text.

Default is the LOCAL provider (MLX Whisper, no API key). A cloud provider
(ElevenLabs) is OPT-IN via ``FOL_STT_PROVIDER=elevenlabs`` and only used when
its key is present — otherwise the router falls back to local. The unified
:func:`transcribe_audio` entry preserves the exact ``/api/stt`` response
contract: ``{"text": ...}`` or ``{"text": "", "error": "local_stt_unavailable", ...}``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from modules.input.voice.interface import STTProvider
from modules.input.voice.providers import ElevenLabsSTT, MLXWhisperSTT

logger = logging.getLogger(__name__)

LOCAL = "mlx_whisper"
CLOUD = "elevenlabs"


def get_stt(provider: str | None = None) -> STTProvider:
    """Select the STT provider.

    Resolution: explicit ``provider`` → ``FOL_STT_PROVIDER`` env → local.
    Cloud providers silently fall back to local when their credentials are
    missing (they are opt-in enhancements, never a requirement).
    """
    cfg = (provider or os.environ.get("FOL_STT_PROVIDER", "") or LOCAL).strip().lower()

    if cfg in ("elevenlabs", "cloud", "scribe"):
        cloud = ElevenLabsSTT()
        if cloud.is_available:
            return cloud
        logger.info("ElevenLabs STT requested but no ELEVENLABS_API_KEY — using local mlx-whisper")
        return MLXWhisperSTT()

    if cfg in (LOCAL, "local", "mlx", "whisper"):
        return MLXWhisperSTT()

    logger.warning("Unknown FOL_STT_PROVIDER=%r — using local mlx-whisper", cfg)
    return MLXWhisperSTT()


def available_providers() -> list[str]:
    """Providers that could be used (order = fallback chain)."""
    providers = [LOCAL]
    if ElevenLabsSTT().is_available:
        providers.append(CLOUD)
    return providers


def transcribe_audio(audio_path: str) -> dict[str, Any]:
    """Transcribe an audio file through the configured provider chain.

    Returns the canonical response dict — same contract as ``/api/stt``.
    """
    text = get_stt().transcribe(audio_path)
    if text:
        return {"text": text}

    local = MLXWhisperSTT()
    missing = local.missing_dependency
    return {
        "text": "",
        "error": "local_stt_unavailable",
        "detail": (
            f"Install mlx-whisper (pip install {missing}) for offline transcription"
            if missing
            else "Local speech recognition failed to transcribe the audio"
        ),
    }


__all__ = ["get_stt", "available_providers", "transcribe_audio", "LOCAL", "CLOUD"]
