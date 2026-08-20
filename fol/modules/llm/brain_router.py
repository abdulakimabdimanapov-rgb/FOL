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

import logging
from typing import Any, AsyncIterator

from modules.llm.brain import (
    BRAIN_INTENT_LABELS,
    BrainError,
    BrainInterface,
    BrainUnavailableError,
)

logger = logging.getLogger(__name__)


class BrainRouter(BrainInterface):
    """Compose multiple brains behind one contract, in priority order.

    ``chat``/``chat_stream``/``acomplete``/… delegate to the first available backend
    and fall back to subsequent backends when a failure occurs.
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

    # -- conversational with fallback ---------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        last_error: Exception | None = None
        for backend in self._backends:
            if not backend.available:
                continue
            logger.info("[BrainRouter] selected backend=%s", backend.name)
            try:
                result = backend.chat(
                    messages,
                    system=system,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if result:
                    return result
                logger.warning("[BrainRouter] backend error=empty response on backend=%s", backend.name)
                logger.info("[BrainRouter] fallback=trying next backend")
            except Exception as exc:
                last_error = exc
                logger.warning("[BrainRouter] backend error=%s on backend=%s", exc, backend.name)
                logger.info("[BrainRouter] fallback=trying next backend")

        raise BrainError(
            f"All brain backends failed to produce a response. Last error: {last_error}"
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        last_error_msg = "No available backends"
        tried_any = False

        for backend in self._backends:
            if not backend.available:
                continue
            tried_any = True
            logger.info("[BrainRouter] selected backend=%s", backend.name)

            yielded_any = False
            backend_failed = False

            try:
                async for event in backend.chat_stream(
                    messages, system=system, tools=tools, max_tokens=max_tokens
                ):
                    event_type = event.get("type")
                    if event_type == "error":
                        if not yielded_any:
                            backend_failed = True
                            last_error_msg = str(event.get("message", "unknown error"))
                            logger.warning(
                                "[BrainRouter] backend error=%s on backend=%s",
                                last_error_msg,
                                backend.name,
                            )
                            logger.info("[BrainRouter] fallback=trying next backend")
                            break
                        else:
                            # Cannot restart mid-stream after emitting partial tokens
                            yield event
                            return
                    elif event_type in ("token", "tool_use"):
                        yielded_any = True
                        yield event
                    elif event_type == "done":
                        if not yielded_any:
                            backend_failed = True
                            last_error_msg = "empty stream (0 tokens before done)"
                            logger.warning(
                                "[BrainRouter] backend error=%s on backend=%s",
                                last_error_msg,
                                backend.name,
                            )
                            logger.info("[BrainRouter] fallback=trying next backend")
                            break
                        else:
                            yield event
                            return
                    else:
                        yield event

                if not backend_failed and yielded_any:
                    return
            except Exception as exc:
                last_error_msg = str(exc)
                logger.warning(
                    "[BrainRouter] backend error=%s on backend=%s",
                    last_error_msg,
                    backend.name,
                )
                if yielded_any:
                    yield {"type": "error", "message": f"Stream failed after partial output: {exc}"}
                    return
                logger.info("[BrainRouter] fallback=trying next backend")
                continue

        if not tried_any:
            yield {"type": "error", "message": "No brain backend available in router chain."}
        else:
            yield {"type": "error", "message": f"All brain backends failed to stream a response. Last error: {last_error_msg}"}

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        for backend in self._backends:
            if not backend.available:
                continue
            logger.info("[BrainRouter] selected backend=%s", backend.name)
            try:
                result = await backend.acomplete(
                    messages,
                    system=system,
                    tools=tools,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if result.get("stop_reason") != "error" and (result.get("content") or result.get("tool_calls")):
                    return result
                logger.warning("[BrainRouter] backend error=empty/error result on backend=%s", backend.name)
                logger.info("[BrainRouter] fallback=trying next backend")
            except Exception as exc:
                logger.warning("[BrainRouter] backend error=%s on backend=%s", exc, backend.name)
                logger.info("[BrainRouter] fallback=trying next backend")

        return {"content": "", "tool_calls": [], "stop_reason": "error"}

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
