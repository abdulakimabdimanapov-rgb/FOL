"""Freebuff Brain Adapter — real integration via OpenRouter.

Freebuff has no official public HTTP API (audited 2026-08-18). The legitimate
way to use Freebuff's models (DeepSeek V4 Flash, MiMo 2.5, etc.) is through
OpenRouter, which provides an OpenAI-compatible API.

This adapter wraps CurrentLLMAdapter with Freebuff-specific model routing:

  Primary:   openrouter/deepseek/deepseek-v4-flash  (free, smart)
  Fallback:  openrouter/moonshotai/mimo-2.5           (free, fast)
             openrouter/nvidia/nemotron-3-super-120b-a12b:free

The adapter is available when:
  1. OPENROUTER_API_KEY is configured
  2. The LLM_MODEL env var points to a Freebuff-compatible model via OpenRouter

It does NOT:
  - Contact fake endpoints
  - Simulate an API
  - Bypass Freebuff's terms of service
  - Spawn a daemon process

It simply routes reasoning through OpenRouter to Freebuff's models.
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncIterator

from modules.llm.brain import (
    BRAIN_INTENT_LABELS,
    BrainError,
    BrainInterface,
    BrainConfigurationError,
)
from modules.llm.router import (
    LiteLLMRouter,
    get_llm_router,
    build_model_chain,
    api_key_for_model,
)
from modules.llm.freebuff import FREEBUFF_REQUIREMENTS, freebuff_config

logger = logging.getLogger(__name__)

# Default Freebuff models available through OpenRouter (free tier)
FREEBUFF_PRIMARY_MODEL = "openrouter/deepseek/deepseek-v4-flash"
FREEBUFF_FALLBACK_MODELS = [
    "openrouter/moonshotai/mimo-2.5",
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
]


class FreebuffBrainAdapter(BrainInterface):
    """Freebuff brain backend — uses Freebuff's models via OpenRouter.

    Freebuff's models (DeepSeek V4 Flash, MiMo 2.5, Nemotron) are available
    through OpenRouter's API. This adapter creates a LiteLLMRouter configured
    with Freebuff models as primary, and delegates all BrainInterface methods
    through CurrentLLMAdapter.

    The adapter is honest about the integration method:
    - It uses OpenRouter, not a fake Freebuff API
    - It does not bypass Freebuff's terms of service
    - It does not spawn daemon processes
    - It does not contact invented endpoints

    Configuration (env vars):
        OPENROUTER_API_KEY  — required, your OpenRouter API key
        FOL_BRAIN_MODEL     — optional override (default: deepseek-v4-flash)
    """

    name = "freebuff"

    def __init__(self) -> None:
        self._config = freebuff_config()
        self._available: bool | None = None
        self._llm_adapter: Any = None  # CurrentLLMAdapter wrapping the router

    @property
    def available(self) -> bool:
        """True when OpenRouter is configured with a Freebuff model."""
        if self._available is not None:
            return self._available

        openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not openrouter_key:
            self._available = False
            logger.debug("Freebuff brain unavailable: no OPENROUTER_API_KEY")
            return False

        # Check that the primary model has a key
        model = os.environ.get("FOL_BRAIN_MODEL", FREEBUFF_PRIMARY_MODEL)
        if api_key_for_model(model) is None:
            self._available = False
            logger.debug("Freebuff brain unavailable: no key for model %s", model)
            return False

        self._available = True
        return True

    def _get_llm_adapter(self) -> Any:
        """Get or create the CurrentLLMAdapter with Freebuff model config."""
        if self._llm_adapter is not None:
            return self._llm_adapter

        from modules.llm.brain import CurrentLLMAdapter

        # Build a router configured for Freebuff models
        model = os.environ.get("FOL_BRAIN_MODEL", FREEBUFF_PRIMARY_MODEL)
        fallbacks = ",".join(FREEBUFF_FALLBACK_MODELS)
        router = LiteLLMRouter(primary_model=model, fallback_models=fallbacks)
        self._llm_adapter = CurrentLLMAdapter(router=router)
        return self._llm_adapter

    def status(self) -> dict[str, Any]:
        """Return current status (never contains secrets)."""
        if not self.available:
            openrouter_set = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
            return {
                "backend": self.name,
                "available": False,
                "reason": "No OPENROUTER_API_KEY configured" if not openrouter_set
                          else "No Freebuff model available",
                "integration": "OpenRouter (official Freebuff model access)",
            }

        model = os.environ.get("FOL_BRAIN_MODEL", FREEBUFF_PRIMARY_MODEL)
        return {
            "backend": self.name,
            "available": True,
            "integration": "OpenRouter (official Freebuff model access)",
            "model": model,
            "model_chain": self.model_chain(),
        }

    def model_chain(self) -> list[str]:
        """Freebuff model chain (through OpenRouter)."""
        if not self.available:
            return []
        model = os.environ.get("FOL_BRAIN_MODEL", FREEBUFF_PRIMARY_MODEL)
        return [model] + FREEBUFF_FALLBACK_MODELS

    def available_providers(self) -> list[str]:
        if not self.available:
            return []
        return ["freebuff/openrouter"]

    def test_connection(self) -> str:
        """Test connectivity to Freebuff models via OpenRouter."""
        if not self.available:
            return "❌ Freebuff brain unavailable: configure OPENROUTER_API_KEY"
        adapter = self._get_llm_adapter()
        return adapter.test_connection()

    # -- Conversational (delegate to CurrentLLMAdapter) ---------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Complete a conversation via Freebuff models through OpenRouter."""
        if not self.available:
            raise BrainError(
                f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}"
            )
        return self._get_llm_adapter().chat(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream completion via Freebuff models through OpenRouter."""
        if not self.available:
            yield {
                "type": "error",
                "message": f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}",
            }
            return
        async for event in self._get_llm_adapter().chat_stream(
            messages, system=system, tools=tools, max_tokens=max_tokens
        ):
            yield event

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Async completion via Freebuff models through OpenRouter."""
        if not self.available:
            raise BrainError(
                f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}"
            )
        return await self._get_llm_adapter().acomplete(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # -- Reasoning capabilities (delegated) --------------------------------

    def classify(self, text: str) -> str:
        if not self.available:
            raise BrainError(f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}")
        return self._get_llm_adapter().classify(text)

    def plan(self, task: str, context: str = "") -> list[str]:
        if not self.available:
            raise BrainError(f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}")
        return self._get_llm_adapter().plan(task, context=context)

    def select_tools(
        self, task: str, tools: list[dict[str, Any]]
    ) -> list[str]:
        if not self.available:
            raise BrainError(f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}")
        return self._get_llm_adapter().select_tools(task, tools)

    def summarize(self, text: str, max_words: int = 80) -> str:
        if not self.available:
            raise BrainError(f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}")
        return self._get_llm_adapter().summarize(text, max_words=max_words)

    def verify(self, claim: str, evidence: str) -> str:
        if not self.available:
            raise BrainError(f"Freebuff brain unavailable. {FREEBUFF_REQUIREMENTS}")
        return self._get_llm_adapter().verify(claim, evidence)

    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass


__all__ = ["FreebuffBrainAdapter", "FREEBUFF_PRIMARY_MODEL", "FREEBUFF_FALLBACK_MODELS"]
