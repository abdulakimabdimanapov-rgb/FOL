"""Unified Voice Engine — ONE interface for all voice operations.

Combines STT (speech-to-text), TTS (text-to-speech), wake word detection,
and background listening into a single coherent API.

Architecture:
    VoiceEngine
     ├── STTProvider    (MLX Whisper / ElevenLabs — via stt.py)
     ├── TTSProvider    (MacOSSay / ElevenLabs — via tts.py)
     ├── WakeWordDetector  (keyword matching + optional ML)
     └── BackgroundListener  (continuous recording → silence → transcribe)

Usage:
    engine = VoiceEngine()
    await engine.start_listening()          # background mode
    text = await engine.transcribe_file(path)  # one-shot
    await engine.speak("Hello!")            # TTS
    engine.stop()                           # shutdown all

Events (via EventBus):
    EventType.VOICE_LISTENING      — background listening started
    EventType.VOICE_TRANSCRIBED    — text transcribed from audio
    EventType.VOICE_SPEAKING       — TTS started
    EventType.WAKE_WORD_DETECTED   — wake word heard
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Coroutine

from modules.input.voice.interface import STTProvider
from modules.input.voice.stt import get_stt, transcribe_audio

logger = logging.getLogger(__name__)

# TTS provider selection (same logic as fol/modules/output/tts.py)
# We import lazily to avoid circular deps.


class VoiceState(enum.Enum):
    """Voice engine state machine."""
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    SPEAKING = "speaking"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Wake Word Detector
# ---------------------------------------------------------------------------

# Default wake words (bilingual)
_DEFAULT_WAKE_WORDS = ("fol", "фол", "hey fol", "hey фол")


class WakeWordDetector:
    """Keyword-based wake word detection.

    Checks if a transcribed text contains a wake word. Simple, reliable,
    no ML dependencies. Can be subclassed for more sophisticated detection
    (e.g., Picovoice Porcupine, Snowboy).
    """

    def __init__(
        self,
        wake_words: tuple[str, ...] | None = None,
        case_sensitive: bool = False,
    ) -> None:
        self._wake_words = wake_words or _DEFAULT_WAKE_WORDS
        self._case_sensitive = case_sensitive

    def detect(self, text: str) -> bool:
        """Return True if ``text`` contains a wake word."""
        if not text:
            return False
        check = text if self._case_sensitive else text.lower()
        for word in self._wake_words:
            target = word if self._case_sensitive else word.lower()
            if target in check:
                return True
        return False

    def strip_wake_word(self, text: str) -> str:
        """Remove the wake word from the beginning of the text."""
        if not text:
            return text
        check = text if self._case_sensitive else text.lower()
        for word in self._wake_words:
            target = word if self._case_sensitive else word.lower()
            if check.startswith(target):
                remainder = text[len(target):].strip(" ,.!?")
                return remainder
        return text


# ---------------------------------------------------------------------------
# Background Listener
# ---------------------------------------------------------------------------

class BackgroundListener:
    """Continuous background listening mode.

    Records audio in chunks, detects silence, and transcribes on voice
    activity. Runs as an async task that can be started/stopped.

    Flow:
        start() → record_chunk() → detect_silence() → transcribe() → callback
    """

    def __init__(
        self,
        stt_provider: STTProvider,
        on_transcription: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        silence_threshold: float = 0.02,
        silence_duration: float = 1.5,
        chunk_duration: float = 3.0,
    ) -> None:
        self._stt = stt_provider
        self._on_transcription = on_transcription
        self._silence_threshold = silence_threshold
        self._silence_duration = silence_duration
        self._chunk_duration = chunk_duration
        self._running = False
        self._task: Any = None

    async def start(self) -> None:
        """Start background listening loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("Background listener started")

    async def stop(self) -> None:
        """Stop background listening."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None
        logger.info("Background listener stopped")

    async def _listen_loop(self) -> None:
        """Main listening loop — record chunks and transcribe."""
        while self._running:
            try:
                # Record a chunk
                text = await self._record_and_transcribe()
                if text and self._on_transcription:
                    await self._on_transcription(text)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Background listen chunk failed: %s", exc)
                await asyncio.sleep(0.5)

    async def _record_and_transcribe(self) -> str | None:
        """Record audio and transcribe if speech detected."""
        # Record to temp file
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            # Use sounddevice for recording
            recorded = await asyncio.to_thread(
                self._record_chunk, tmp_path, self._chunk_duration
            )
            if not recorded:
                return None

            # Transcribe
            text = await asyncio.to_thread(self._stt.transcribe, tmp_path)
            return text.strip() if text else None
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def _record_chunk(self, filepath: str, duration: float) -> bool:
        """Record a chunk of audio to a WAV file."""
        try:
            import sounddevice as sd
            import wave

            sample_rate = 16000
            channels = 1
            audio = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
            )
            sd.wait()

            # Simple voice activity detection — check if there's speech
            import numpy as np
            audio_array = np.frombuffer(audio.tobytes(), dtype=np.int16)
            rms = float(np.sqrt(np.mean(audio_array.astype(float) ** 2)))
            normalized_rms = rms / 32768.0  # Normalize to 0-1

            if normalized_rms < self._silence_threshold:
                return False  # Silence — skip transcription

            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(audio.tobytes())
            return True
        except ImportError:
            logger.warning("sounddevice/numpy not installed — background listener unavailable")
            return False
        except Exception as exc:
            logger.debug("Record chunk failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Voice Engine — unified interface
# ---------------------------------------------------------------------------

class VoiceEngine:
    """Unified voice engine — STT + TTS + Wake Word + Background Listening.

    The single entry point for all voice operations in FOL. Replaces the
    fragmented STT/TTS/VoiceAssistant setup with one coherent interface.
    """

    def __init__(
        self,
        stt_provider: STTProvider | None = None,
        tts_provider: Any | None = None,
        wake_words: tuple[str, ...] | None = None,
    ) -> None:
        # STT — default to local MLX Whisper
        self._stt = stt_provider or get_stt()

        # TTS — lazy import to avoid circular deps
        self._tts_provider = tts_provider
        self._tts: Any = None  # lazy init

        # Wake word
        self._wake_detector = WakeWordDetector(wake_words=wake_words)

        # Background listener
        self._background: BackgroundListener | None = None

        # State
        self._state = VoiceState.IDLE
        self._speaking = False

        logger.info(
            "VoiceEngine initialized (stt=%s, tts=lazy)",
            self._stt.name,
        )

    # -- TTS (lazy) -----------------------------------------------------------

    def _ensure_tts(self) -> Any:
        """Lazy-init TTS provider."""
        if self._tts is None:
            if self._tts_provider:
                self._tts = self._tts_provider
            else:
                try:
                    from modules.output.tts import get_tts
                    self._tts = get_tts()
                except Exception as exc:
                    logger.warning("TTS init failed: %s", exc)
                    self._tts = None
        return self._tts

    # -- State ----------------------------------------------------------------

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def is_listening(self) -> bool:
        return self._state == VoiceState.LISTENING

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def stt_available(self) -> bool:
        return self._stt.is_available

    @property
    def tts_available(self) -> bool:
        tts = self._ensure_tts()
        return tts is not None and getattr(tts, "is_available", False)

    def status(self) -> dict[str, Any]:
        """Human-readable status dict."""
        return {
            "state": self._state.value,
            "stt_provider": self._stt.name,
            "stt_available": self._stt.is_available,
            "tts_available": self.tts_available,
            "background_active": self._background is not None and self._background._running,
            "wake_words": list(self._wake_detector._wake_words),
        }

    # -- STT ------------------------------------------------------------------

    async def transcribe_file(self, audio_path: str) -> str:
        """Transcribe an audio file to text."""
        self._state = VoiceState.TRANSCRIBING
        try:
            text = await asyncio.to_thread(self._stt.transcribe, audio_path)
            return text.strip() if text else ""
        except Exception as exc:
            logger.error("Transcribe failed: %s", exc)
            return ""
        finally:
            self._state = VoiceState.IDLE

    async def transcribe_audio_data(self, audio_bytes: bytes, suffix: str = ".wav") -> str:
        """Transcribe raw audio bytes."""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
                tmp.write(audio_bytes)
            return await self.transcribe_file(tmp_path)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    # -- TTS ------------------------------------------------------------------

    async def speak(self, text: str) -> bool:
        """Speak text aloud. Returns True if speech started."""
        tts = self._ensure_tts()
        if tts is None or not getattr(tts, "is_available", False):
            logger.debug("TTS not available — skipping speech")
            return False

        self._speaking = True
        self._state = VoiceState.SPEAKING
        try:
            result = await tts.speak(text)
            return bool(result)
        except Exception as exc:
            logger.error("TTS speak failed: %s", exc)
            return False
        finally:
            self._speaking = False
            self._state = VoiceState.IDLE

    async def speak_and_wait(self, text: str) -> bool:
        """Speak text and wait for completion (blocking)."""
        return await self.speak(text)

    # -- Wake Word ------------------------------------------------------------

    def detect_wake_word(self, text: str) -> bool:
        """Check if text contains a wake word."""
        return self._wake_detector.detect(text)

    def strip_wake_word(self, text: str) -> str:
        """Remove wake word from text."""
        return self._wake_detector.strip_wake_word(text)

    # -- Background Listening -------------------------------------------------

    async def start_background(
        self,
        on_transcription: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Start continuous background listening."""
        if self._background and self._background._running:
            return

        self._background = BackgroundListener(
            stt_provider=self._stt,
            on_transcription=on_transcription,
        )
        await self._background.start()
        self._state = VoiceState.LISTENING

    async def stop_background(self) -> None:
        """Stop background listening."""
        if self._background:
            await self._background.stop()
            self._background = None
        self._state = VoiceState.IDLE

    # -- Cleanup --------------------------------------------------------------

    async def shutdown(self) -> None:
        """Shutdown all voice components."""
        await self.stop_background()
        self._state = VoiceState.IDLE
        logger.info("VoiceEngine shut down")


__all__ = [
    "VoiceEngine",
    "VoiceState",
    "WakeWordDetector",
    "BackgroundListener",
]
