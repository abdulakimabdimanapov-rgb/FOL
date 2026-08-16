"""Tests for EpisodicMemory."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.memory.episodic_memory import EpisodicMemory


@pytest.fixture
def memory(tmp_path: Path) -> EpisodicMemory:
    return EpisodicMemory(memory_path=tmp_path / "test_episodic.jsonl")


@pytest.mark.asyncio
async def test_record(memory: EpisodicMemory):
    ep = await memory.record("User said hello", context="morning session")
    assert ep.event == "User said hello"
    assert memory.episode_count == 1


@pytest.mark.asyncio
async def test_search(memory: EpisodicMemory):
    await memory.record("Opened Safari")
    await memory.record("Closed Terminal")
    results = await memory.search("safari")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_get_recent(memory: EpisodicMemory):
    for i in range(5):
        await memory.record(f"Event {i}")
    recent = await memory.get_recent(n=3)
    assert len(recent) == 3
    assert recent[0].event == "Event 2"


@pytest.mark.asyncio
async def test_persistence(tmp_path: Path):
    m1 = EpisodicMemory(memory_path=tmp_path / "ep.jsonl")
    await m1.initialize()
    await m1.record("test event")
    await m1.shutdown()

    m2 = EpisodicMemory(memory_path=tmp_path / "ep.jsonl")
    await m2.initialize()
    assert m2.episode_count == 1
