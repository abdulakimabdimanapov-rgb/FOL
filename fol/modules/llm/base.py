"""Abstract base class for LLM backends."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


@dataclass
class LLMResponse:
    """Response from an LLM backend."""

    text: str = ""
    model: str = ""
    tokens_used: int = 0
    finish_reason: str = "stop"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


class AbstractLLMBackend(abc.ABC):
    """Base class all LLM backends must implement."""

    name: str = "base_llm"

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Load model / connect to API."""

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Cleanup resources."""

    @abc.abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response from messages."""
