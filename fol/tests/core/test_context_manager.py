"""Tests for ContextManager."""

from __future__ import annotations

import pytest
from core.context_manager import ContextManager


def test_add_turn(context_manager: ContextManager):
    context_manager.add_turn("hello", "hi there")
    assert context_manager.history_length == 1
    assert context_manager.last_user_input == "hello"
    assert context_manager.last_assistant_response == "hi there"


def test_max_history(context_manager: ContextManager):
    cm = ContextManager(max_history=3)
    for i in range(5):
        cm.add_turn(f"q{i}", f"a{i}")
    assert cm.history_length == 3
    assert cm.last_user_input == "q4"


def test_get_recent_context(context_manager: ContextManager):
    context_manager.add_turn("hello", "hi")
    context_manager.add_turn("how are you?", "good")
    ctx = context_manager.get_recent_context(n=1)
    assert "how are you?" in ctx


def test_empty_context(context_manager: ContextManager):
    ctx = context_manager.get_recent_context()
    assert "No recent" in ctx


def test_working_memory(context_manager: ContextManager):
    context_manager.set_working_memory("key", "value")
    assert context_manager.get_working_memory("key") == "value"
    context_manager.clear_working_memory()
    assert context_manager.get_working_memory("key") is None
