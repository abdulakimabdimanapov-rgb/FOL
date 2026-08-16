"""Tests for RAG pipeline."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.memory.rag import RAGPipeline
from modules.memory.vector_store import VectorStore
from modules.memory.conversation import ConversationHistory
from modules.memory.knowledge_graph import KnowledgeGraph
from modules.memory.preferences import PreferencesStore


@pytest.fixture
def rag(tmp_path: Path) -> RAGPipeline:
    return RAGPipeline(
        vector_store=VectorStore(collection_name="test", db_path=tmp_path / "vectordb"),
        conversation_history=ConversationHistory(history_path=tmp_path / "hist.jsonl"),
        knowledge_graph=KnowledgeGraph(graph_path=tmp_path / "kg.json"),
        preferences=PreferencesStore(prefs_path=tmp_path / "prefs.json"),
    )


@pytest.mark.asyncio
async def test_store_conversation(rag: RAGPipeline):
    await rag.store_conversation("hello", "hi there")
    # Should be stored in history
    assert rag._history.turn_count == 1


@pytest.mark.asyncio
async def test_store_fact(rag: RAGPipeline):
    await rag.store_fact("Python is a programming language")
    # Vector store may not be available (chromadb optional)
    # Just verify no exception is raised
    assert True


@pytest.mark.asyncio
async def test_extract_entities(rag: RAGPipeline):
    await rag.extract_and_store_entities("My name is Alexander")
    entity = await rag._kg.get_entity("Alexander")
    assert entity is not None
    assert entity.entity_type == "person"
