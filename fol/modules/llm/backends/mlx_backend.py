"""MLX backend — local LLM inference on Apple Silicon."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.llm.base import AbstractLLMBackend, LLMResponse

logger = logging.getLogger(__name__)

try:
    import mlx_lm
    HAS_MLX_LM = True
except ImportError:
    HAS_MLX_LM = False


class MLXBackend(AbstractLLMBackend):
    """Local LLM inference using MLX on Apple Silicon."""

    name = "mlx"

    def __init__(self, model_name: str = "mlx-community/Llama-3.2-3B-Instruct-4bit") -> None:
        self._model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None
        self._is_ready = False

    async def initialize(self) -> None:
        if not HAS_MLX_LM:
            logger.warning("mlx-lm not available, MLX backend disabled")
            return

        logger.info("Loading MLX model", model=self._model_name)
        try:
            self._model, self._tokenizer = await asyncio.to_thread(
                mlx_lm.load, self._model_name
            )
            self._is_ready = True
            logger.info("MLX model loaded successfully")
        except Exception as exc:
            logger.error("Failed to load MLX model: %s", exc)

    async def shutdown(self) -> None:
        self._model = None
        self._tokenizer = None
        self._is_ready = False
        logger.info("MLX backend shut down")

    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        if not self._is_ready:
            return LLMResponse(text="[MLX model not loaded]", model=self._model_name)

        try:
            prompt = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )

            response_text = await asyncio.to_thread(
                mlx_lm.generate,
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
            )

            return LLMResponse(
                text=response_text.strip(),
                model=self._model_name,
                finish_reason="stop",
            )
        except Exception as exc:
            logger.error("MLX generation failed: %s", exc)
            return LLMResponse(text=f"[Generation error: {exc}]", model=self._model_name)
