"""Freebuff Process Manager — CLI detection and OpenRouter health monitoring.

Freebuff has no daemon mode or HTTP server. This manager:

1. Detects whether the Freebuff CLI is installed (informational)
2. Monitors OpenRouter connectivity (the real integration path)
3. Tracks brain state for UI status updates
4. Does NOT spawn processes or manage daemons

The "process" in this context is the OpenRouter connection — Freebuff's
models are accessed via OpenRouter's API, not through a local process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any

import aiohttp

logger = logging.getLogger(__name__)


class BrainProcessState(Enum):
    """Brain process lifecycle states."""

    UNKNOWN = "unknown"  # Initial state
    STARTING = "starting"  # Checking availability
    READY = "ready"  # OpenRouter connected, models available
    BUSY = "busy"  # Processing request
    ERROR = "error"  # Runtime error (e.g. API key invalid)
    CRASHED = "crashed"  # Connection lost
    STOPPING = "stopping"  # Graceful shutdown in progress
    STOPPED = "stopped"  # Shut down


@dataclass
class BrainProcessStatus:
    """Current status of the brain process."""

    state: BrainProcessState = BrainProcessState.UNKNOWN
    pid: Optional[int] = None
    uptime_seconds: float = 0.0
    last_health_check: Optional[float] = None
    error_message: Optional[str] = None
    restart_count: int = 0
    owned_by_fol: bool = True  # FOL manages the OpenRouter connection
    cli_installed: bool = False  # Is the Freebuff CLI available?
    openrouter_configured: bool = False  # Is OPENROUTER_API_KEY set?
    model: str = ""  # Primary model name

    def is_alive(self) -> bool:
        """Is the brain responding and healthy?"""
        return self.state in (BrainProcessState.READY, BrainProcessState.BUSY)

    def to_dict(self) -> dict:
        """Serialize for API/logging."""
        return {
            "state": self.state.value,
            "pid": self.pid,
            "uptime_seconds": self.uptime_seconds,
            "last_health_check": self.last_health_check,
            "error_message": self.error_message,
            "restart_count": self.restart_count,
            "owned_by_fol": self.owned_by_fol,
            "cli_installed": self.cli_installed,
            "openrouter_configured": self.openrouter_configured,
            "model": self.model,
        }


class FreebuffProcessManager:
    """Manage brain process lifecycle — monitors OpenRouter connectivity.

    Does NOT spawn processes. Freebuff's models are accessed through
    OpenRouter's API. This manager:
    - Checks if the Freebuff CLI is installed (informational)
    - Monitors OpenRouter API health
    - Tracks brain state for UI updates
    """

    def __init__(
        self,
        *,
        health_check_interval: float = 30.0,
        health_check_timeout: float = 5.0,
        auto_start: bool = True,
        max_restart_attempts: int = 3,
        restart_backoff_seconds: float = 2.0,
        status_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        """Initialize brain process manager.

        Args:
            health_check_interval: Seconds between health checks
            health_check_timeout: Timeout for individual health check
            auto_start: Automatically check availability on init
            max_restart_attempts: Max reconnect attempts before giving up
            restart_backoff_seconds: Delay between reconnect attempts
            status_callback: Callback when status changes
        """
        self.health_check_interval = health_check_interval
        self.health_check_timeout = health_check_timeout
        self.auto_start = auto_start
        self.max_restart_attempts = max_restart_attempts
        self.restart_backoff_seconds = restart_backoff_seconds
        self.status_callback = status_callback

        self._status = BrainProcessStatus(state=BrainProcessState.UNKNOWN)
        self._health_check_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._start_time: Optional[float] = None
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def status(self) -> BrainProcessStatus:
        """Current process status."""
        return self._status

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> bool:
        """Check brain availability and start monitoring.

        Returns True if brain is available.
        """
        async with self._lock:
            self._status = BrainProcessStatus(state=BrainProcessState.STARTING)
            self._start_time = time.time()

            # Check CLI installation (informational)
            self._status.cli_installed = self._check_cli_installed()

            # Check OpenRouter configuration
            self._status.openrouter_configured = self._check_openrouter_config()

            # Check primary model
            self._status.model = os.environ.get(
                "FOL_BRAIN_MODEL", "openrouter/deepseek/deepseek-v4-flash"
            )

            # Initial health check
            if self._status.openrouter_configured:
                if await self._health_check():
                    self._status.state = BrainProcessState.READY
                    logger.info(
                        "Brain ready: model=%s, openrouter=%s, cli=%s",
                        self._status.model,
                        self._status.openrouter_configured,
                        self._status.cli_installed,
                    )
                    await self._notify_status("ready")
                    # Start background monitoring
                    if (
                        not self._health_check_task
                        or self._health_check_task.done()
                    ):
                        self._health_check_task = asyncio.create_task(
                            self._health_check_loop()
                        )
                    return True

            # Not available
            self._status.state = BrainProcessState.ERROR
            if not self._status.openrouter_configured:
                self._status.error_message = "OPENROUTER_API_KEY not configured"
            else:
                self._status.error_message = "OpenRouter health check failed"
            logger.warning("Brain unavailable: %s", self._status.error_message)
            await self._notify_status("unavailable")
            return False

    async def stop(self) -> None:
        """Stop monitoring and clean up."""
        async with self._lock:
            self._status.state = BrainProcessState.STOPPING

            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass

            if self._session:
                await self._session.close()
                self._session = None

            self._status.state = BrainProcessState.STOPPED
            await self._notify_status("stopped")

    async def health_check(self) -> bool:
        """Perform a health check on the brain.

        Returns True if the brain is responding and healthy.
        """
        return await self._health_check()

    async def get_active_brain(self) -> Optional[str]:
        """Get the currently active brain name."""
        if self._status.is_alive():
            return "freebuff"
        return None

    # -- Internal -----------------------------------------------------------

    def _check_cli_installed(self) -> bool:
        """Check if the Freebuff CLI is installed (informational)."""
        freebuff_path = shutil.which("freebuff")
        if freebuff_path:
            logger.debug("Freebuff CLI found at: %s", freebuff_path)
            return True

        # Also check via npx
        try:
            result = subprocess.run(
                ["npx", "freebuff", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.debug("Freebuff CLI available via npx")
                return True
        except Exception:
            pass

        logger.debug("Freebuff CLI not found")
        return False

    def _check_openrouter_config(self) -> bool:
        """Check if OpenRouter is configured for Freebuff models."""
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            return False

        # Check that the primary model has a key
        from modules.llm.router import api_key_for_model

        model = os.environ.get(
            "FOL_BRAIN_MODEL", "openrouter/deepseek/deepseek-v4-flash"
        )
        return api_key_for_model(model) is not None

    async def _health_check(self) -> bool:
        """Check OpenRouter connectivity by listing models."""
        if not self._session:
            self._session = aiohttp.ClientSession()

        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            return False

        try:
            async with self._session.get(
                "https://openrouter.ai/api/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=self.health_check_timeout),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Check that at least one Freebuff model is available
                    models = data.get("data", [])
                    freebuff_models = [
                        m for m in models
                        if any(
                            name in m.get("id", "").lower()
                            for name in ["deepseek", "mimo", "nemotron", "minimax"]
                        )
                    ]
                    if freebuff_models:
                        self._status.last_health_check = time.time()
                        self._status.uptime_seconds = (
                            time.time() - (self._start_time or time.time())
                        )
                        logger.debug(
                            "Health check passed: %d Freebuff models available",
                            len(freebuff_models),
                        )
                        return True
                    logger.warning(
                        "Health check: OpenRouter OK but no Freebuff models found"
                    )
                    return False
                else:
                    logger.warning("Health check failed: HTTP %d", resp.status)
                    return False
        except asyncio.TimeoutError:
            logger.warning("Health check timeout")
            self._status.error_message = "OpenRouter health check timeout"
            return False
        except aiohttp.ClientError as exc:
            logger.warning("Health check error: %s", exc)
            self._status.error_message = str(exc)
            return False
        except Exception as exc:
            logger.error("Unexpected health check error: %s", exc)
            self._status.error_message = str(exc)
            return False

    async def _health_check_loop(self) -> None:
        """Periodic health check loop with crash detection and recovery."""
        consecutive_failures = 0

        while True:
            try:
                await asyncio.sleep(self.health_check_interval)

                if not self._status.is_alive():
                    continue

                if await self._health_check():
                    consecutive_failures = 0
                    continue

                consecutive_failures += 1
                logger.warning(
                    "Brain health check failed (%d consecutive)", consecutive_failures
                )

                if consecutive_failures >= 3:
                    logger.error("Brain unhealthy, attempting reconnect")
                    await self._reconnect()
                    consecutive_failures = 0

            except asyncio.CancelledError:
                logger.debug("Health check loop cancelled")
                break
            except Exception as exc:
                logger.error("Unexpected error in health check loop: %s", exc)
                await asyncio.sleep(1.0)

    async def _reconnect(self) -> None:
        """Attempt to reconnect to OpenRouter."""
        if self._status.restart_count >= self.max_restart_attempts:
            logger.warning("Max reconnect attempts exceeded")
            self._status.state = BrainProcessState.ERROR
            self._status.error_message = "Max reconnect attempts exceeded"
            await self._notify_status("error")
            return

        self._status.restart_count += 1
        logger.info(
            "Reconnecting (attempt %d/%d)",
            self._status.restart_count,
            self.max_restart_attempts,
        )
        await asyncio.sleep(self.restart_backoff_seconds)

        if await self._health_check():
            self._status.state = BrainProcessState.READY
            self._status.error_message = None
            await self._notify_status("reconnected")
        else:
            self._status.state = BrainProcessState.ERROR
            self._status.error_message = "Reconnect failed"

    async def _notify_status(self, event: str, **kwargs: Any) -> None:
        """Notify listener of status change."""
        if self.status_callback:
            try:
                status = {
                    "event": event,
                    "brain": "freebuff",
                    "timestamp": time.time(),
                    **kwargs,
                }
                if asyncio.iscoroutinefunction(self.status_callback):
                    await self.status_callback(status)
                else:
                    self.status_callback(status)
            except Exception as exc:
                logger.error("Error in status callback: %s", exc)


__all__ = [
    "FreebuffProcessManager",
    "BrainProcessState",
    "BrainProcessStatus",
]
