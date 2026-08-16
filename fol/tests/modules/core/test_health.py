"""Tests for health checker."""

from __future__ import annotations

import pytest
from modules.core.health import HealthChecker


@pytest.mark.asyncio
async def test_health_check_empty():
    hc = HealthChecker()
    health = await hc.check_all()
    assert health.status == "healthy"
    assert health.uptime_seconds >= 0


@pytest.mark.asyncio
async def test_health_check_healthy():
    hc = HealthChecker()
    hc.register("test", lambda: "OK")
    health = await hc.check_all()
    assert len(health.components) == 1
    assert health.components[0].status == "healthy"


@pytest.mark.asyncio
async def test_health_check_unhealthy():
    def fail():
        raise Exception("test failure")

    hc = HealthChecker()
    hc.register("failing", fail)
    health = await hc.check_all()
    assert health.status == "degraded"
    assert health.components[0].status == "unhealthy"


@pytest.mark.asyncio
async def test_check_single_component():
    hc = HealthChecker()
    hc.register("test", lambda: "works")
    status = await hc.check_component("test")
    assert status.status == "healthy"
    assert "works" in status.message


@pytest.mark.asyncio
async def test_check_unregistered():
    hc = HealthChecker()
    status = await hc.check_component("unknown")
    assert status.status == "unknown"
