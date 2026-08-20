"""Tests for VoiceEngine, WakeWordDetector, and BackgroundListener."""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.input.voice.engine import (
    BackgroundListener,
    VoiceEngine,
    VoiceState,
    WakeWordDetector,
)
from modules.input.voice.interface import STTProvider


# ---------------------------------------------------------------------------
# Mock STT Provider
# ---------------------------------------------------------------------------

class MockSTTProvider(STTProvider):
    """Test STT provider that returns configured text."""

    name = "mock_stt"

    def __init__(self, text: str = "hello world") -> None:
        self._text = text
        self._call_count = 0

    @property
    def is_available(self) -> bool:
        return True

    def transcribe(self, audio_path: str) -> str:
        self._call_count += 1
        return self._text


class UnavailableSTTProvider(STTProvider):
    """Test STT provider that is never available."""

    name = "unavailable_stt"

    @property
    def is_available(self) -> bool:
        return False

    def transcribe(self, audio_path: str) -> str:
        return ""


# ---------------------------------------------------------------------------
# WakeWordDetector Tests
# ---------------------------------------------------------------------------

class TestWakeWordDetector:
    def test_detect_default_wake_words(self):
        det = WakeWordDetector()
        assert det.detect("fol, open safari") is True
        assert det.detect("фол, открой safari") is True
        assert det.detect("hey fol what time") is True
        assert det.detect("hey фол какой час") is True

    def test_detect_no_wake_word(self):
        det = WakeWordDetector()
        assert det.detect("open safari") is False
        assert det.detect("what time is it") is False
        assert det.detect("") is False
        assert det.detect("beautiful day") is False

    def test_detect_custom_wake_words(self):
        det = WakeWordDetector(wake_words=("computer", "jarvis"))
        assert det.detect("computer open mail") is True
        assert det.detect("jarvis what time") is True
        assert det.detect("fol open mail") is False

    def test_detect_case_insensitive(self):
        det = WakeWordDetector()
        assert det.detect("FOL open safari") is True
        assert det.detect("Fol, какой час") is True

    def test_detect_case_sensitive(self):
        det = WakeWordDetector(case_sensitive=True)
        assert det.detect("FOL open safari") is False  # "FOL" != "fol"
        assert det.detect("fol open safari") is True

    def test_strip_wake_word(self):
        det = WakeWordDetector()
        assert det.strip_wake_word("fol open safari") == "open safari"
        assert det.strip_wake_word("фол какой час") == "какой час"
        assert det.strip_wake_word("hey fol what time") == "what time"

    def test_strip_wake_word_no_match(self):
        det = WakeWordDetector()
        assert det.strip_wake_word("open safari") == "open safari"

    def test_strip_wake_word_empty(self):
        det = WakeWordDetector()
        assert det.strip_wake_word("") == ""
        assert det.strip_wake_word("fol") == ""


# ---------------------------------------------------------------------------
# VoiceEngine Tests
# ---------------------------------------------------------------------------

class TestVoiceEngine:
    def test_init_default(self):
        stt = MockSTTProvider()
        engine = VoiceEngine(stt_provider=stt)
        assert engine.state == VoiceState.IDLE
        assert engine.stt_available is True
        assert engine.is_listening is False
        assert engine.is_speaking is False

    def test_init_unavailable_stt(self):
        stt = UnavailableSTTProvider()
        engine = VoiceEngine(stt_provider=stt)
        assert engine.stt_available is False

    @pytest.mark.asyncio
    async def test_transcribe_file(self):
        stt = MockSTTProvider(text="привет мир")
        engine = VoiceEngine(stt_provider=stt)

        # Create a temp file for transcription
        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake audio data")
            tmp = f.name

        try:
            result = await engine.transcribe_file(tmp)
            assert result == "привет мир"
            assert stt._call_count == 1
        finally:
            Path(tmp).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_transcribe_file_empty(self):
        stt = MockSTTProvider(text="")
        engine = VoiceEngine(stt_provider=stt)

        import tempfile
        from pathlib import Path
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake audio data")
            tmp = f.name

        try:
            result = await engine.transcribe_file(tmp)
            assert result == ""
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_wake_word_detection(self):
        stt = MockSTTProvider()
        engine = VoiceEngine(stt_provider=stt)
        assert engine.detect_wake_word("fol open safari") is True
        assert engine.detect_wake_word("open safari") is False

    def test_wake_word_strip(self):
        stt = MockSTTProvider()
        engine = VoiceEngine(stt_provider=stt)
        assert engine.strip_wake_word("fol open safari") == "open safari"

    def test_status(self):
        stt = MockSTTProvider()
        engine = VoiceEngine(stt_provider=stt)
        status = engine.status()
        assert status["state"] == "idle"
        assert status["stt_provider"] == "mock_stt"
        assert status["stt_available"] is True
        assert status["background_active"] is False
        assert "wake_words" in status

    @pytest.mark.asyncio
    async def test_shutdown(self):
        stt = MockSTTProvider()
        engine = VoiceEngine(stt_provider=stt)
        await engine.shutdown()
        assert engine.state == VoiceState.IDLE

    @pytest.mark.asyncio
    async def test_speak_no_tts(self):
        """speak() returns False when TTS is not available."""
        stt = MockSTTProvider()
        # Create engine with explicitly unavailable TTS
        engine = VoiceEngine(stt_provider=stt)
        # Force TTS to be None by setting a mock that's not available
        class MockUnavailableTTS:
            is_available = False
            async def speak(self, text):
                return False
        engine._tts = MockUnavailableTTS()
        result = await engine.speak("Hello world")
        assert result is False


# ---------------------------------------------------------------------------
# BackgroundListener Tests
# ---------------------------------------------------------------------------

class TestBackgroundListener:
    def test_init(self):
        stt = MockSTTProvider()
        listener = BackgroundListener(stt_provider=stt)
        assert listener._running is False

    @pytest.mark.asyncio
    async def test_start_stop(self):
        stt = MockSTTProvider()
        listener = BackgroundListener(stt_provider=stt)
        await listener.start()
        assert listener._running is True
        await listener.stop()
        assert listener._running is False

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        stt = MockSTTProvider()
        listener = BackgroundListener(stt_provider=stt)
        await listener.stop()  # Should not raise
        assert listener._running is False

    @pytest.mark.asyncio
    async def test_double_start(self):
        stt = MockSTTProvider()
        listener = BackgroundListener(stt_provider=stt)
        await listener.start()
        await listener.start()  # Should not raise
        assert listener._running is True
        await listener.stop()
