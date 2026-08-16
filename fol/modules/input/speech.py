"""Speech module — TTS and STT for FOL.

Handles:
- Text-to-Speech (TTS) using macOS 'say' command
- Speech-to-Text (STT) using speech_recognition + sounddevice
- Voice activity detection (VAD)
- Wake word detection
- Continuous voice mode
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import wave
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
WAKE_WORDS = ["fol", "фол", "hey fol", "hey фол"]

try:
    import speech_recognition as sr
    HAS_SPEECH_RECOGNITION = True
except ImportError:
    HAS_SPEECH_RECOGNITION = False

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False


class SoundDeviceMicrophone:
    """Custom microphone using sounddevice instead of pyaudio."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS) -> None:
        self.sample_rate = sample_rate
        self.channels = channels

    def __enter__(self) -> SoundDeviceMicrophone:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def record_audio(self, duration: float = 5.0) -> Any:
        """Record audio from microphone."""
        if not HAS_SOUNDDEVICE:
            raise RuntimeError("sounddevice not installed")
        audio = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
        )
        sd.wait()
        return sr.AudioData(audio.tobytes(), self.sample_rate, 2)

    def record_to_wav(self, filepath: str, duration: float = 5.0) -> bool:
        if not HAS_SOUNDDEVICE:
            return False
        try:
            audio = sd.rec(
                int(duration * self.sample_rate),
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
            )
            sd.wait()
            with wave.open(filepath, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio.tobytes())
            return True
        except Exception as exc:
            logger.error("Recording failed: %s", exc)
            return False


class TTS:
    """Text-to-Speech using macOS 'say' command."""

    # JARVIS-like voice: British English (Daniel), slow & deliberate
    def __init__(self, voice: str = "Daniel", rate: int = 150) -> None:
        self._voice = voice
        self._rate = rate
        self._enabled = True

    def speak(self, text: str) -> bool:
        """Speak text aloud."""
        if not self._enabled or not text:
            return False
        try:
            cmd = ["say"]
            if self._voice:
                cmd.extend(["-v", self._voice])
            cmd.extend(["-r", str(self._rate)])
            cmd.append(text)
            subprocess.run(cmd, check=True, timeout=30)
            return True
        except Exception as exc:
            logger.error("TTS error: %s", exc)
            return False

    async def speak_async(self, text: str) -> bool:
        return await asyncio.to_thread(self.speak, text)

    def set_voice(self, voice: str) -> None:
        self._voice = voice

    def set_rate(self, rate: int) -> None:
        self._rate = rate

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def list_voices(self) -> list[str]:
        try:
            result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=5)
            return [line.split()[0] for line in result.stdout.strip().split("\n") if line.strip()]
        except Exception:
            return []

    @property
    def is_available(self) -> bool:
        try:
            result = subprocess.run(["which", "say"], capture_output=True, timeout=5)
            return result.returncode == 0
        except Exception:
            return False


class STT:
    """Speech-to-Text using speech_recognition + sounddevice."""

    def __init__(self, language: str = "ru-RU") -> None:
        self._language = language
        self._recognizer: Any = None
        self._microphone: Any = None
        self._enabled = False

        if HAS_SPEECH_RECOGNITION:
            self._recognizer = sr.Recognizer()
            # Energy threshold for silence detection
            self._recognizer.energy_threshold = 300
            self._recognizer.dynamic_energy_threshold = True

            if HAS_SOUNDDEVICE:
                try:
                    self._microphone = SoundDeviceMicrophone()
                    self._enabled = True
                    logger.info("STT initialized with sounddevice")
                except Exception as exc:
                    logger.warning("Failed to init sounddevice: %s", exc)
            else:
                try:
                    self._microphone = sr.Microphone()
                    self._enabled = True
                    logger.info("STT initialized with pyaudio")
                except Exception as exc:
                    logger.warning("Failed to init pyaudio: %s", exc)

    def listen(self, timeout: float = 5.0, phrase_limit: float = 10.0) -> str | None:
        """Listen to microphone and transcribe speech."""
        if not self._enabled or not self._recognizer:
            return None
        try:
            if isinstance(self._microphone, SoundDeviceMicrophone):
                audio_data = self._microphone.record_audio(duration=min(phrase_limit, 7.0))
            else:
                with self._microphone as source:
                    self._recognizer.adjust_for_ambient_noise(source, duration=0.3)
                with self._microphone as source:
                    audio_data = self._recognizer.listen(
                        source, timeout=timeout, phrase_time_limit=phrase_limit
                    )

            # Try Google Speech Recognition (free, works well for RU/EN)
            try:
                text = self._recognizer.recognize_google(audio_data, language=self._language)
                logger.info("STT recognized: %s", text)
                return text.strip()
            except sr.UnknownValueError:
                logger.debug("Could not understand audio")
                return None
            except sr.RequestError as exc:
                logger.warning("Google STT error: %s", exc)
                return None

        except sr.WaitTimeoutError:
            return None
        except Exception as exc:
            logger.error("STT error: %s", exc)
            return None

    async def listen_async(self, timeout: float = 5.0, phrase_limit: float = 10.0) -> str | None:
        return await asyncio.to_thread(self.listen, timeout, phrase_limit)

    def record_to_file(self, filepath: str, duration: float = 5.0) -> bool:
        if isinstance(self._microphone, SoundDeviceMicrophone):
            return self._microphone.record_to_wav(filepath, duration)
        return False

    def set_language(self, language: str) -> None:
        self._language = language

    @property
    def is_available(self) -> bool:
        return self._enabled


class VoiceAssistant:
    """Combined voice interface for FOL.

    Supports:
    - One-shot listen: listen_once()
    - Voice mode: continuous listen → process → speak loop
    - Wake word: listen_for_wake_word()
    """

    def __init__(self, tts: TTS | None = None, stt: STT | None = None) -> None:
        self.tts = tts or TTS()
        self.stt = stt or STT()
        self._is_listening = False
        self._voice_mode = False

    async def say(self, text: str) -> bool:
        """Speak text aloud."""
        return await self.tts.speak_async(text)

    async def listen_once(self, timeout: float = 7.0, phrase_limit: float = 10.0) -> str | None:
        """Listen for a single utterance and return text."""
        return await self.stt.listen_async(timeout=timeout, phrase_limit=phrase_limit)

    async def listen_for_wake_word(self, timeout: float = 10.0) -> bool:
        """Listen for the wake word."""
        text = await self.stt.listen_async(timeout=timeout, phrase_limit=3.0)
        if text:
            text_lower = text.lower()
            for wake in WAKE_WORDS:
                if wake in text_lower:
                    return True
        return False

    async def voice_mode(
        self,
        process_fn: Callable[[str], Coroutine[Any, Any, str]],
        on_listen: Callable[[], Coroutine[Any, Any, None]] | None = None,
        on_think: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """Continuous voice conversation mode.

        Flow: listen → process → speak → listen → ...
        Say "stop" or "выход" to exit.

        Args:
            process_fn: async function that takes user text and returns FOL response
            on_listen: optional callback when listening starts
            on_think: optional callback when processing starts
        """
        self._voice_mode = True
        self._is_listening = True

        await self.say("Voice mode activated. I'm listening, sir.")

        while self._voice_mode:
            try:
                if on_listen:
                    await on_listen()

                # Listen for user speech
                text = await self.stt.listen_async(timeout=8.0, phrase_limit=12.0)

                if not text:
                    # No speech detected, continue listening
                    continue

                text_lower = text.lower().strip()
                logger.info("Voice input: %s", text)

                # Check for exit commands
                if text_lower in ("stop", "exit", "quit", "выход", "выключи голос", "стоп"):
                    await self.say("Voice mode deactivated. Goodbye, sir.")
                    break

                # Process the command
                if on_think:
                    await on_think()

                response = await process_fn(text)

                # Speak the response
                if response and response != "__SHUTDOWN__":
                    await self.say(response)

                if response == "__SHUTDOWN__":
                    break

            except KeyboardInterrupt:
                await self.say("Shutting down, sir.")
                break
            except Exception as exc:
                logger.error("Voice mode error: %s", exc)
                await self.say("Sorry, sir. Something went wrong.")
                await asyncio.sleep(1)

        self._voice_mode = False
        self._is_listening = False
        logger.info("Voice mode stopped")

    def stop_voice_mode(self) -> None:
        """Stop voice mode."""
        self._voice_mode = False
        self._is_listening = False

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    @property
    def is_voice_mode(self) -> bool:
        return self._voice_mode

    @property
    def status(self) -> dict[str, Any]:
        return {
            "tts_available": self.tts.is_available,
            "stt_available": self.stt.is_available,
            "is_listening": self._is_listening,
            "voice_mode": self._voice_mode,
            "voice": self.tts._voice or "default",
            "language": self.stt._language,
        }
