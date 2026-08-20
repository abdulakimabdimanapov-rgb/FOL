"""Tests for LLM Engine (API providers only — local LLMs removed)."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.llm.engine import LLMEngine


@pytest.mark.asyncio
async def test_engine_initialization():
    """Engine should initialize without errors even with no API keys."""
    engine = LLMEngine(config={"llm_backend": "openrouter"})
    await engine.initialize()
    # No keys configured → no backends registered, but no crash
    assert engine.available_backends == []
    await engine.shutdown()


@pytest.mark.asyncio
async def test_openrouter_backend_registered_with_base_url():
    """Engine registers the OpenRouter backend (OpenAI-compatible endpoint)
    when an OpenRouter API key is configured."""
    engine = LLMEngine(config={
        "llm_backend": "openrouter",
        "openrouter_api_key": "sk-or-v1-test",
        "openrouter_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    })
    with patch("modules.llm.engine.OpenAIBackend") as mock_openai:
        or_backend = MagicMock()
        or_backend.initialize = AsyncMock()
        or_backend.shutdown = AsyncMock()
        mock_openai.return_value = or_backend

        await engine.initialize()
        assert "openrouter" in engine.available_backends
        # base_url must point at OpenRouter's OpenAI-compatible endpoint
        _, kwargs = mock_openai.call_args
        assert kwargs.get("base_url") == "https://openrouter.ai/api/v1"
        assert kwargs.get("model") == "nvidia/nemotron-3-ultra-550b-a55b:free"
        await engine.shutdown()


def test_fallback_order_primary_openrouter_first():
    """With openrouter primary, the fallback chain tries it first, then
    openai / anthropic — local MLX is gone."""
    engine = LLMEngine(config={"llm_backend": "openrouter"})
    assert engine._fallback_order[0] == "openrouter"
    assert "mlx" not in engine._fallback_order
    assert "openai" in engine._fallback_order
    assert "anthropic" in engine._fallback_order


def test_mlx_backend_never_accepted_as_primary():
    """Requesting 'mlx' as backend falls back to a cloud default — local LLMs
    are removed from FOL by policy."""
    engine = LLMEngine(config={"llm_backend": "mlx"})
    assert engine._primary_backend == "openrouter"
    assert "mlx" not in engine._fallback_order


@pytest.mark.asyncio
async def test_openai_backend_accepts_base_url():
    """OpenAIBackend must pass base_url through to the OpenAI client so
    OpenRouter (an OpenAI-compatible endpoint) can be used."""
    from modules.llm.backends.openai_backend import OPENROUTER_BASE_URL, OpenAIBackend

    backend = OpenAIBackend(
        api_key="sk-or-v1-test",
        model="nvidia/nemotron-3-ultra-550b-a55b:free",
        base_url=OPENROUTER_BASE_URL,
    )
    assert backend._base_url == OPENROUTER_BASE_URL

    with patch("modules.llm.backends.openai_backend.openai") as mock_openai:
        mock_client = MagicMock()
        mock_openai.AsyncOpenAI.return_value = mock_client

        await backend.initialize()

        mock_openai.AsyncOpenAI.assert_called_once_with(
            api_key="sk-or-v1-test", base_url=OPENROUTER_BASE_URL
        )


@pytest.mark.asyncio
async def test_generate_without_model():
    """Without a configured backend, generate returns a friendly fallback."""
    engine = LLMEngine(config={"llm_backend": "openrouter"})
    await engine.initialize()
    response = await engine.generate("hello")
    assert isinstance(response, str)
    assert "All LLM backends are unavailable" in response
    await engine.shutdown()


@pytest.mark.asyncio
async def test_generate_with_mocked_response():
    """Should return response from the API backend when available."""
    from modules.llm.base import LLMResponse

    engine = LLMEngine(config={
        "llm_backend": "openrouter",
        "openrouter_api_key": "sk-or-v1-test",
    })
    with patch("modules.llm.engine.OpenAIBackend") as mock_openai:
        mock_instance = MagicMock()
        mock_instance.initialize = AsyncMock()
        mock_instance.shutdown = AsyncMock()
        mock_instance.generate = AsyncMock(return_value=LLMResponse(text="Hello, sir!", model="test"))
        mock_openai.return_value = mock_instance
        await engine.initialize()

        response = await engine.generate("hello")
        assert response == "Hello, sir!"
        await engine.shutdown()


@pytest.mark.asyncio
async def test_build_messages():
    """Should build correct message list."""
    engine = LLMEngine()
    messages = engine._build_messages("hello", "context here", "custom prompt")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "custom prompt" in messages[0]["content"]
    assert "context here" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "hello"
