"""Application lifecycle management."""

from __future__ import annotations

import asyncio
import enum
import logging
import signal
from typing import Any

logger = logging.getLogger(__name__)


class AppState(enum.Enum):
    """Application states."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class LifecycleManager:
    """Manages application startup, shutdown, and state transitions."""

    def __init__(self) -> None:
        self._state = AppState.CREATED
        self._startup_hooks: list[Any] = []
        self._shutdown_hooks: list[Any] = []
        self._shutdown_event: asyncio.Event | None = None

    def _get_shutdown_event(self) -> asyncio.Event:
        """Lazy asyncio.Event — avoids crashing when no event loop exists.

        Python 3.9's ``asyncio.Event()`` calls ``get_event_loop()`` which
        raises ``RuntimeError`` if no loop is set (e.g. after a prior
        ``asyncio.run()`` closed the default loop).  We defer creation until
        an async method needs it, when a loop is guaranteed.
        """
        if self._shutdown_event is None:
            self._shutdown_event = asyncio.Event()
        return self._shutdown_event

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == AppState.RUNNING

    def on_startup(self, hook: Any) -> None:
        """Register a startup hook."""
        self._startup_hooks.append(hook)

    def on_shutdown(self, hook: Any) -> None:
        """Register a shutdown hook."""
        self._shutdown_hooks.append(hook)

    async def start(self) -> None:
        """Transition to RUNNING state, executing startup hooks."""
        if self._state not in (AppState.CREATED, AppState.STOPPED):
            logger.warning("Cannot start from state", state=self._state.value)
            return

        self._state = AppState.STARTING
        logger.info("Application starting")

        for hook in self._startup_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as exc:
                logger.error("Startup hook failed", hook=str(hook), error=str(exc))

        self._state = AppState.RUNNING
        logger.info("Application started")

    async def stop(self) -> None:
        """Transition to STOPPED state, executing shutdown hooks."""
        if self._state == AppState.STOPPED:
            return

        self._state = AppState.STOPPING
        logger.info("Application stopping")

        for hook in reversed(self._shutdown_hooks):
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
            except Exception as exc:
                logger.error("Shutdown hook failed", hook=str(hook), error=str(exc))

        self._state = AppState.STOPPED
        self._get_shutdown_event().set()
        logger.info("Application stopped")

    async def wait_for_shutdown(self) -> None:
        """Block until shutdown is requested."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
        await self._get_shutdown_event().wait()
