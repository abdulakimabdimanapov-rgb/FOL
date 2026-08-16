"""Pytest fixtures for FOL tests."""

from __future__ import annotations

import os

import pytest

from core.event_bus import EventBus
from core.lifecycle import LifecycleManager
from core.task_manager import TaskManager
from core.context_manager import ContextManager
from core.orchestrator import Orchestrator


@pytest.fixture(autouse=True)
def _disable_brain_for_tests():
    """Keep unit tests hermetic: the Freebuff Brain must never write into the
    real user Obsidian vault while tests run. Tests that exercise Brain
    itself construct it with an explicit tmp_path vault."""
    os.environ["FOL_BRAIN_ENABLED"] = "0"
    yield
    os.environ.pop("FOL_BRAIN_ENABLED", None)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def lifecycle() -> LifecycleManager:
    return LifecycleManager()


@pytest.fixture
def task_manager() -> TaskManager:
    return TaskManager()


@pytest.fixture
def context_manager() -> ContextManager:
    return ContextManager()


@pytest.fixture
def orchestrator(event_bus: EventBus, task_manager: TaskManager, context_manager: ContextManager) -> Orchestrator:
    return Orchestrator(event_bus=event_bus, task_manager=task_manager, context_manager=context_manager)
