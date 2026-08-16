"""Regression tests for the memory boundary (modules/memory/interface.py).

Verifies the canonical orchestrator↔memory interface
(retrieve_context / store_memory / retrieve_relevant_memories /
record_episode) over the existing stores, including graceful fallback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.memory.base import MemoryItem
from modules.memory.interface import MemoryService, RAGMemoryService


class TestRAGMemoryService:
    async def test_retrieve_context_delegates_to_rag(self):
        rag = AsyncMock()
        rag.retrieve_context = AsyncMock(return_value="rag context")
        service = RAGMemoryService(rag=rag)
        assert await service.retrieve_context("query", max_tokens=500) == "rag context"
        rag.retrieve_context.assert_awaited_once_with("query", max_tokens=500)

    async def test_retrieve_context_falls_back_to_long_term(self):
        rag = AsyncMock()
        rag.retrieve_context = AsyncMock(side_effect=RuntimeError("vector down"))
        long_term = MagicMock()
        long_term.get_context_for_query = MagicMock(return_value="ltm context")
        service = RAGMemoryService(rag=rag, long_term=long_term)
        assert await service.retrieve_context("q") == "ltm context"

    async def test_retrieve_context_empty_when_nothing_available(self):
        assert await RAGMemoryService().retrieve_context("q") == ""

    async def test_store_memory_via_rag_store_fact(self):
        rag = AsyncMock()
        rag.store_fact = AsyncMock()
        await RAGMemoryService(rag=rag).store_memory(
            "user likes coffee", metadata={"category": "preference"}
        )
        rag.store_fact.assert_awaited_once_with("user likes coffee", category="preference")

    async def test_store_memory_via_long_term(self):
        long_term = MagicMock()
        long_term.store_memory = MagicMock()
        await RAGMemoryService(long_term=long_term).store_memory("fact", metadata={})
        long_term.store_memory.assert_called_once()
        assert long_term.store_memory.call_args.args[0] == "fact"

    async def test_retrieve_relevant_memories_via_vector(self):
        vector = AsyncMock()
        vector.retrieve = AsyncMock(return_value=[MemoryItem(content="m1")])
        service = RAGMemoryService(vector_store=vector)
        items = await service.retrieve_relevant_memories("q", limit=5)
        assert len(items) == 1
        assert items[0].content == "m1"
        vector.retrieve.assert_awaited_once_with("q", limit=5)

    async def test_retrieve_relevant_memories_via_long_term(self):
        long_term = MagicMock()
        entry = MagicMock()
        entry.content = "m1"
        entry.category = "general"
        entry.timestamp = 1.0
        long_term.search_memories = MagicMock(return_value=[entry])
        items = await RAGMemoryService(long_term=long_term).retrieve_relevant_memories("q")
        assert items[0].content == "m1"
        assert items[0].metadata == {"category": "general"}

    async def test_retrieve_relevant_memories_empty(self):
        assert await RAGMemoryService().retrieve_relevant_memories("q") == []

    async def test_record_episode_via_episodic(self):
        episodic = AsyncMock()
        episodic.record = AsyncMock()
        await RAGMemoryService(episodic=episodic).record_episode(
            "user opened Safari", context="desktop", importance=0.7, metadata={"app": "Safari"}
        )
        episodic.record.assert_awaited_once_with(
            "user opened Safari", context="desktop", importance=0.7, metadata={"app": "Safari"}
        )

    async def test_record_episode_via_long_term(self):
        long_term = MagicMock()
        long_term.store_episode = MagicMock()
        await RAGMemoryService(long_term=long_term).record_episode("event")
        long_term.store_episode.assert_called_once()
        assert long_term.store_episode.call_args.args[0] == "event"

    async def test_never_raises_when_stores_fail(self):
        rag = AsyncMock()
        rag.store_fact = AsyncMock(side_effect=RuntimeError("disk full"))
        rag.retrieve_context = AsyncMock(side_effect=RuntimeError("vector down"))
        # Falls through to nothing — no raise.
        await RAGMemoryService(rag=rag).store_memory("x", metadata={})
        await RAGMemoryService(rag=rag).record_episode("e")
        assert await RAGMemoryService(rag=rag).retrieve_context("q") == ""


class TestMemoryServiceProtocol:
    def test_service_implements_protocol(self):
        assert isinstance(RAGMemoryService(), MemoryService)
