"""Brain Startup Manager — handles initialization and lifecycle of brain backends.

Coordinates:
- Freebuff brain availability check (via OpenRouter)
- Health checks and monitoring
- Fallback routing (Freebuff → OpenRouter → other providers)
- UI status updates

The brain startup flow:
1. Check if Freebuff is available via OpenRouter
2. If available, use FreebuffBrainAdapter (primary)
3. If unavailable, fall back to CurrentLLMAdapter (API providers)
4. Monitor health and switch on failure
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional, Callable, Any

from modules.llm.brain import BrainInterface, BrainConfigurationError
from modules.brain.freebuff_process import FreebuffProcessManager, BrainProcessState
from modules.brain.freebuff_adapter import FreebuffBrainAdapter

logger = logging.getLogger(__name__)


class BrainStartupManager:
    """Manage brain backend startup and health.

    Initializes the brain chain: Freebuff (primary) → Current (fallback).
    Monitors health and handles switching on failure.
    """

    def __init__(
        self,
        *,
        primary_brain: str = "freebuff",
        fallback_brains: list[str] | None = None,
        auto_start: bool = True,
        status_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> None:
        """Initialize brain startup manager.

        Args:
            primary_brain: Name of primary brain backend (default: freebuff)
            fallback_brains: List of fallback brain names in order
            auto_start: Automatically start primary brain if available
            status_callback: Callback when brain status changes
        """
        self.primary_brain = primary_brain or "freebuff"
        self.fallback_brains = fallback_brains or ["current"]
        self.auto_start = auto_start
        self.status_callback = status_callback

        # Process managers by brain name
        self._process_managers: dict[str, FreebuffProcessManager] = {}
        self._adapters: dict[str, BrainInterface] = {}
        self._active_brain: Optional[BrainInterface] = None
        self._lock = asyncio.Lock()

        # Initialize process manager for Freebuff
        if self.primary_brain == "freebuff":
            self._process_managers["freebuff"] = FreebuffProcessManager(
                auto_start=self.auto_start,
                status_callback=status_callback,
            )

    async def initialize(self) -> BrainInterface:
        """Initialize brain backends and return active brain.

        Returns the first available brain (primary or fallback).
        Raises BrainConfigurationError if no brain is available.
        """
        async with self._lock:
            # Try primary brain
            if await self._initialize_brain(self.primary_brain):
                return self._active_brain

            # Try fallback brains
            for brain_name in self.fallback_brains:
                logger.warning(
                    "Primary brain %r unavailable, trying fallback: %r",
                    self.primary_brain,
                    brain_name,
                )
                if await self._initialize_brain(brain_name):
                    await self._notify_status("fallback")
                    return self._active_brain

            # No brain available
            raise BrainConfigurationError(
                f"No brain available. Primary: {self.primary_brain}, "
                f"Fallback: {self.fallback_brains}"
            )

    async def _initialize_brain(self, brain_name: str) -> bool:
        """Initialize a specific brain.

        Returns True if successful and brain is available.
        """
        try:
            # Start process/health check if needed
            if brain_name in self._process_managers:
                manager = self._process_managers[brain_name]
                logger.info("Checking Freebuff brain availability...")
                if not await manager.start():
                    logger.error("Freebuff brain unavailable")
                    await self._notify_status("startup_failed")
                    return False

            # Get or create adapter
            if brain_name == "freebuff":
                adapter = FreebuffBrainAdapter()
            else:
                # For other brains (e.g., "current"), import lazily
                from modules.llm.brain import get_brain

                adapter = get_brain(brain_name)

            # Check if adapter is actually available
            if not adapter.available:
                logger.warning("Brain adapter %r is not available", brain_name)
                return False

            self._adapters[brain_name] = adapter
            self._active_brain = adapter
            logger.info("Brain initialized: %s", brain_name)
            await self._notify_status("ready", brain=brain_name)
            return True

        except Exception as exc:
            logger.error("Failed to initialize brain %r: %s", brain_name, exc)
            return False

    async def shutdown(self) -> None:
        """Shutdown all managed brains and processes."""
        async with self._lock:
            logger.info("Shutting down brain backends...")

            # Stop process managers
            for manager in self._process_managers.values():
                try:
                    await manager.stop()
                except Exception as exc:
                    logger.error("Error stopping brain process: %s", exc)

            # Cleanup adapters
            for adapter in self._adapters.values():
                if hasattr(adapter, "cleanup"):
                    try:
                        await adapter.cleanup()
                    except Exception as exc:
                        logger.error("Error cleaning up adapter: %s", exc)

            self._active_brain = None
            await self._notify_status("stopped")

    async def health_check(self) -> dict[str, Any]:
        """Perform health check on active brain.

        Returns status dict.
        """
        if not self._active_brain:
            return {
                "status": "offline",
                "reason": "No brain initialized",
            }

        try:
            status = self._active_brain.status()
            status["timestamp"] = time.time()
            return status
        except Exception as exc:
            return {
                "status": "error",
                "reason": str(exc),
            }

    async def get_active_brain(self) -> BrainInterface:
        """Get the currently active brain."""
        if not self._active_brain:
            raise BrainConfigurationError("No brain initialized")
        return self._active_brain

    async def switch_brain(self, brain_name: str) -> BrainInterface:
        """Switch to a different brain backend.

        Raises BrainConfigurationError if the target brain is unavailable.
        """
        async with self._lock:
            if await self._initialize_brain(brain_name):
                return self._active_brain
            raise BrainConfigurationError(
                f"Brain {brain_name!r} is not available"
            )

    async def _notify_status(
        self, event: str, brain: Optional[str] = None, **kwargs: Any
    ) -> None:
        """Notify listener of status change."""
        if self.status_callback:
            try:
                status = {
                    "event": event,
                    "brain": brain or self.primary_brain,
                    "timestamp": time.time(),
                    **kwargs,
                }
                if asyncio.iscoroutinefunction(self.status_callback):
                    await self.status_callback(status)
                else:
                    self.status_callback(status)
            except Exception as exc:
                logger.error("Error in status callback: %s", exc)

    def get_process_status(self, brain_name: str = "freebuff") -> Optional[dict]:
        """Get process status for a brain."""
        if brain_name not in self._process_managers:
            return None
        manager = self._process_managers[brain_name]
        return manager.status.to_dict()


__all__ = ["BrainStartupManager"]
