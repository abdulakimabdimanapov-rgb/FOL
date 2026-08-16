"""Tests for KnowledgeGraph."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.memory.knowledge_graph import KnowledgeGraph


@pytest.fixture
def graph(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(graph_path=tmp_path / "test_graph.json")


@pytest.mark.asyncio
async def test_add_entity(graph: KnowledgeGraph):
    entity = await graph.add_entity("Alice", "person")
    assert entity.name == "Alice"
    assert graph.entity_count == 1


@pytest.mark.asyncio
async def test_add_relation(graph: KnowledgeGraph):
    await graph.add_relation("Alice", "Bob", "friend_of")
    assert graph.relation_count == 1
    assert graph.entity_count == 2


@pytest.mark.asyncio
async def test_get_relations(graph: KnowledgeGraph):
    await graph.add_relation("Alice", "Bob", "friend_of")
    await graph.add_relation("Alice", "Charlie", "colleague_of")
    relations = await graph.get_relations("Alice")
    assert len(relations) == 2


@pytest.mark.asyncio
async def test_search(graph: KnowledgeGraph):
    await graph.add_entity("Alice Smith", "person")
    await graph.add_entity("Bob Jones", "person")
    results = await graph.search("alice")
    assert len(results) == 1
    assert results[0].name == "Alice Smith"


@pytest.mark.asyncio
async def test_persistence(tmp_path: Path):
    g1 = KnowledgeGraph(graph_path=tmp_path / "g.json")
    await g1.initialize()
    await g1.add_entity("Test")
    await g1.shutdown()

    g2 = KnowledgeGraph(graph_path=tmp_path / "g.json")
    await g2.initialize()
    assert g2.entity_count == 1
