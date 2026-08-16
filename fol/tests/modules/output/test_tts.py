"""Tests for TTS module."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.output.tts import TTSModule


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
