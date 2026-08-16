"""Memory boundary — the canonical interface between the orchestrator and
``fol/modules/memory/``.

This phase does NOT migrate the memory stores. It only defines the clean
interface the orchestration layer uses, so new code depends on the boundary
instead of individual store implementations:

    retrieve_context(query)             → assembled context string for prompts
    store_memory(content, metadata)     → persist a fact / preference
    retrieve_relevant_memories(query)   → ranked MemoryItem list
    record_episode(event, context)      → episodic memory ("what happened")

``RAGMemoryService`` is the reference adapter over the existing stores
(RAGPipeline / VectorStore / EpisodicMemory / LongTermMemory). All existing
stores remain untouched.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from modules.memory.base import MemoryItem

logger = logging.getLogger(__name__)


@runtime_checkable
class MemoryService(Protocol):
    """Canonical orchestrator↔memory boundary."""

    async def retrieve_context(self, query: str, *, max_tokens: int = 2000) -> str:
        """Return a context block for prompt assembly, or ``""``."""

    async def store_memory(self, content: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Persist a memory item."""

    async def retrieve_relevant_memories(self, query: str, *, limit: int = 10) -> list[MemoryItem]:
        """Return ranked relevant memories."""

    async def record_episode(
        self,
        event: str,
        *,
        context: str = "",
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an episodic memory."""


class RAGMemoryService:
    """Reference ``MemoryService`` over the existing FOL memory stores.

    Degrades gracefully: when a store is unavailable (e.g. vector search is
    not initialized), the service falls back to the next available store and
    never raises.
    """

    name = "rag_memory"

    def __init__(
        self,
        rag: Any | None = None,
        vector_store: Any | None = None,
        episodic: Any | None = None,
        long_term: Any | None = None,
    ) -> None:
        self._rag = rag
        self._vector = vector_store
        self._episodic = episodic
        self._long_term = long_term

    async def retrieve_context(self, query: str, *, max_tokens: int = 2000) -> str:
        if self._rag is not None:
            try:
                return await self._rag.retrieve_context(query, max_tokens=max_tokens)
            except Exception as exc:
                logger.debug("RAG retrieve_context failed: %s", exc)
        if self._long_term is not None:
            try:
                return self._long_term.get_context_for_query(query, max_tokens=max_tokens)
            except Exception as exc:
                logger.debug("LongTermMemory context failed: %s", exc)
        return ""

    async def store_memory(self, content: str, *, metadata: dict[str, Any] | None = None) -> None:
        metadata = metadata or {}
        category = metadata.get("category", "general")
        if self._rag is not None:
            try:
                await self._rag.store_fact(content, category=category)
                return
            except Exception as exc:
                logger.debug("RAG store_fact failed: %s", exc)
        if self._long_term is not None:
            try:
                self._long_term.store_memory(
                    content,
                    category=category,
                    importance=float(metadata.get("importance", 0.5)),
                    tags=list(metadata.get("tags", [])),
                )
                return
            except Exception as exc:
                logger.debug("LongTermMemory store failed: %s", exc)
        logger.warning("store_memory dropped — no memory store available")

    async def retrieve_relevant_memories(self, query: str, *, limit: int = 10) -> list[MemoryItem]:
        if self._vector is not None:
            try:
                return await self._vector.retrieve(query, limit=limit)
            except Exception as exc:
                logger.debug("Vector retrieve failed: %s", exc)
        if self._long_term is not None:
            try:
                return [
                    MemoryItem(
                        content=m.content,
                        metadata={"category": m.category},
                        timestamp=m.timestamp,
                        score=1.0,
                    )
                    for m in self._long_term.search_memories(query, limit=limit)
                ]
            except Exception as exc:
                logger.debug("LongTermMemory search failed: %s", exc)
        return []

    async def record_episode(
        self,
        event: str,
        *,
        context: str = "",
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self._episodic is not None:
            try:
                await self._episodic.record(
                    event, context=context, importance=importance, metadata=metadata or {}
                )
                return
            except Exception as exc:
                logger.debug("EpisodicMemory record failed: %s", exc)
        if self._long_term is not None:
            try:
                self._long_term.store_episode(
                    event,
                    context=context,
                    importance=importance,
                    metadata=metadata or {},
                )
                return
            except Exception as exc:
                logger.debug("LongTermMemory episode failed: %s", exc)
        logger.warning("record_episode dropped — no episodic store available")


__all__ = ["MemoryService", "RAGMemoryService"]
