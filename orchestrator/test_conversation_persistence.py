"""
Conversation persistence tests — follow-up context must survive restarts.

The orchestrator persists dialog turns to a JSONL store
(``~/.fol/conversation_history.jsonl`` via ``ConversationHistory``). On a
restart, ``lifespan`` re-initializes the store from disk, so
``_get_recent_history_sync()`` keeps returning prior turns — that's what lets
the model answer "а какая самая важная?" after the previous request.
"""

import pytest

import server as srv
from fol.modules.memory.conversation import ConversationHistory


@pytest.fixture
def restore_store_state():
    """Restore the module-level store globals after each test."""
    store = srv._conversation_store
    initialized = srv._conversation_store_initialized
    history = srv._conversation_history
    yield
    srv._conversation_store = store
    srv._conversation_store_initialized = initialized
    srv._conversation_history = history


async def _build_store(path, turns):
    store = ConversationHistory(history_path=path)
    await store.initialize()
    for user_input, assistant_response in turns:
        await store.add_turn(user_input=user_input, assistant_response=assistant_response)
    await store.save()
    return store


class TestConversationPersistence:
    @pytest.mark.asyncio
    async def test_history_survives_restart(self, tmp_path, restore_store_state):
        """Turns written before a "restart" are visible after re-initialization."""
        history_path = tmp_path / "conversation_history.jsonl"
        turns = [
            ("find news about OpenAI", "here are the top headlines..."),
            ("what is the most important one?", "the funding round is the big story"),
        ]

        # First "session"
        first = await _build_store(history_path, turns)
        srv._conversation_store = first
        seen = srv._get_recent_history_sync(40)
        assert [m["role"] for m in seen] == ["user", "assistant", "user", "assistant"]
        assert seen[2]["content"] == "what is the most important one?"

        # Simulate an orchestrator restart: brand-new store object on the SAME file
        restarted = ConversationHistory(history_path=history_path)
        await restarted.initialize()
        assert restarted.turn_count == 2

        srv._conversation_store = restarted
        seen_again = srv._get_recent_history_sync(40)
        assert [m["role"] for m in seen_again] == ["user", "assistant", "user", "assistant"]
        assert seen_again[3]["content"] == "the funding round is the big story"

    @pytest.mark.asyncio
    async def test_store_initialized_from_disk_eagerly(self, tmp_path, restore_store_state):
        """A fresh ConversationHistory() + initialize() loads prior turns from disk."""
        history_path = tmp_path / "conversation_history.jsonl"
        await _build_store(history_path, [("remember this", "done")])

        fresh = ConversationHistory(history_path=history_path)
        assert fresh.turn_count == 0  # not yet loaded
        await fresh.initialize()
        assert fresh.turn_count == 1
        recent = await fresh.get_recent(n=5)
        assert recent[-1].user_input == "remember this"

    @pytest.mark.asyncio
    async def test_get_recent_history_falls_back_to_memory(self, restore_store_state):
        """Without a persistent store, the in-memory history is returned."""
        srv._conversation_store = None
        srv._conversation_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        seen = srv._get_recent_history_sync(40)
        assert [m["role"] for m in seen] == ["user", "assistant"]
        assert seen[0]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_in_memory_history_preferred_while_streaming(self, tmp_path, restore_store_state):
        """The live message being processed must NEVER be shadowed by the
        (asynchronously-flushed) persistent store."""
        store = await _build_store(tmp_path / "conversation_history.jsonl", [("old", "old answer")])
        srv._conversation_store = store
        # Simulate mid-request: user message already in memory, store lags behind
        srv._conversation_history = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "what is the most important one?"},
        ]
        seen = srv._get_recent_history_sync(40)
        assert seen[-1]["content"] == "what is the most important one?"
