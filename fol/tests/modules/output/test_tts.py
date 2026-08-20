"""Tests for the TTS provider architecture.

Covers the canonical ``TTSModule`` OutputChannel contract (initialize/send/
shutdown) and the provider layer: selection (default macOS say, opt-in
ElevenLabs), fallback when cloud credentials are missing, missing-key and
unavailable-provider handling.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.output.tts import (
    ElevenLabsProvider,
    MacOSSayProvider,
    TTSModule,
    available_providers,
    get_tts,
)


# ---------------------------------------------------------------------------
# Canonical TTSModule contract (unchanged behavior)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tts_initialize():
    """TTS module should initialize."""
    tts = TTSModule()
    await tts.initialize()
    assert tts is not None


@pytest.mark.asyncio
async def test_tts_send():
    """TTS module should send text for speech."""
    tts = TTSModule()
    await tts.initialize()
    result = await tts.send("Hello, world!")
    # May fail without audio device, but should not crash
    assert result is None or isinstance(result, bool)


@pytest.mark.asyncio
async def test_tts_shutdown():
    """TTS module should shutdown cleanly."""
    tts = TTSModule()
    await tts.initialize()
    await tts.shutdown()


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

class TestTTSSelection:
    def test_default_is_macos_say(self, monkeypatch):
        monkeypatch.delenv("FOL_TTS_PROVIDER", raising=False)
        assert isinstance(get_tts(), MacOSSayProvider)

    def test_env_say(self, monkeypatch):
        monkeypatch.setenv("FOL_TTS_PROVIDER", "say")
        assert isinstance(get_tts(), MacOSSayProvider)

    def test_cloud_without_key_falls_back_to_say(self, monkeypatch):
        monkeypatch.setenv("FOL_TTS_PROVIDER", "elevenlabs")
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        assert isinstance(get_tts(), MacOSSayProvider)

    def test_cloud_with_key_selected(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/afplay" if name == "afplay" else None)
        assert isinstance(get_tts("elevenlabs"), ElevenLabsProvider)

    def test_unknown_falls_back_to_say(self, monkeypatch):
        monkeypatch.setenv("FOL_TTS_PROVIDER", "banana")
        assert isinstance(get_tts(), MacOSSayProvider)

    def test_available_providers(self, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        assert "say" in available_providers()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class TestMacOSSayProvider:
    def test_unavailable_without_say(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        provider = MacOSSayProvider()
        assert provider.is_available is False

    @pytest.mark.asyncio
    async def test_speak_empty_text_is_noop(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/say")
        provider = MacOSSayProvider()
        assert await provider.speak("") is False


class TestElevenLabsProvider:
    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        provider = ElevenLabsProvider(api_key="")
        assert provider.is_available is False

    def test_available_with_key(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/afplay" if name == "afplay" else None)
        provider = ElevenLabsProvider(api_key="sk-test")
        assert provider.is_available is True

    @pytest.mark.asyncio
    async def test_speak_failure_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/afplay" if name == "afplay" else None)
        import urllib.error

        def _boom(*a, **kw):
            raise urllib.error.HTTPError("url", 401, "unauthorized", {}, None)

        with patch("urllib.request.urlopen", side_effect=_boom):
            provider = ElevenLabsProvider(api_key="sk-test")
            assert await provider.speak("hello") is False
