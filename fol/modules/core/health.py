"""Health check and diagnostics."""

from __future__ import annotations

import asyncio
import logging
import platform
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

START_TIME = time.time()


@dataclass
class HealthStatus:
    """Health status of a component."""

    name: str = ""
    status: str = "unknown"  # "healthy", "degraded", "unhealthy"
    message: str = ""
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemHealth:
    """Overall system health."""

    status: str = "healthy"
    uptime_seconds: float = 0.0
    version: str = "0.1.0"
    platform: str = ""
    components: list[HealthStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "uptime_seconds": round(self.uptime_seconds, 1),
            "version": self.version,
            "platform": self.platform,
            "components": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "latency_ms": round(c.latency_ms, 1),
                }
                for c in self.components
            ],
        }


class HealthChecker:
    """Checks health of all FOL components."""

    def __init__(self) -> None:
        self._checks: dict[str, Any] = {}

    def register(self, name: str, check_func: Any) -> None:
        """Register a health check function."""
        self._checks[name] = check_func

    async def check_all(self) -> SystemHealth:
        """Run all health checks."""
        health = SystemHealth(
            uptime_seconds=time.time() - START_TIME,
            platform=f"{platform.system()} {platform.release()}",
        )

        overall_healthy = True
        for name, check_func in self._checks.items():
            start = time.perf_counter()
            try:
                if asyncio.iscoroutinefunction(check_func):
                    result = await asyncio.wait_for(check_func(), timeout=5.0)
                else:
                    result = check_func()
                latency = (time.perf_counter() - start) * 1000
                health.components.append(HealthStatus(
                    name=name,
                    status="healthy",
                    message=str(result) if result else "OK",
                    latency_ms=latency,
                ))
            except asyncio.TimeoutError:
                health.components.append(HealthStatus(
                    name=name, status="degraded", message="Timeout",
                ))
                overall_healthy = False
            except Exception as exc:
                health.components.append(HealthStatus(
                    name=name, status="unhealthy", message=str(exc),
                ))
                overall_healthy = False

        health.status = "healthy" if overall_healthy else "degraded"
        return health

    async def check_component(self, name: str) -> HealthStatus:
        """Check a single component."""
        check_func = self._checks.get(name)
        if check_func is None:
            return HealthStatus(name=name, status="unknown", message="Not registered")

        start = time.perf_counter()
        try:
            if asyncio.iscoroutinefunction(check_func):
                result = await asyncio.wait_for(check_func(), timeout=5.0)
            else:
                result = check_func()
            latency = (time.perf_counter() - start) * 1000
            return HealthStatus(name=name, status="healthy", message=str(result) if result else "OK", latency_ms=latency)
        except Exception as exc:
            return HealthStatus(name=name, status="unhealthy", message=str(exc))
