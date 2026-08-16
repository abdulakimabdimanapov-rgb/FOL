"""Anthropic backend — Claude via Anthropic API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.llm.base import AbstractLLMBackend, LLMResponse

logger = logging.getLogger(__name__)

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


class AnthropicBackend(AbstractLLMBackend):
    """Cloud LLM via Anthropic API (Claude)."""

    name = "anthropic"

    def __init__(self, api_key: str = "", model: str = "claude-3-5-sonnet-20241022") -> None:
        self._api_key = api_key
        self._model = model
        self._client: Any = None
        self._is_ready = False

    async def initialize(self) -> None:
        if not HAS_ANTHROPIC:
            logger.warning("anthropic package not available")
            return
        if not self._api_key:
            logger.warning("Anthropic API key not set")
            return

        self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        self._is_ready = True
        logger.info("Anthropic backend initialized", model=self._model)

    async def shutdown(self) -> None:
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
            return LLMResponse(text="[Anthropic not configured]", model=self._model)

        try:
            # Anthropic expects system as separate param
            system_msg = ""
            user_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_messages.append(m)

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_msg,
                messages=user_messages,
            )
            text = response.content[0].text if response.content else ""
            return LLMResponse(
                text=text.strip(),
                model=self._model,
                tokens_used=(response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0,
                finish_reason=response.stop_reason or "stop",
            )
        except Exception as exc:
            logger.error("Anthropic generation failed", error=str(exc))
            return LLMResponse(text=f"[Anthropic error: {exc}]", model=self._model)
