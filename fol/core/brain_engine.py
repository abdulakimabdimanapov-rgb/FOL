"""Brain Engine Adapter — wraps BrainInterface to expose LLMEngine.generate() API.

This adapter lets fol/core/app.py use the unified BrainInterface (get_brain())
instead of the legacy LLMEngine, while preserving the familiar `generate()`
signature that existing consumers expect.

The adapter:
  - Delegates to BrainInterface.chat() for text generation
  - Preserves auto-temperature selection (code/creative/factual)
  - Delegates model chain introspection to the brain
  - Provides shutdown() as a no-op (BrainInterface handles its own lifecycle)

This eliminates the parallel LLM routing that existed between LLMEngine and
BrainInterface, unifying all LLM calls through a single path.
"""

from __future__ import annotations

import logging
from typing import Any

from modules.llm.brain import BrainInterface, BrainError, get_brain
from modules.llm.language import detect_language, get_lang_prompt_hint
from modules.llm.personality import FOL_PERSONALITY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Personality block — appended to every LLM call so FOL always behaves like
# a natural JARVIS-like assistant regardless of the active agent/prompt.
FOL_PERSONALITY = FOL_PERSONALITY_SYSTEM_PROMPT


def _auto_temperature(user_input: str) -> float:
    """Auto-select temperature based on query type.

    - Code/technical: lower temp for precision
    - Creative/open: higher temp for variety
    - Simple questions: moderate temp
    """
    lower = user_input.lower()
    # Creative/brainstorming → higher temperature
    creative_signals = [
        "напиши", "придумай", "сочини", "write", "create", "generate",
        "imagine", "brainstorm",
    ]
    if any(s in lower for s in creative_signals):
        return 0.8
    # Code/technical → lower temperature
    code_signals = [
        "code", "код", "python", "swift", "bug", "fix", "исправ", "отлад",
        "debug", "function", "класс",
    ]
    if any(s in lower for s in code_signals):
        return 0.3
    # Factual questions → very low temperature
    fact_signals = [
        "what is", "что такое", "какой", "сколько", "когда", "who is",
        "кто такой",
    ]
    if any(s in lower for s in fact_signals):
        return 0.2
    # Default conversational
    return 0.6


class BrainEngineAdapter:
    """Thin adapter exposing BrainInterface through the LLMEngine.generate() API.

    Used by fol/core/app.py to replace the legacy LLMEngine while preserving
    backward compatibility for all consumers (UniversalExecutor, screen analysis,
    response generation, etc.).
    """

    def __init__(self, brain: BrainInterface | None = None, *, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._brain: BrainInterface | None = brain
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the brain backend via get_brain() if not already provided."""
        if self._brain is not None:
            self._initialized = True
            return

        try:
            self._brain = get_brain()
            self._initialized = True
            logger.info("Brain engine initialized: %s", self._brain.name)
        except Exception as exc:
            logger.error("Failed to initialize brain engine: %s", exc)
            self._brain = None

    async def shutdown(self) -> None:
        """No-op — BrainInterface handles its own lifecycle."""
        pass

    async def generate(
        self,
        user_input: str,
        *,
        context: str = "",
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a response using the brain backend.

        Mirrors LLMEngine.generate() signature for backward compatibility:
        - Builds system prompt with personality and language hints
        - Appends context to the system prompt
        - Auto-selects temperature based on query type
        - Delegates to BrainInterface.chat()
        """
        if self._brain is None or not self._initialized:
            return "All LLM backends are unavailable. Please configure an API key in .env."

        # Build system prompt
        lang = detect_language(user_input)
        lang_hint = get_lang_prompt_hint(lang)
        sys_content = system_prompt or ""
        sys_content += f"\n\n{FOL_PERSONALITY}"
        sys_content += f"\n\n{lang_hint}"

        # Inject context sections with clear labels
        if context:
            sys_content += f"\n\n## Additional Context\n{context}"

        # Build messages (BrainInterface.chat() expects message list)
        messages = [{"role": "user", "content": user_input}]

        # Apply temperature
        effective_temp = temperature if temperature is not None else _auto_temperature(user_input)

        # Cap max_tokens
        effective_max_tokens = (
            max_tokens
            if max_tokens is not None
            else int(self._config.get("llm_max_tokens") or 4096)
        )

        try:
            result = self._brain.chat(
                messages,
                system=sys_content.strip() if sys_content.strip() else None,
                max_tokens=effective_max_tokens,
                temperature=effective_temp,
            )
            if result and not result.startswith("["):
                return result
            logger.warning("Brain engine returned empty/error response")
        except BrainError as exc:
            logger.warning("Brain engine failed: %s", exc)
        except Exception as exc:
            logger.warning("Brain engine error: %s", exc)

        return "All LLM backends are unavailable. Please configure an API key in .env."

    @property
    def available_backends(self) -> list[str]:
        """List of available backend names."""
        if self._brain is None:
            return []
        return self._brain.available_providers()

    @property
    def active_model(self) -> str | None:
        """Currently active model name."""
        if self._brain is None:
            return None
        chain = self._brain.model_chain()
        return chain[0] if chain else None

    def model_chain(self) -> list[str]:
        """Ordered list of models that would be tried."""
        if self._brain is None:
            return []
        return self._brain.model_chain()

    def status(self) -> dict[str, Any]:
        """Brain backend status."""
        if self._brain is None:
            return {"backend": "none", "available": False}
        return self._brain.status()

    def test_connection(self) -> str:
        """Quick connectivity test."""
        if self._brain is None:
            return "❌ No brain backend configured"
        return self._brain.test_connection()


__all__ = ["BrainEngineAdapter"]
