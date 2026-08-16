"""Integration tests — full cycle tests for FOL."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.event_bus import EventBus, EventType
from core.context_manager import ContextManager
from core.task_manager import TaskManager
from core.orchestrator import Orchestrator


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def task_manager():
    return TaskManager()


@pytest.fixture
def context_manager():
    return ContextManager()


@pytest.fixture
def orchestrator(event_bus, task_manager, context_manager):
    return Orchestrator(
        event_bus=event_bus,
        task_manager=task_manager,
        context_manager=context_manager,
    )


@pytest.mark.asyncio
async def test_orchestrator_processes_input(orchestrator):
    """Orchestrator should process text input and return a response."""
    response = await orchestrator.process_input("hello")
    assert isinstance(response, str)
    assert len(response) > 0


@pytest.mark.asyncio
async def test_orchestrator_handles_unknown_input(orchestrator):
    """Orchestrator should handle unknown input gracefully."""
    response = await orchestrator.process_input("asdfghjkl")
    assert isinstance(response, str)
    # Natural, honorific-free fallback — never a bare "Done."/"OK".
    assert "didn't" in response.lower() or "error" in response.lower()
    assert "sir" not in response.lower()


@pytest.mark.asyncio
async def test_orchestrator_time_command(orchestrator):
    """Orchestrator should return current time."""
    response = await orchestrator.process_input("time")
    assert isinstance(response, str)
    assert ":" in response  # Time format HH:MM:SS


@pytest.mark.asyncio
async def test_orchestrator_date_command(orchestrator):
    """Orchestrator should return current date."""
    response = await orchestrator.process_input("date")
    assert isinstance(response, str)


@pytest.mark.asyncio
async def test_orchestrator_help_command(orchestrator):
    """Orchestrator should return help text."""
    response = await orchestrator.process_input("help")
    assert isinstance(response, str)
    assert "commands" in response.lower()


@pytest.mark.asyncio
async def test_event_bus_publishes_during_processing(orchestrator, event_bus):
    """Event bus should receive events during input processing."""
    received_events = []

    async def handler(event):
        received_events.append(event)

    event_bus.subscribe(EventType.USER_INPUT_RECEIVED, handler)
    event_bus.subscribe(EventType.LLM_RESPONSE_READY, handler)

    await orchestrator.process_input("hello")

    # Should have received at least input and response events
    assert len(received_events) >= 1
    event_bus.unsubscribe(EventType.USER_INPUT_RECEIVED, handler)
    event_bus.unsubscribe(EventType.LLM_RESPONSE_READY, handler)


@pytest.mark.asyncio
async def test_context_manager_stores_turns(context_manager):
    """Context manager should store conversation turns."""
    context_manager.add_turn("Hello", "Hi there!")
    context_manager.add_turn("How are you?", "I'm fine!")

    recent = context_manager.get_recent_context()
    assert len(recent) > 0


@pytest.mark.asyncio
async def test_task_manager_creates_tasks(task_manager):
    """Task manager should create and track tasks."""
    task = task_manager.create_task("test_task", "Test description")
    assert task is not None
    assert task.id is not None
