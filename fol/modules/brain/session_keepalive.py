"""Session Keepalive Watchdog — prevents Freebuff tmux session from dying.

This is a lightweight background task that:
1. Periodically checks if the tmux session is alive
2. Detects if Freebuff process died inside tmux
3. Automatically restarts the session on crash
4. Logs health status for debugging

The watchdog is the "приваска" (safeguard) that ensures the Freebuff
tmux session stays alive even if FOL encounters transient errors.

It does NOT:
- Run tests
- Exit the session
- Modify brain interfaces
- Break existing safety layers

Usage:
    watchdog = SessionKeepalive()
    await watchdog.start()   # launches background monitor
    ...
    await watchdog.stop()    # clean shutdown
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_CHECK_INTERVAL = 10.0   # seconds between health checks
_DEFAULT_MAX_MISSED = 3          # missed checks before restart attempt
_DEFAULT_SESSION_NAME = "fol-freebuff"
_DEFAULT_RESTART_COOLDOWN = 5.0  # seconds between restart attempts


class SessionKeepalive:
    """Background watchdog that keeps a tmux session alive.

    It periodically checks:
    1. Does the tmux session exist?
    2. Is the Freebuff process still running inside it?
    3. Is the TUI responsive (can we capture-pane)?

    If the session dies, it attempts automatic restart.
    """

    def __init__(
        self,
        session_name: Optional[str] = None,
        check_interval: Optional[float] = None,
        max_missed: Optional[int] = None,
        restart_callback: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._session_name = session_name or os.environ.get(
            "FREEBUFF_TMUX_SESSION", _DEFAULT_SESSION_NAME
        )
        self._check_interval = check_interval or _DEFAULT_CHECK_INTERVAL
        self._max_missed = max_missed or _DEFAULT_MAX_MISSED
        self._restart_callback = restart_callback

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._missed_checks = 0
        self._last_healthy: float = 0.0
        self._restart_count = 0
        self._max_restarts = 5
        self._last_restart: float = 0.0
        self._health_log: list[dict[str, Any]] = []

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    @property
    def health_summary(self) -> dict[str, Any]:
        return {
            "running": self.is_running,
            "session_name": self._session_name,
            "last_healthy": self._last_healthy,
            "missed_checks": self._missed_checks,
            "restart_count": self._restart_count,
            "total_checks": len(self._health_log),
        }

    # -- Lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start the background watchdog task."""
        if self._running:
            logger.debug("Keepalive already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(
            "Session keepalive started (session=%s, interval=%.0fs)",
            self._session_name,
            self._check_interval,
        )

    async def stop(self) -> None:
        """Stop the watchdog task gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Session keepalive stopped")

    # -- Monitor loop -------------------------------------------------------

    async def _monitor_loop(self) -> None:
        """Background loop that checks session health."""
        while self._running:
            try:
                await asyncio.sleep(self._check_interval)
                await self._check_health()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Never let the watchdog itself crash the session
                logger.error("Keepalive check error (non-fatal): %s", exc)
                await asyncio.sleep(self._check_interval)

    async def _check_health(self) -> None:
        """Single health check cycle."""
        from modules.brain.freebuff_tmux_session import session_exists, capture_pane

        healthy = False
        details: dict[str, Any] = {}

        try:
            # Check 1: tmux session exists
            if not session_exists(self._session_name):
                details["session_exists"] = False
                self._missed_checks += 1
                logger.warning(
                    "Keepalive: session '%s' not found (missed %d/%d)",
                    self._session_name,
                    self._missed_checks,
                    self._max_missed,
                )
            else:
                details["session_exists"] = True

                # Check 2: can we capture the pane?
                raw = capture_pane(self._session_name)
                if raw:
                    details["capture_ok"] = True
                    healthy = True
                    self._missed_checks = 0
                    self._last_healthy = time.time()
                else:
                    details["capture_ok"] = False
                    self._missed_checks += 1

        except Exception as exc:
            details["error"] = str(exc)
            self._missed_checks += 1

        # Log health record (keep last 100)
        details["healthy"] = healthy
        details["timestamp"] = time.time()
        self._health_log.append(details)
        if len(self._health_log) > 100:
            self._health_log = self._health_log[-100:]

        # If too many missed checks, attempt restart
        if self._missed_checks >= self._max_missed:
            await self._attempt_restart()

    async def _attempt_restart(self) -> None:
        """Attempt to restart the tmux session."""
        now = time.time()

        # Cooldown between restarts
        if (now - self._last_restart) < _DEFAULT_RESTART_COOLDOWN:
            logger.debug("Keepalive: restart cooldown, skipping")
            return

        if self._restart_count >= self._max_restarts:
            logger.error(
                "Keepalive: max restarts (%d) reached for session '%s'",
                self._max_restarts,
                self._session_name,
            )
            return

        self._restart_count += 1
        self._last_restart = now
        self._missed_checks = 0

        logger.warning(
            "Keepalive: attempting restart #%d for session '%s'",
            self._restart_count,
            self._session_name,
        )

        try:
            if self._restart_callback:
                import inspect
                if inspect.iscoroutinefunction(self._restart_callback):
                    await self._restart_callback()
                else:
                    self._restart_callback()
                logger.info("Keepalive: restart callback executed")
            else:
                logger.warning(
                    "Keepalive: no restart callback configured, "
                    "cannot auto-restart"
                )
        except Exception as exc:
            logger.error("Keepalive: restart failed: %s", exc)

    # -- Manual health probe ------------------------------------------------

    def is_healthy(self) -> bool:
        """Quick synchronous health check (for callers outside the loop)."""
        try:
            from modules.brain.freebuff_tmux_session import session_exists
            return session_exists(self._session_name)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_global_keepalive: Optional[SessionKeepalive] = None


def get_keepalive() -> SessionKeepalive:
    """Get or create the global keepalive instance."""
    global _global_keepalive
    if _global_keepalive is None:
        _global_keepalive = SessionKeepalive()
    return _global_keepalive


async def start_keepalive(**kwargs: Any) -> SessionKeepalive:
    """Create and start the global keepalive watchdog."""
    global _global_keepalive
    _global_keepalive = SessionKeepalive(**kwargs)
    await _global_keepalive.start()
    return _global_keepalive


async def stop_keepalive() -> None:
    """Stop the global keepalive watchdog."""
    if _global_keepalive:
        await _global_keepalive.stop()


__all__ = [
    "SessionKeepalive",
    "get_keepalive",
    "start_keepalive",
    "stop_keepalive",
]
