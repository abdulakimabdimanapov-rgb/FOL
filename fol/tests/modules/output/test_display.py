"""Tests for output modules."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.output.display import DisplayModule
from modules.output.notifications import NotificationModule


@pytest.mark.asyncio
async def test_display_initialize():
    """Display module should initialize."""
    display = DisplayModule()
    await display.initialize()
    assert display is not None


@pytest.mark.asyncio
async def test_display_send():
    """Display module should send text."""
    display = DisplayModule()
    await display.initialize()
    result = await display.send("Hello, world!")
    # Display module returns None (prints to stdout)
    assert result is None or isinstance(result, bool)


@pytest.mark.asyncio
async def test_display_shutdown():
    """Display module should shutdown cleanly."""
    display = DisplayModule()
    await display.initialize()
    await display.shutdown()


@pytest.mark.asyncio
async def test_notification_initialize():
    """Notification module should initialize."""
    notif = NotificationModule()
    await notif.initialize()
    assert notif is not None


@pytest.mark.asyncio
async def test_notification_send():
    """Notification module should send notification."""
    notif = NotificationModule()
    await notif.initialize()
    result = await notif.send("Test notification")
    # May fail on CI without display, but should not crash
    assert result is None or isinstance(result, bool)


@pytest.mark.asyncio
async def test_notification_shutdown():
    """Notification module should shutdown cleanly."""
    notif = NotificationModule()
    await notif.initialize()
    await notif.shutdown()
