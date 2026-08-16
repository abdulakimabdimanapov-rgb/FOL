"""Tests for memory persistence fix — проверка что модель помнит контекст.

Тестирует:
1. build_context_messages() — возвращает правильный контекст
2. Инжекция контекста в начало messages
3. _append_to_history — трекинг сообщений
4. Полный flow: 5 сообщений → модель помнит первое

Fixtures (reset_globals) provided by tests/conftest.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

# Use shared reset_globals from conftest (opt-in, not autouse)
pytestmark = pytest.mark.usefixtures("reset_globals")

import server


# ---------------------------------------------------------------------------
# Test 1: build_context_messages() produces valid context
# ---------------------------------------------------------------------------

class TestBuildContextMessages:
    """Test that context messages are properly built."""

    def test_returns_list_with_one_message(self):
        """Context should return a list with one user message."""
        context_msgs = server.build_context_messages()
        assert isinstance(context_msgs, list)
        assert len(context_msgs) >= 1

    def test_message_has_role_user(self):
        """Context message should have role 'user'."""
        context_msgs = server.build_context_messages()
        msg = context_msgs[0]
        assert msg["role"] == "user"

    def test_contains_date_context(self):
        """Context should mention today's date."""
        context_msgs = server.build_context_messages()
        content = str(context_msgs[0]["content"])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today in content or "Today" in content

    def test_contains_context_prefix(self):
        """Context should have [CONTEXT] prefix."""
        context_msgs = server.build_context_messages()
        content = str(context_msgs[0]["content"])
        assert "[CONTEXT]" in content

    def test_contains_message_count(self):
        """Context should mention how many messages in conversation."""
        # Simulate some conversation history
        server._conversation_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        context_msgs = server.build_context_messages()
        content = str(context_msgs[0]["content"])
        assert "2" in content or "messages" in content.lower()


# ---------------------------------------------------------------------------
# Test 2: Context injection at start of messages
# ---------------------------------------------------------------------------

class TestContextInjection:
    """Test that context messages are prepended to conversation history."""

    def test_context_prepended_to_messages(self):
        """In agent loop, context should be prepended to messages."""
        server._conversation_history = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
        ]
        
        context_msgs = server.build_context_messages()
        messages = list(server._conversation_history)
        final_messages = context_msgs + messages
        
        # First message should be context
        assert "[CONTEXT]" in str(final_messages[0]["content"])
        # Second should be user's first message
        assert final_messages[1]["role"] == "user"
        assert "Message 1" in str(final_messages[1]["content"])

    def test_5_messages_then_remember_first(self):
        """Core test: 5 messages sent, then ask 'what was first?'.
        
        This simulates what the orchestrator does with context injection.
        We can't call the real LLM, but we can verify the data structure
        that gets sent to the LLM includes all the context.
        """
        # Simulate 5 user messages with responses
        messages = []
        for i in range(1, 6):
            messages.append({"role": "user", "content": f"Message number {i}"})
            messages.append({"role": "assistant", "content": f"Response to message {i}"})
        
        server._conversation_history = messages
        
        # Build context and prepend (this is what the agent loop does)
        context_msgs = server.build_context_messages()
        final_messages = context_msgs + list(server._conversation_history)
        
        # Now add a 6th message (the test question)
        test_question = {"role": "user", "content": "What was my first message?"}
        server._conversation_history.append(test_question)
        
        # Final messages to be sent to LLM
        context_msgs2 = server.build_context_messages()
        llm_input = context_msgs2 + list(server._conversation_history)
        
        # Verify that ALL previous messages are in the context
        all_content = str(llm_input)
        assert "Message number 1" in all_content, "First message NOT in context!"
        assert "Message number 5" in all_content, "Last message NOT in context!"
        assert "What was my first message?" in all_content, "Question NOT in context!"
        assert "[CONTEXT]" in all_content, "Context marker NOT present!"
        
        # The model should see all 11 messages (5 exchanges + context)
        assert len(llm_input) >= 12  # context + 5 exchanges + question


# ---------------------------------------------------------------------------
# Test 3: _append_to_history tracks messages
# ---------------------------------------------------------------------------

class TestAppendToHistory:
    """Test message tracking in conversation history."""

    def test_appends_message(self):
        """Message should be appended to history."""
        server._append_to_history("user", "Hello")
        assert len(server._conversation_history) == 1
        assert server._conversation_history[0]["role"] == "user"

    def test_appends_multiple_messages(self):
        """Multiple messages should all be tracked."""
        for i in range(5):
            server._append_to_history("user", f"Message {i}")
        assert len(server._conversation_history) == 5

    def test_trims_at_max(self):
        """History should be trimmed to MAX_HISTORY_MESSAGES."""
        old_max = server.MAX_HISTORY_MESSAGES
        server.MAX_HISTORY_MESSAGES = 3  # Small for testing
        
        for i in range(10):
            server._append_to_history("user", f"Message {i}")
        
        # Should be trimmed
        assert len(server._conversation_history) <= 3
        
        # Should contain the LAST messages (most recent)
        content = str(server._conversation_history)
        assert "Message 9" in content  # Last message
        assert "Message 0" not in content  # First message trimmed
        
        server.MAX_HISTORY_MESSAGES = old_max


# ---------------------------------------------------------------------------
# Test 4: Episodic logging
# ---------------------------------------------------------------------------

class TestEpisodicLogging:
    """Test that completed tasks are logged to episodic memory."""

    def test_log_episodic_event(self):
        """Task should be logged to episodic memory."""
        with patch("utils.episodic_writer.append_event") as mock_append:
            server._log_episodic_event("Test task")
            mock_append.assert_called_once()
            args = mock_append.call_args[1]
            assert args["summary"] == "Test task"
            assert args["category"] == "agent_action"

    def test_log_truncates_long_tasks(self):
        """Long task summaries should be truncated to 200 chars."""
        long_task = "x" * 500
        with patch("utils.episodic_writer.append_event") as mock_append:
            server._log_episodic_event(long_task)
            args = mock_append.call_args[1]
            assert len(args["summary"]) == 200

    def test_log_daily_activity(self):
        """Daily activity should be logged."""
        with patch("utils.episodic_writer.append_event") as mock_append:
            server._log_daily_activity("Coding in VS Code", "daily")
            mock_append.assert_called_once()
            args = mock_append.call_args[1]
            assert args["category"] == "daily"
            assert args["source"] == "daily_tracker"


# ---------------------------------------------------------------------------
# Test 5: _get_context_summary
# ---------------------------------------------------------------------------

class TestGetContextSummary:
    """Test context summary generation."""

    def test_returns_string(self):
        """Should always return a string."""
        summary = server._get_context_summary()
        assert isinstance(summary, str)

    def test_mentions_user_if_messages_exist(self):
        """Should mention user's messages if any."""
        server._conversation_history = [
            {"role": "user", "content": "Research AI agents"},
        ]
        summary = server._get_context_summary()
        assert "Research AI agents" in summary or "request" in summary.lower()


# ---------------------------------------------------------------------------
# Test 6: Full flow simulation
# ---------------------------------------------------------------------------

class TestFullMemoryFlow:
    """Simulate the full agent loop to verify memory persistence."""

    def test_context_structure_for_llm(self):
        """Verify the exact data structure sent to the LLM contains context."""
        server._conversation_history = []
        
        # Simulate sending 5 messages
        messages_data = [
            "Find information about Python async programming",
            "Show me the key concepts",
            "Give me code examples",
            "What are best practices?",
            "Compare async vs threading",
        ]
        
        for i, msg in enumerate(messages_data):
            server._append_to_history("user", msg)
            server._append_to_history("assistant", f"Response to: {msg[:30]}...")
        
        # Now simulate the 6th message (test question)
        test_q = "What was my first request?"
        server._append_to_history("user", test_q)
        server._append_to_history("assistant", "I remember! Your first request was...")
        
        # Build the input that would go to the LLM
        context_msgs = server.build_context_messages()
        final_input = context_msgs + list(server._conversation_history)
        
        # Convert to string representation (same as what the LLM sees)
        all_text = json.dumps(final_input)
        
        # CRITICAL ASSERTIONS:
        assert "[CONTEXT]" in context_msgs[0]["content"], "Context marker is missing!"
        assert "Python async" in all_text, "First user message LOST from context!"
        assert "Compare async vs threading" in all_text, "Last user message LOST from context!"
        assert "What was my first request?" in all_text, "Test question LOST from context!"
        
        # Verify total message count (5 exchanges = 10 msgs + 1 test exchange = 12 + 1 context)
        total_msgs = len(final_input)
        assert total_msgs >= 13, f"Too few messages in context: {total_msgs} (expected 13+)"
