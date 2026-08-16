"""Google Gemini backend for FOL LLM engine."""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from modules.llm.base import AbstractLLMBackend

logger = logging.getLogger(__name__)


class GeminiBackend(AbstractLLMBackend):
    """Google Gemini API backend."""

    name = "gemini"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._api_key = self._config.get("gemini_api_key", "")
        self._model = self._config.get("gemini_model", "gemini-2.0-flash")
        self._client = None

    async def initialize(self) -> None:
        """Initialize the Gemini client."""
        if not self._api_key:
            logger.warning("Gemini API key not configured")
            return
        try:
            import google.generativeai as genai
            genai.configure(api_key=self._api_key)
            self._client = genai.GenerativeModel(self._model)
            logger.info("Gemini backend initialized", model=self._model)
        except ImportError:
            logger.warning("google-generativeai not installed, Gemini backend unavailable")
        except Exception as exc:
            logger.error("Failed to initialize Gemini", error=str(exc))

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> str:
        """Generate a response using Gemini."""
        if self._client is None:
            raise RuntimeError("Gemini backend not initialized")

        try:
            # Convert messages to Gemini format
            prompt = self._messages_to_prompt(messages)
            response = await self._client.generate_content_async(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
            )
            return response.text or ""
        except Exception as exc:
            logger.error("Gemini generation failed", error=str(exc))
            raise

    async def generate_stream(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a response from Gemini."""
        if self._client is None:
            raise RuntimeError("Gemini backend not initialized")

        try:
            prompt = self._messages_to_prompt(messages)
            response = await self._client.generate_content_async(
                prompt,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                },
                stream=True,
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            logger.error("Gemini streaming failed", error=str(exc))
            raise

    def _messages_to_prompt(self, messages: list[dict[str, str]]) -> str:
        """Convert message list to a single prompt string."""
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"Instructions: {content}")
            elif role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
        return "\n\n".join(parts)

    @property
    def is_available(self) -> bool:
        """Check if the backend is available."""
        return self._client is not None and bool(self._api_key)
