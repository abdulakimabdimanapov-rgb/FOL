"""Tests for LifecycleManager."""

from __future__ import annotations

import asyncio
import pytest
from core.lifecycle import AppState, LifecycleManager


@pytest.mark.asyncio
async def test_lifecycle_start_stop():
    lm = LifecycleManager()
    assert lm.state == AppState.CREATED
    await lm.start()
    assert lm.state == AppState.RUNNING
    assert lm.is_running
    await lm.stop()
    assert lm.state == AppState.STOPPED


@pytest.mark.asyncio
async def test_startup_hook():
    lm = LifecycleManager()
    called = []

    def hook():
        called.append(True)

    lm.on_startup(hook)
    await lm.start()
    assert called == [True]


@pytest.mark.asyncio
async def test_shutdown_hook():
    lm = LifecycleManager()
    called = []

    def hook():
        called.append(True)

    lm.on_shutdown(hook)
    await lm.start()
    await lm.stop()
    assert called == [True]


@pytest.mark.asyncio
async def test_async_hooks():
    lm = LifecycleManager()
    called = []

    async def hook():
        called.append(True)

    lm.on_startup(hook)
    lm.on_shutdown(hook)
    await lm.start()
    await lm.stop()
    assert called == [True, True]
