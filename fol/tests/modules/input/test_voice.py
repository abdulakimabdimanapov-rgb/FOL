"""Tests for the unified STT provider architecture.

Covers: provider selection (default local, opt-in cloud), fallback when cloud
credentials are missing, missing dependency handling, malformed/empty audio,
and the canonical ``/api/stt`` response contract.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from modules.input.voice import get_stt, transcribe_audio
from modules.input.voice.providers import ElevenLabsSTT, MLXWhisperSTT


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

class TestSTTSelection:
    def test_default_is_local(self, monkeypatch):
        monkeypatch.delenv("FOL_STT_PROVIDER", raising=False)
        assert isinstance(get_stt(), MLXWhisperSTT)

    def test_env_local(self, monkeypatch):
        monkeypatch.setenv("FOL_STT_PROVIDER", "mlx_whisper")
        assert isinstance(get_stt(), MLXWhisperSTT)

    def test_cloud_without_key_falls_back_to_local(self, monkeypatch):
        monkeypatch.setenv("FOL_STT_PROVIDER", "elevenlabs")
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        assert isinstance(get_stt(), MLXWhisperSTT)

    def test_cloud_with_key_selected(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-123")
        provider = get_stt("elevenlabs")
        assert isinstance(provider, ElevenLabsSTT)

    def test_unknown_provider_falls_back_to_local(self, monkeypatch):
        monkeypatch.setenv("FOL_STT_PROVIDER", "banana")
        assert isinstance(get_stt(), MLXWhisperSTT)

    def test_available_providers(self, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        providers = __import__("modules.input.voice", fromlist=["available_providers"]).available_providers()
        assert "mlx_whisper" in providers


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class TestMLXWhisperSTT:
    def test_transcribe_without_mlx_whisper_returns_empty(self, monkeypatch):
        # Force the dependency to look missing.
        monkeypatch.setattr("modules.input.voice.providers.mlx_whisper.HAS_MLX_WHISPER", False)
        monkeypatch.setattr("modules.input.voice.providers.mlx_whisper.HAS_SPEECH_RECOGNITION", False)
        provider = MLXWhisperSTT()
        assert provider.is_available is False
        assert provider.transcribe("/tmp/nope.wav") == ""

    def test_transcribe_parses_mlx_result(self, monkeypatch):
        monkeypatch.setattr("modules.input.voice.providers.mlx_whisper.HAS_MLX_WHISPER", True)
        monkeypatch.setattr(
            "modules.input.voice.providers.mlx_whisper.MLXWhisperSTT._transcribe_mlx",
            lambda self, audio_path: "  Hello world  ",
        )
        provider = MLXWhisperSTT()
        assert provider.transcribe("/tmp/x.wav") == "Hello world"

    def test_missing_dependency_reported(self, monkeypatch):
        monkeypatch.setattr("modules.input.voice.providers.mlx_whisper.HAS_MLX_WHISPER", False)
        provider = MLXWhisperSTT()
        assert provider.missing_dependency == "mlx-whisper"


class TestElevenLabsSTT:
    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        provider = ElevenLabsSTT(api_key="")
        assert provider.is_available is False
        assert provider.transcribe("/tmp/x.wav") == ""

    def test_available_with_key(self):
        provider = ElevenLabsSTT(api_key="sk-test")
        assert provider.is_available is True

    def test_transcribe_success(self, tmp_path):
        wav = tmp_path / "in.wav"
        wav.write_bytes(b"RIFF....WAVEfmt ")

        class _Resp:
            def read(self):
                return json.dumps({"text": "привет мир"}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with patch("urllib.request.urlopen", return_value=_Resp()):
            provider = ElevenLabsSTT(api_key="sk-test")
            assert provider.transcribe(str(wav)) == "привет мир"

    def test_transcribe_http_error(self, tmp_path, monkeypatch):
        wav = tmp_path / "in.wav"
        wav.write_bytes(b"data")

        class _Err(Exception):
            code = 401

            def read(self):
                return b"unauthorized"

        def _boom(*a, **kw):
            raise _Err()

        with patch("urllib.request.urlopen", side_effect=_boom):
            provider = ElevenLabsSTT(api_key="sk-test")
            assert provider.transcribe(str(wav)) == ""


# ---------------------------------------------------------------------------
# Unified entry (the /api/stt contract)
# ---------------------------------------------------------------------------

class TestTranscribeAudio:
    def test_success_returns_text(self, monkeypatch, tmp_path):
        monkeypatch.setattr("modules.input.voice.stt.get_stt", lambda: MLXWhisperSTT())
        monkeypatch.setattr("modules.input.voice.providers.mlx_whisper.HAS_MLX_WHISPER", True)
        monkeypatch.setattr(
            "modules.input.voice.providers.mlx_whisper.MLXWhisperSTT._transcribe_mlx",
            lambda self, audio_path: "ok",
        )
        result = transcribe_audio(str(tmp_path / "a.wav"))
        assert result == {"text": "ok"}

    def test_failure_returns_local_stt_unavailable(self, monkeypatch, tmp_path):
        monkeypatch.setattr("modules.input.voice.providers.mlx_whisper.HAS_MLX_WHISPER", False)
        monkeypatch.setattr("modules.input.voice.providers.mlx_whisper.HAS_SPEECH_RECOGNITION", False)
        result = transcribe_audio(str(tmp_path / "a.wav"))
        assert result["text"] == ""
        assert result["error"] == "local_stt_unavailable"
        assert "mlx-whisper" in result["detail"]
