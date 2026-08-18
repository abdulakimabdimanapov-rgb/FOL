"""Brain Router — ordered backend composition behind ``BrainInterface``.

The router is the extension point that lets FOL try a chain of brains
(e.g. ``[freebuff, current]``) and fall back at runtime. It implements the
SAME ``BrainInterface`` contract, so consumers never know which backend
answered.

Strictness: a backend that is ``available=False`` at construction time is
NOT silently skipped for the primary position — selection strictness lives
in ``get_brain()`` (an explicitly requested unavailable brain raises
``BrainConfigurationError``). The router itself only delegates to the first
``available`` backend and raises ``BrainUnavailableError`` when none can
answer.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from modules.llm.brain import (
    BRAIN_INTENT_LABELS,
    BrainInterface,
    BrainUnavailableError,
)


class BrainRouter(BrainInterface):
    """Compose multiple brains behind one contract, in priority order.

    ``chat``/``chat_stream``/``acomplete``/… delegate to the first backend
    whose ``available`` is True. When no backend is available every
    reasoning call raises :class:`BrainUnavailableError` (streaming yields
    an ``error`` event instead).
    """

    name = "router"

    def __init__(self, backends: list[BrainInterface]) -> None:
        if not backends:
            raise ValueError("BrainRouter requires at least one backend")
        self._backends: list[BrainInterface] = list(backends)

    # -- introspection ------------------------------------------------------

    @property
    def available(self) -> bool:
        return any(b.available for b in self._backends)

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.available,
            "chain": [b.status() for b in self._backends],
        }

    def model_chain(self) -> list[str]:
        for b in self._backends:
            if b.available:
                return b.model_chain()
        return []

    def available_providers(self) -> list[str]:
        for b in self._backends:
            if b.available:
                return b.available_providers()
        return []

    def test_connection(self) -> str:
        for b in self._backends:
            if b.available:
                return b.test_connection()
        return "❌ no available brain backend"

    # -- internal -----------------------------------------------------------

    def _first_available(self) -> BrainInterface:
        for b in self._backends:
            if b.available:
                return b
        raise BrainUnavailableError(
            "No brain backend available in router chain: "
            + ", ".join(b.name for b in self._backends)
        )

    # -- conversational -----------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return self._first_available().chat(
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
        try:
            backend = self._first_available()
        except BrainUnavailableError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        async for event in backend.chat_stream(
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
        return await self._first_available().acomplete(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # -- reasoning capabilities (delegated to the first available brain) ----

    def classify(self, text: str) -> str:
        return self._first_available().classify(text)

    def plan(self, task: str, context: str = "") -> list[str]:
        return self._first_available().plan(task, context=context)

    def select_tools(
        self, task: str, tools: list[dict[str, Any]]
    ) -> list[str]:
        return self._first_available().select_tools(task, tools)

    def summarize(self, text: str, max_words: int = 80) -> str:
        return self._first_available().summarize(text, max_words=max_words)

    def verify(self, claim: str, evidence: str) -> str:
        return self._first_available().verify(claim, evidence)


__all__ = ["BrainRouter", "BRAIN_INTENT_LABELS"]
