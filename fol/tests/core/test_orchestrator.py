"""Tests for Orchestrator."""

from __future__ import annotations

import pytest
from core.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_simple_process(orchestrator: Orchestrator):
    """Should handle basic commands without LLM."""
    response = await orchestrator.process_input("hello")
    # No robotic "sir"/"service" boilerplate — a natural greeting.
    assert "sir" not in response.lower()
    assert len(response) > 10


@pytest.mark.asyncio
async def test_help_command(orchestrator: Orchestrator):
    response = await orchestrator.process_input("help")
    assert "commands" in response.lower()


@pytest.mark.asyncio
async def test_time_command(orchestrator: Orchestrator):
    response = await orchestrator.process_input("time")
    assert ":" in response


@pytest.mark.asyncio
async def test_date_command(orchestrator: Orchestrator):
    response = await orchestrator.process_input("date")
    assert "20" in response


@pytest.mark.asyncio
async def test_unknown_command(orchestrator: Orchestrator):
    response = await orchestrator.process_input("xyz123")
    assert "didn't" in response.lower()
    assert "sir" not in response.lower()
