"""OpenAI backend — cloud LLM via OpenAI API (also OpenRouter-compatible)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.llm.base import AbstractLLMBackend, LLMResponse

logger = logging.getLogger(__name__)

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# OpenRouter exposes an OpenAI-compatible API.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenAIBackend(AbstractLLMBackend):
    """Cloud LLM via OpenAI API (or any OpenAI-compatible endpoint such as
    OpenRouter, via ``base_url``)."""

    name = "openai"

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini", base_url: str | None = None) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._client: Any = None
        self._is_ready = False

    async def initialize(self) -> None:
        if not HAS_OPENAI:
            logger.warning("openai package not available")
            return
        if not self._api_key:
            logger.warning("OpenAI API key not set")
            return

        kwargs: dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._is_ready = True
        logger.info("OpenAI backend initialized", model=self._model)

    async def shutdown(self) -> None:
        if self._client:
            await self._client.close()
        self._client = None
        self._is_ready = False

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        if not self._is_ready:
            return LLMResponse(text="[OpenAI not configured]", model=self._model)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = response.choices[0].message.content or ""
            return LLMResponse(
                text=text.strip(),
                model=self._model,
                tokens_used=response.usage.total_tokens if response.usage else 0,
                finish_reason=response.choices[0].finish_reason or "stop",
            )
        except Exception as exc:
            logger.error("OpenAI generation failed: %s", exc)
            return LLMResponse(text=f"[OpenAI error: {exc}]", model=self._model)
