"""Integration tests for memory workflow."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_conversation_history_workflow():
    """Test full conversation history workflow."""
    from modules.memory.conversation import ConversationHistory

    history = ConversationHistory()
    await history.initialize()

    # Add turns (positional args)
    turn1 = await history.add_turn("Hello", "Hi there!")
    turn2 = await history.add_turn("How are you?", "I'm fine!")

    # Retrieve recent
    recent = await history.get_recent(n=10)
    assert len(recent) >= 2

    await history.shutdown()


@pytest.mark.asyncio
async def test_preferences_workflow():
    """Test preferences store workflow."""
    from modules.memory.preferences import PreferencesStore

    prefs = PreferencesStore()
    await prefs.initialize()

    # Set preference
    await prefs.set("language", "ru")
    value = await prefs.get("language")
    assert value == "ru"

    # Update
    await prefs.set("language", "en")
    value = await prefs.get("language")
    assert value == "en"

    await prefs.shutdown()


@pytest.mark.asyncio
async def test_episodic_memory_workflow():
    """Test episodic memory workflow."""
    from modules.memory.episodic_memory import EpisodicMemory

    episodic = EpisodicMemory()
    await episodic.initialize()

    # Record event (method is 'record', not 'store')
    episode = await episodic.record("User opened Safari", metadata={"action": "open_app"})
    assert episode is not None
    assert episode.event == "User opened Safari"

    # Retrieve recent
    recent = await episodic.get_recent(n=10)
    assert len(recent) >= 1

    await episodic.shutdown()
