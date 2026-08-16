"""LLM Engine — manages backends and routes requests."""

from __future__ import annotations

import logging
from typing import Any

from modules.llm.base import AbstractLLMBackend, LLMResponse
from modules.llm.backends.mlx_backend import MLXBackend
from modules.llm.backends.openai_backend import OPENROUTER_BASE_URL, OpenAIBackend
from modules.llm.backends.anthropic_backend import AnthropicBackend
from modules.llm.language import detect_language, get_lang_prompt_hint
from modules.llm.personality import FOL_PERSONALITY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are F.O.L. (Friendly Obedient Listener), a personal AI assistant inspired by JARVIS.
You are running on a MacBook Air M2. You are helpful, conversational, and proactive.
Always address the user by name if known, otherwise use "sir" / "босс".
You can manage windows and programs on macOS.
If you need to perform actions on the computer, describe what you will do.
"""

# Personality block — appended to every LLM call so FOL always behaves like
# a natural JARVIS-like assistant regardless of the active agent/prompt.
FOL_PERSONALITY = FOL_PERSONALITY_SYSTEM_PROMPT


class LLMEngine:
    """Manages multiple LLM backends with automatic failover."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._backends: dict[str, AbstractLLMBackend] = {}
        self._primary_backend: str = self._config.get("llm_backend", "mlx")
        # Build fallback order: primary first, then others
        all_backends = ["openrouter", "mlx", "openai", "anthropic"]
        self._fallback_order: list[str] = [self._primary_backend] + [b for b in all_backends if b != self._primary_backend]

    async def initialize(self) -> None:
        """Initialize configured backends based on config."""
        # MLX — only if backend is mlx or as fallback
        mlx_model = self._config.get("llm_model", "mlx-community/Qwen2.5-0.5B-Instruct-4bit")
        # Don't use gpt-4o as MLX model name
        if not mlx_model.startswith("gpt-") and not mlx_model.startswith("claude-"):
            mlx = MLXBackend(model_name=mlx_model)
            await mlx.initialize()
            self._backends["mlx"] = mlx

        # OpenRouter if key provided (OpenAI-compatible endpoint)
        openrouter_key = self._config.get("openrouter_api_key", "")
        if openrouter_key:
            or_b = OpenAIBackend(
                api_key=openrouter_key,
                model=self._config.get("openrouter_model", "nvidia/nemotron-3-ultra-550b-a55b:free"),
                base_url=self._config.get("openrouter_base_url", OPENROUTER_BASE_URL),
            )
            await or_b.initialize()
            self._backends["openrouter"] = or_b

        # OpenAI if key provided
        openai_key = self._config.get("openai_api_key", "")
        if openai_key:
            oai = OpenAIBackend(api_key=openai_key, model=self._config.get("openai_model", "gpt-4o-mini"))
            await oai.initialize()
            self._backends["openai"] = oai

        # Anthropic if key provided
        anthropic_key = self._config.get("anthropic_api_key", "")
        if anthropic_key:
            ant = AnthropicBackend(api_key=anthropic_key)
            await ant.initialize()
            self._backends["anthropic"] = ant

        logger.info("LLM Engine initialized", primary=self._primary_backend, backends=list(self._backends.keys()))

    async def shutdown(self) -> None:
        for backend in self._backends.values():
            await backend.shutdown()
        self._backends.clear()

    async def generate(
        self,
        user_input: str,
        *,
        context: str = "",
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Generate a response using the best available backend.

        Args:
            user_input: The user's message.
            context: Additional context (conversation history, memories, etc.).
            system_prompt: Override system prompt.
            temperature: Override temperature (0.0-1.0). Higher = more creative.
            max_tokens: Override max response length.
        """
        messages = self._build_messages(user_input, context, system_prompt)

        # Apply temperature based on query type
        effective_temp = temperature if temperature is not None else self._auto_temperature(user_input)

        # Cap max_tokens so requests fit the remaining credit balance / model
        # limit. Without this, max_tokens=None makes cloud APIs default to the
        # model maximum (e.g. 16k for gpt-4o-mini), which exceeds small credit
        # balances and fails with 402. The env-configured FOL_LLM_MAX_TOKENS
        # (1500 in fol/.env; settings default 4096) is passed through the app
        # config; the ``or 4096`` fallback covers direct LLMEngine callers.
        effective_max_tokens = (
            max_tokens
            if max_tokens is not None
            else int(self._config.get("llm_max_tokens") or 4096)
        )

        # Try backends in fallback order
        for backend_name in self._fallback_order:
            backend = self._backends.get(backend_name)
            if backend is None:
                continue

            try:
                response = await backend.generate(
                    messages,
                    temperature=effective_temp,
                    max_tokens=effective_max_tokens,
                )
            except TypeError:
                # Backend doesn't support temperature kwargs
                response = await backend.generate(messages)

            if response.text and not response.text.startswith("["):
                logger.info("LLM response generated from %s (%d chars, temp=%.1f)", backend_name, len(response.text), effective_temp)
                return response.text

            logger.warning("Backend %s failed, trying next", backend_name)

        return "All LLM backends are unavailable. Please configure an API key or install mlx-lm."

    def _auto_temperature(self, user_input: str) -> float:
        """Auto-select temperature based on query type.

        - Code/technical: lower temp for precision
        - Creative/open: higher temp for variety
        - Simple questions: moderate temp
        """
        lower = user_input.lower()
        # Creative/brainstorming → higher temperature
        creative_signals = ["напиши", "придумай", "сочини", "write", "create", "generate", "imagine", "brainstorm"]
        if any(s in lower for s in creative_signals):
            return 0.8
        # Code/technical → lower temperature
        code_signals = ["code", "код", "python", "swift", "bug", "fix", " исправ", "отлад", "debug", "function", "класс"]
        if any(s in lower for s in code_signals):
            return 0.3
        # Factual questions → very low temperature
        fact_signals = ["what is", "что такое", "какой", "сколько", "когда", "who is", "кто такой"]
        if any(s in lower for s in fact_signals):
            return 0.2
        # Default conversational
        return 0.6

    def _build_messages(
        self,
        user_input: str,
        context: str,
        system_prompt: str,
    ) -> list[dict[str, str]]:
        """Build message list for the LLM.

        Automatically detects the user's language and injects a strong
        instruction so the model always replies in the same language.
        Builds rich context from behavioral data, memories, and conversation.
        """
        messages = []

        # Detect language and build system prompt
        lang = detect_language(user_input)
        lang_hint = get_lang_prompt_hint(lang)
        sys_content = system_prompt or SYSTEM_PROMPT
        # Personality instructions always apply — independent of agent/prompt
        sys_content += f"\n\n{FOL_PERSONALITY}"
        sys_content += f"\n\n{lang_hint}"

        # Inject context sections with clear labels
        if context:
            sys_content += f"\n\n## Additional Context\n{context}"

        messages.append({"role": "system", "content": sys_content})

        # User message
        messages.append({"role": "user", "content": user_input})

        return messages

    @property
    def available_backends(self) -> list[str]:
        return list(self._backends.keys())
