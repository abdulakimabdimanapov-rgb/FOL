"""Opt-in cloud STT provider — ElevenLabs Scribe.

Explicitly OPT-IN: the provider is only usable when ``ELEVENLABS_API_KEY`` is
present in the environment (never hardcoded, never logged). Without a key
``is_available`` is False and the router uses the local provider instead.
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

ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = "scribe_v1"
TIMEOUT = 30.0


class ElevenLabsSTT(STTProvider):
    """Cloud transcription via ElevenLabs Scribe (opt-in)."""

    name = "elevenlabs"

    def __init__(self, api_key: str | None = None, model: str = MODEL) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get("ELEVENLABS_API_KEY", "")
        self._model = model

    @property
    def is_available(self) -> bool:
        return bool(self._api_key)

    def transcribe(self, audio_path: str) -> str:
        if not self.is_available:
            return ""
        try:
            data = Path(audio_path).read_bytes()
        except Exception as exc:
            logger.warning("ElevenLabs STT: cannot read audio: %s", exc)
            return ""

        boundary = uuid.uuid4().hex
        parts = [
            f"--{boundary}\r\n".encode(),
            b"Content-Disposition: form-data; name=\"model_id\"\r\n\r\n",
            self._model.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b"Content-Disposition: form-data; name=\"file\"; filename=\"recording.wav\"\r\n",
            b"Content-Type: audio/wav\r\n\r\n",
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
        body = b"".join(parts)

        req = urllib.request.Request(
            ENDPOINT,
            data=body,
            headers={
                "xi-api-key": self._api_key,
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
            logger.warning("ElevenLabs STT HTTP %s: %s", exc.code, detail)
            return ""
        except Exception as exc:
            logger.warning("ElevenLabs STT network error: %s", exc)
            return ""

        try:
            parsed = json.loads(raw)
            return (parsed.get("text", "") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            logger.warning("ElevenLabs STT: unparseable response")
            return ""


__all__ = ["ElevenLabsSTT"]
