"""Performance utilities — timing, caching, profiling."""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections import OrderedDict
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Timer:
    """Context manager for timing operations."""

    def __init__(self, name: str = "operation") -> None:
        self.name = name
        self.start: float = 0.0
        self.end: float = 0.0
        self.elapsed: float = 0.0

    def __enter__(self) -> Timer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.end = time.perf_counter()
        self.elapsed = self.end - self.start
        logger.info("Timer [%s]: %.3fs", self.name, self.elapsed)

    async def __aenter__(self) -> Timer:
        self.start = time.perf_counter()
        return self

    async def __aexit__(self, *args: Any) -> None:
        self.end = time.perf_counter()
        self.elapsed = self.end - self.start
        logger.info("Timer [%s]: %.3fs", self.name, self.elapsed)


class LRUCache:
    """Simple LRU cache with TTL support."""

    def __init__(self, max_size: int = 128, ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._ttl = ttl
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        """Get a value from cache. Returns None if expired or missing."""
        if key not in self._cache:
            return None
        value, timestamp = self._cache[key]
        if time.time() - timestamp > self._ttl:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        """Set a value in cache."""
        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)
        self._cache[key] = (value, time.time())

    def invalidate(self, key: str) -> bool:
        """Remove a key from cache."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


def cached(ttl: float = 300.0, max_size: int = 128) -> Callable:
    """Decorator that caches async function results."""

    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        cache = LRUCache(max_size=max_size, ttl=ttl)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            # Build cache key from args (skip 'self')
            key_parts = [str(a) for a in args[1:]] + [f"{k}={v}" for k, v in sorted(kwargs.items())]
            key = f"{func.__name__}:{':'.join(key_parts)}"

            result = cache.get(key)
            if result is not None:
                return result

            result = await func(*args, **kwargs)
            cache.set(key, result)
            return result

        wrapper.cache = cache  # type: ignore
        return wrapper

    return decorator


class RateLimiter:
    """Simple rate limiter."""

    def __init__(self, max_calls: int = 10, period: float = 1.0) -> None:
        self._max_calls = max_calls
        self._period = period
        self._calls: list[float] = []

    async def acquire(self) -> bool:
        """Try to acquire a rate limit slot. Returns True if allowed."""
        now = time.time()
        self._calls = [t for t in self._calls if now - t < self._period]
        if len(self._calls) < self._max_calls:
            self._calls.append(now)
            return True
        return False

    async def wait(self) -> None:
        """Wait until a slot is available."""
        while not await self.acquire():
            await asyncio.sleep(0.05)

    @property
    def remaining(self) -> int:
        """Remaining calls in current period."""
        now = time.time()
        self._calls = [t for t in self._calls if now - t < self._period]
        return max(0, self._max_calls - len(self._calls))


class CircuitBreaker:
    """Circuit breaker for fault tolerance."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count: int = 0
        self._last_failure_time: float = 0.0
        self._is_open: bool = False

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing)."""
        if self._is_open:
            if time.time() - self._last_failure_time > self._recovery_timeout:
                self._is_open = False
                self._failure_count = 0
                logger.info("Circuit breaker recovered")
        return self._is_open

    def record_success(self) -> None:
        """Record a successful call."""
        self._failure_count = 0
        self._is_open = False

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self._failure_threshold:
            self._is_open = True
            logger.warning("Circuit breaker opened after %d failures", self._failure_count)

    @property
    def failure_count(self) -> int:
        return self._failure_count
