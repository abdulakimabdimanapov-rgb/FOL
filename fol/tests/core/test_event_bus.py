"""Tests for the EventBus."""

from __future__ import annotations

import asyncio
import pytest
from core.event_bus import Event, EventBus, EventType


@pytest.mark.asyncio
async def test_publish_no_handlers(event_bus: EventBus):
    """Publishing with no handlers should not raise."""
    event = Event(type=EventType.USER_INPUT_RECEIVED, source="test")
    await event_bus.publish(event)


@pytest.mark.asyncio
async def test_publish_with_handler(event_bus: EventBus):
    """Handler should be called when event is published."""
    received = []

    async def handler(event: Event):
        received.append(event)

    event_bus.subscribe(EventType.USER_INPUT_RECEIVED, handler)
    event = Event(type=EventType.USER_INPUT_RECEIVED, source="test", payload={"text": "hello"})
    await event_bus.publish(event)

    assert len(received) == 1
    assert received[0].source == "test"
    assert received[0].payload["text"] == "hello"


@pytest.mark.asyncio
async def test_unsubscribe(event_bus: EventBus):
    """Unsubscribed handler should not be called."""
    received = []

    async def handler(event: Event):
        received.append(event)

    event_bus.subscribe(EventType.USER_INPUT_RECEIVED, handler)
    event_bus.unsubscribe(EventType.USER_INPUT_RECEIVED, handler)
    await event_bus.publish(Event(type=EventType.USER_INPUT_RECEIVED))

    assert len(received) == 0


@pytest.mark.asyncio
async def test_multiple_handlers(event_bus: EventBus):
    """Multiple handlers should all be called."""
    results = []

    async def h1(event: Event):
        results.append("h1")

    async def h2(event: Event):
        results.append("h2")

    event_bus.subscribe(EventType.LLM_RESPONSE_READY, h1)
    event_bus.subscribe(EventType.LLM_RESPONSE_READY, h2)
    await event_bus.publish(Event(type=EventType.LLM_RESPONSE_READY))

    assert results == ["h1", "h2"]


@pytest.mark.asyncio
async def test_event_count(event_bus: EventBus):
    """Event count should increment."""
    assert event_bus.event_count == 0
    await event_bus.publish(Event(type=EventType.USER_INPUT_RECEIVED))
    await event_bus.publish(Event(type=EventType.LLM_RESPONSE_READY))
    assert event_bus.event_count == 2


def test_clear(event_bus: EventBus):
    """Clear should reset everything."""
    event_bus._event_count = 5
    event_bus.clear()
    assert event_bus.event_count == 0
