"""Local MLX Whisper STT provider — the default. No API key required.

Runs on Apple Silicon via ``mlx_whisper`` (offline, private). When
``mlx_whisper`` is not installed it falls back to ``speech_recognition``
(Google needs network; Sphinx needs pocketsphinx) and reports the real
missing dependency through the router.
"""

from __future__ import annotations

import logging

from modules.input.voice.interface import STTProvider

logger = logging.getLogger(__name__)

try:
    import mlx_whisper  # type: ignore

    HAS_MLX_WHISPER = True
except ImportError:
    HAS_MLX_WHISPER = False

try:
    import speech_recognition as sr  # type: ignore

    HAS_SPEECH_RECOGNITION = True
except ImportError:
    sr = None
    HAS_SPEECH_RECOGNITION = False


class MLXWhisperSTT(STTProvider):
    """Offline local transcription (mlx-whisper → speech_recognition)."""

    name = "mlx_whisper"

    def __init__(self, language: str | None = None) -> None:
        self._language = language  # None → auto-detect

    @property
    def is_available(self) -> bool:
        return HAS_MLX_WHISPER

    def transcribe(self, audio_path: str) -> str:
        if HAS_MLX_WHISPER:
            text = self._transcribe_mlx(audio_path)
            if text:
                return text.strip()
            logger.warning("mlx-whisper returned empty — falling back")
        else:
            logger.warning("mlx-whisper not installed — offline local STT unavailable")
        if HAS_SPEECH_RECOGNITION:
            text = self._transcribe_sr(audio_path)
            if text:
                return text.strip()
        return ""

    def _transcribe_mlx(self, audio_path: str) -> str:
        try:
            result = mlx_whisper.transcribe(
                audio_path,
                temperature=0.0,
                language=self._language,
            )
            return (result.get("text", "") or "").strip()
        except Exception as exc:
            logger.warning("mlx-whisper transcription failed: %s", exc)
            return ""

    def _transcribe_sr(self, audio_path: str) -> str:
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(audio_path) as source:
                audio_data = recognizer.record(source)
            return recognizer.recognize_google(audio_data)
        except Exception as exc:
            logger.warning("speech_recognition fallback failed: %s", exc)
            return ""

    @property
    def missing_dependency(self) -> str | None:
        """None when usable; otherwise the dependency to install."""
        if HAS_MLX_WHISPER:
            return None
        return "mlx-whisper"


__all__ = ["MLXWhisperSTT"]
