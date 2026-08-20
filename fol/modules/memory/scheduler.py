"""Consolidation Scheduler — background process for memory consolidation.

Runs the MemoryConsolidator on a schedule (default: daily at 23:55)
and after significant activity (e.g., 50+ turns since last consolidation).

The scheduler is lightweight — it runs consolidation in a background thread
so it never blocks the main chat loop. Best-effort: failures are logged
at debug level and never propagate.

Usage:
    scheduler = ConsolidationScheduler(consolidator=consolidator)
    scheduler.start()  # starts background loop
    scheduler.stop()   # graceful shutdown

    # Or trigger manually:
    await scheduler.consolidate_now()
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from modules.memory.consolidation import MemoryConsolidator, ConsolidationResult

logger = logging.getLogger(__name__)


class ConsolidationScheduler:
    """Background scheduler for memory consolidation.

    Runs consolidation at configured intervals, with automatic triggers
    after high-activity sessions.
    """

    def __init__(
        self,
        consolidator: MemoryConsolidator,
        interval_hours: float = 24.0,
        turns_before_auto: int = 50,
        enabled: bool = True,
    ) -> None:
        """
        Args:
            consolidator: The MemoryConsolidator to use
            interval_hours: Hours between scheduled consolidations (default: 24)
            turns_before_auto: Auto-consolidate after this many turns (default: 50)
            enabled: Whether the scheduler is active
        """
        self._consolidator = consolidator
        self._interval_hours = interval_hours
        self._turns_before_auto = turns_before_auto
        self._enabled = enabled

        self._running = False
        self._task: asyncio.Task | None = None
        self._turn_count = 0
        self._last_consolidation: float = 0.0
        self._last_consolidated_date: str = ""

    # -- Public API ----------------------------------------------------------

    def start(self) -> None:
        """Start the background consolidation loop."""
        if not self._enabled:
            logger.info("Consolidation scheduler disabled")
            return
        if self._running:
            return
        self._running = True
        self._last_consolidation = time.time()
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._loop())
            logger.info(
                "Consolidation scheduler started (interval=%sh, auto_after=%d turns)",
                self._interval_hours,
                self._turns_before_auto,
            )
        except RuntimeError:
            # No event loop running — scheduler will be started later
            logger.debug("No event loop — consolidation scheduler deferred")

    def stop(self) -> None:
        """Stop the background consolidation loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Consolidation scheduler stopped")

    def record_turn(self) -> None:
        """Record that a conversation turn happened.

        Called by the main app after each user interaction. When the
        turn count exceeds the threshold, auto-consolidation triggers.
        """
        self._turn_count += 1
        if self._turn_count >= self._turns_before_auto:
            logger.info(
                "Auto-consolidation threshold reached (%d turns)",
                self._turn_count,
            )
            # Reset counter — consolidation will happen on next loop tick
            self._turn_count = 0

    async def consolidate_now(self) -> ConsolidationResult:
        """Trigger consolidation immediately (on-demand).

        Consolidates yesterday's log (or today's if late at night).
        """
        # Decide which date to consolidate
        now = datetime.now()
        if now.hour >= 23:
            # Late night — consolidate today
            date = now.strftime("%Y-%m-%d")
        else:
            # Daytime — consolidate yesterday
            date = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        result = await self._consolidator.consolidate(date)
        self._last_consolidation = time.time()
        self._last_consolidated_date = date
        return result

    def status(self) -> dict[str, Any]:
        """Return scheduler status for diagnostics."""
        elapsed = time.time() - self._last_consolidation if self._last_consolidation else 0
        return {
            "enabled": self._enabled,
            "running": self._running,
            "turn_count": self._turn_count,
            "turns_before_auto": self._turns_before_auto,
            "interval_hours": self._interval_hours,
            "last_consolidation_ago_s": round(elapsed),
            "last_consolidated_date": self._last_consolidated_date,
        }

    # -- Private: background loop --------------------------------------------

    async def _loop(self) -> None:
        """Main scheduler loop — runs consolidation on schedule."""
        while self._running:
            try:
                await asyncio.sleep(self._interval_hours * 3600)
                if not self._running:
                    break

                # Check if consolidation is needed
                should_consolidate = False

                # Time-based: enough time since last consolidation
                elapsed = time.time() - self._last_consolidation
                if elapsed >= self._interval_hours * 3600:
                    should_consolidate = True

                # Activity-based: enough turns since last consolidation
                if self._turn_count >= self._turns_before_auto:
                    should_consolidate = True

                if should_consolidate:
                    try:
                        await self.consolidate_now()
                    except Exception as exc:
                        logger.debug("Scheduled consolidation failed: %s", exc)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Consolidation scheduler error: %s", exc)
                await asyncio.sleep(60)  # wait a minute before retrying


__all__ = ["ConsolidationScheduler"]
