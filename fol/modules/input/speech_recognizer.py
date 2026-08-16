"""Speech recognition module — audio to text via Whisper."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from modules.input.base import AbstractInputModule, UserInput

logger = logging.getLogger(__name__)

try:
    import sounddevice as sd
    import soundfile as sf
    HAS_AUDIO = True
except ImportError:
    sd = None
    sf = None
    HAS_AUDIO = False

try:
    import mlx_whisper
    HAS_MLX_WHISPER = True
except ImportError:
    HAS_MLX_WHISPER = False

try:
    import speech_recognition as sr
    HAS_SPEECH_RECOGNITION = True
except ImportError:
    sr = None
    HAS_SPEECH_RECOGNITION = False


SAMPLE_RATE = 16000
CHANNELS = 1


class SpeechRecognizer(AbstractInputModule):
    """Speech-to-text using mlx-whisper or fallback speech_recognition."""

    name = "speech_recognizer"

    def __init__(
        self,
        model_size: str = "medium",
        language: str = "ru",
        device: str = "mps",
        record_seconds: int = 5,
    ) -> None:
        self._model_size = model_size
        self._language = language
        self._device = device
        self._record_seconds = record_seconds
        self._model: Any = None
        self._is_ready = False

    async def initialize(self) -> None:
        """Load the Whisper model."""
        if HAS_MLX_WHISPER:
            logger.info("Loading mlx-whisper model", model=self._model_size)
            try:
                self._model = await asyncio.to_thread(
                    mlx_whisper.load_model, self._model_size
                )
                self._is_ready = True
                logger.info("mlx-whisper model loaded successfully")
            except Exception as exc:
                logger.error("Failed to load mlx-whisper", error=str(exc))
        else:
            logger.warning("mlx-whisper not available, using speech_recognition fallback")

    async def shutdown(self) -> None:
        self._model = None
        self._is_ready = False
        logger.info("SpeechRecognizer shut down")

    async def capture(self) -> UserInput:
        """Record audio from microphone and transcribe."""
        if not HAS_AUDIO:
            return UserInput(text="", source="voice", confidence=0.0)

        logger.info("Recording audio", seconds=self._record_seconds)

        try:
            audio_data = await asyncio.to_thread(
                sd.rec,
                int(self._record_seconds * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
            )
            await asyncio.to_thread(sd.wait)
        except Exception as exc:
            logger.error("Audio recording failed", error=str(exc))
            return UserInput(text="", source="voice", confidence=0.0)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            if sf is not None:
                await asyncio.to_thread(sf.write, tmp_path, audio_data, SAMPLE_RATE)
            else:
                import wave
                with wave.open(tmp_path, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(audio_data.tobytes())

            text = await self._transcribe(tmp_path)
            return UserInput(
                text=text,
                source="voice",
                language=self._language,
                confidence=0.9 if text else 0.0,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _transcribe(self, audio_path: str) -> str:
        """Transcribe an audio file to text."""
        if self._model is not None and self._is_ready:
            return await self._transcribe_mlx(audio_path)
        if HAS_SPEECH_RECOGNITION:
            return await self._transcribe_sr(audio_path)
        logger.warning("No transcription backend available")
        return ""

    async def _transcribe_mlx(self, audio_path: str) -> str:
        """Transcribe using mlx-whisper."""
        try:
            result = await asyncio.to_thread(
                self._model.transcribe,
                audio_path,
                temperature=0.0,
                language=self._language,
            )
            text = result["text"].strip()
            logger.info("Transcription completed", text_length=len(text))
            return text
        except Exception as exc:
            logger.error("mlx-whisper transcription failed", error=str(exc))
            return ""

    async def _transcribe_sr(self, audio_path: str) -> str:
        """Transcribe using speech_recognition (fallback)."""
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(audio_path) as source:
                audio_data = recognizer.record(source)
            try:
                return recognizer.recognize_sphinx(audio_data)
            except Exception:
                pass
            try:
                return recognizer.recognize_google(audio_data, language=self._language)
            except Exception:
                return ""
        except Exception as exc:
            logger.error("speech_recognition failed", error=str(exc))
            return ""
