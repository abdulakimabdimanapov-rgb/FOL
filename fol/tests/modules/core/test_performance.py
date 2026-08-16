"""Tests for performance utilities."""

from __future__ import annotations

import asyncio
import pytest
from modules.core.performance import Timer, LRUCache, RateLimiter, CircuitBreaker, cached


def test_timer_sync():
    with Timer("test") as t:
        pass
    assert t.elapsed >= 0


@pytest.mark.asyncio
async def test_timer_async():
    async with Timer("async_test") as t:
        await asyncio.sleep(0.01)
    assert t.elapsed >= 0.01


def test_lru_cache_get_set():
    cache = LRUCache(max_size=3, ttl=60)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None


def test_lru_cache_max_size():
    cache = LRUCache(max_size=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)  # Should evict "a"
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_lru_cache_invalidate():
    cache = LRUCache()
    cache.set("x", 10)
    assert cache.invalidate("x")
    assert cache.get("x") is None
    assert not cache.invalidate("x")


def test_lru_cache_clear():
    cache = LRUCache()
    cache.set("a", 1)
    cache.set("b", 2)
    cache.clear()
    assert cache.size == 0


def test_rate_limiter():
    limiter = RateLimiter(max_calls=2, period=1.0)
    assert limiter.remaining == 2


@pytest.mark.asyncio
async def test_rate_limiter_acquire():
    limiter = RateLimiter(max_calls=2, period=1.0)
    assert await limiter.acquire()
    assert await limiter.acquire()
    assert not await limiter.acquire()
    assert limiter.remaining == 0


def test_circuit_breaker():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.1)
    assert not cb.is_open
    for _ in range(3):
        cb.record_failure()
    assert cb.is_open
    assert cb.failure_count == 3


def test_circuit_breaker_recovery():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
    cb.record_failure()
    cb.record_failure()
    assert cb.is_open
    import time; time.sleep(0.1)
    assert not cb.is_open


def test_circuit_breaker_success():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    assert cb.failure_count == 0
    assert not cb.is_open


@pytest.mark.asyncio
async def test_cached_decorator():
    call_count = 0

    @cached(ttl=60)
    async def expensive_func(x: int) -> int:
        nonlocal call_count
        call_count += 1
        return x * 2

    result1 = await expensive_func(5)
    result2 = await expensive_func(5)
    assert result1 == 10
    assert result2 == 10
    assert call_count == 1  # Second call was cached
