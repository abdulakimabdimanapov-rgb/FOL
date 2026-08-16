"""Regression tests for output channels (modules/output/).

Verifies the canonical output boundary: TTS via ``say`` and Telegram Bot
API, both degrading gracefully when unconfigured / unavailable.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.output.base import OutputChannel
from modules.output.telegram import TelegramBot, get_telegram_bot
from modules.output.tts import TTSModule


class TestTTSModule:
    async def test_unavailable_when_say_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr("shutil.which", lambda _name: None)
        tts = TTSModule()
        assert tts.is_available is False
        assert await tts.send("hello") is False

    async def test_send_returns_false_for_empty_text(self):
        tts = TTSModule()
        tts._probed = True
        assert await tts.send("") is False

    async def test_send_spawns_say(self):
        tts = TTSModule()
        tts._probed = True
        with patch.object(asyncio, "create_subprocess_exec", new_callable=AsyncMock) as spawn:
            assert await tts.send("Hello, sir") is True
        args = spawn.call_args.args
        assert args[0] == "say"
        assert args[-1] == "Hello, sir"

    async def test_send_handles_spawn_failure(self):
        tts = TTSModule()
        tts._probed = True
        with patch.object(asyncio, "create_subprocess_exec", side_effect=OSError("boom")):
            assert await tts.send("hi") is False

    async def test_implements_output_channel(self):
        assert isinstance(TTSModule(), OutputChannel)


class TestTelegramBot:
    def test_not_configured_by_default(self):
        bot = TelegramBot()
        assert bot.is_available is False
        assert bot._default_chat_id == ""

    def test_configure_enables(self):
        bot = TelegramBot()
        bot.configure("token123", "chat-1")
        assert bot.is_available is True
        assert bot._default_chat_id == "chat-1"

    async def test_send_message_noop_when_not_configured(self):
        bot = TelegramBot()
        assert await bot.send_message("chat-1", "hello") is False

    async def test_send_message_success(self):
        bot = TelegramBot()
        bot.configure("token123", "chat-1")

        response = MagicMock()
        response.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            assert await bot.send_message("chat-1", "hello") is True

        url = urlopen.call_args.args[0].full_url
        assert "token123" in url
        body = json.loads(urlopen.call_args.args[0].data)
        assert body == {"chat_id": "chat-1", "text": "hello"}

    async def test_send_message_failure(self):
        bot = TelegramBot()
        bot.configure("token123", "chat-1")
        with patch("urllib.request.urlopen", side_effect=OSError("network")):
            assert await bot.send_message("chat-1", "hello") is False

    async def test_send_uses_default_chat(self):
        bot = TelegramBot()
        bot.configure("token123", "chat-1")
        response = MagicMock()
        response.read.return_value = json.dumps({"ok": True}).encode("utf-8")
        with patch("urllib.request.urlopen", return_value=response):
            assert await bot.send("hello") is True

    def test_get_telegram_bot_is_singleton(self):
        assert get_telegram_bot() is get_telegram_bot()
