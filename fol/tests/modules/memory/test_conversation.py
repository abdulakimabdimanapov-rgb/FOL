"""Tests for ConversationHistory."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.memory.conversation import ConversationHistory


@pytest.fixture
def history(tmp_path: Path) -> ConversationHistory:
    return ConversationHistory(history_path=tmp_path / "test_history.jsonl", max_turns=100)


@pytest.mark.asyncio
async def test_add_and_get_recent(history: ConversationHistory):
    await history.add_turn("hello", "hi there")
    await history.add_turn("how are you?", "good")
    recent = await history.get_recent(n=1)
    assert len(recent) == 1
    assert recent[0].user_input == "how are you?"


@pytest.mark.asyncio
async def test_turn_count(history: ConversationHistory):
    await history.add_turn("a", "b")
    await history.add_turn("c", "d")
    assert history.turn_count == 2


@pytest.mark.asyncio
async def test_search(history: ConversationHistory):
    await history.add_turn("what is python?", "Python is a language")
    await history.add_turn("hello", "hi")
    results = await history.search("python")
    assert len(results) == 1
    assert "Python" in results[0].assistant_response


@pytest.mark.asyncio
async def test_persistence(tmp_path: Path):
    h1 = ConversationHistory(history_path=tmp_path / "hist.jsonl")
    await h1.initialize()
    await h1.add_turn("q1", "a1")
    await h1.shutdown()

    h2 = ConversationHistory(history_path=tmp_path / "hist.jsonl")
    await h2.initialize()
    assert h2.turn_count == 1


@pytest.mark.asyncio
async def test_clear(history: ConversationHistory):
    await history.add_turn("q", "a")
    await history.clear()
    assert history.turn_count == 0
