"""Cloud STT provider — Groq Whisper API.

Uses Groq's whisper-large-v3 model for fast, accurate speech-to-text.
Groq provides a generous free tier (~30 req/min) and supports 99+ languages.

Inspired by https://github.com/egraich/voicebot which uses the same API.

Requires: GROQ_API_KEY in environment.
Activation: FOL_STT_PROVIDER=groq (or FOL_STT_PROVIDER=groq_whisper)

The provider:
  1. Reads the audio file (WAV, FLAC, MP3, OGG, etc.)
  2. Sends it as multipart form to Groq's /v1/audio/transcriptions
  3. Returns the transcribed text

Groq automatically resamples audio to 16kHz internally, so no FFmpeg
pre-processing is needed (unlike self-hosted Whisper).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from modules.input.voice.interface import STTProvider

logger = logging.getLogger(__name__)

# Groq Whisper API endpoint (OpenAI-compatible format)
ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3"
TIMEOUT = 30.0


class GroqWhisperSTT(STTProvider):
    """Cloud transcription via Groq's Whisper API (opt-in).

    Fast, accurate, supports 99+ languages. Free tier available.
    Requires GROQ_API_KEY environment variable.
    """

    name = "groq_whisper"

    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL) -> None:
        self._api_key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()
        self._model = model

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def transcribe(self, audio_path: str) -> str:
        """Transcribe an audio file via Groq's Whisper API.

        Args:
            audio_path: path to audio file (WAV, FLAC, MP3, OGG, etc.)

        Returns:
            Transcribed text, or "" on failure.
        """
        if not self.is_available:
            return ""

        try:
            data = Path(audio_path).read_bytes()
        except Exception as exc:
            logger.warning("Groq Whisper STT: cannot read audio: %s", exc)
            return ""

        # Build multipart form body
        boundary = uuid.uuid4().hex
        filename = Path(audio_path).name or "recording.wav"

        # Detect content type from extension
        ext = Path(audio_path).suffix.lower()
        content_types = {
            ".wav": "audio/wav",
            ".flac": "audio/flac",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
            ".oga": "audio/ogg",
            ".m4a": "audio/mp4",
            ".webm": "audio/webm",
        }
        content_type = content_types.get(ext, "audio/wav")

        parts = [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="model"\r\n\r\n',
            self._model.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        body = b"".join(parts)

        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read()[:200]
            except Exception:
                detail = b""
            logger.warning("Groq Whisper STT HTTP %s: %s", exc.code, detail)
            return ""
        except Exception as exc:
            logger.warning("Groq Whisper STT network error: %s", exc)
            return ""

        try:
            parsed = json.loads(raw)
            return (parsed.get("text", "") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Groq Whisper STT: unparseable response")
            return ""

    def status(self) -> dict:
        """Return provider status (never leaks the API key)."""
        base = super().status()
        if self.is_available:
            base["model"] = self._model
            base["endpoint"] = ENDPOINT
        return base


__all__ = ["GroqWhisperSTT"]
