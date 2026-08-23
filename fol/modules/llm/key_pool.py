"""OpenRouter API Key Pool — N-key rotation with rate-limit auto-switching.

When one key hits a rate limit (429 / quota exceeded), the pool automatically
rotates to the next available key. After a cooldown period, exhausted keys
are recycled back into the pool.

Environment variables:
    OPENROUTER_API_KEY          — primary key
    OPENROUTER_API_KEY_2        — second key
    OPENROUTER_API_KEY_3        — third key
    ... (OPENROUTER_API_KEY_N for N keys)

    OPENROUTER_KEY_COOLDOWN     — seconds before a rate-limited key is
                                  recycled (default: 300 = 5 minutes)
    OPENROUTER_KEY_MAX_RETRIES  — how many times to retry with the same
                                  key before rotating (default: 1)

Usage:
    from modules.llm.key_pool import get_key_pool

    pool = get_key_pool()
    key = pool.get_key()                    # current best key
    pool.mark_rate_limited(key)             # rotate away from this key
    pool.mark_success(key)                  # optional: reset error counter
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_COOLDOWN = 300  # 5 minutes


@dataclass
class _KeyState:
    """Internal state for one API key."""
    key: str
    index: int
    cooldown_until: float = 0.0       # timestamp when key becomes available
    consecutive_failures: int = 0
    total_uses: int = 0
    last_used: float = 0.0

    @property
    def available(self) -> bool:
        """True if this key is not in cooldown."""
        return time.time() >= self.cooldown_until

    @property
    def is_exhausted(self) -> bool:
        """True if this key is currently in cooldown."""
        return not self.available

    def mark_rate_limited(self, cooldown_seconds: float) -> None:
        """Put this key into cooldown."""
        self.cooldown_until = time.time() + cooldown_seconds
        self.consecutive_failures += 1
        logger.warning(
            "Key #%d exhausted — cooldown %.0fs (failures=%d, total_uses=%d)",
            self.index, cooldown_seconds, self.consecutive_failures, self.total_uses,
        )

    def mark_success(self) -> None:
        """Reset failure counter on successful use."""
        self.consecutive_failures = 0
        self.total_uses += 1
        self.last_used = time.time()

    def status_dict(self) -> dict:
        remaining = max(0, self.cooldown_until - time.time())
        return {
            "index": self.index,
            "available": self.available,
            "cooldown_remaining_s": round(remaining, 1),
            "consecutive_failures": self.consecutive_failures,
            "total_uses": self.total_uses,
            "key_preview": f"{self.key[:8]}...{self.key[-4:]}" if len(self.key) > 12 else "***",
        }


class OpenRouterKeyPool:
    """Thread-safe pool of OpenRouter API keys with automatic rotation.

    Keys are loaded from environment variables at construction time.
    The pool picks the next available key, rotating on rate limits.
    """

    def __init__(
        self,
        cooldown: float = _DEFAULT_COOLDOWN,
        *,
        extra_keys: list[str] | None = None,
    ) -> None:
        self._cooldown = cooldown
        self._lock = threading.Lock()
        self._current_index = 0
        self._keys: list[_KeyState] = []
        self._load_keys(extra_keys=extra_keys)

    def _load_keys(self, *, extra_keys: list[str] | None = None) -> None:
        """Discover all OPENROUTER_API_KEY* env vars."""
        # Collect from env: OPENROUTER_API_KEY, OPENROUTER_API_KEY_2, ..., _KEY_N
        collected: list[str] = []
        primary = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if primary:
            collected.append(primary)

        # Keys 2..N — scan env for OPENROUTER_API_KEY_2, _3, ...
        for i in range(2, 100):  # reasonable upper bound
            k = os.environ.get(f"OPENROUTER_API_KEY_{i}", "").strip()
            if k and k not in collected:
                collected.append(k)

        # Also check single OPENROUTER_KEYS= comma-separated (convenience)
        bulk = os.environ.get("OPENROUTER_KEYS", "").strip()
        if bulk:
            for k in bulk.split(","):
                k = k.strip()
                if k and k not in collected:
                    collected.append(k)

        # Extra keys injected programmatically
        if extra_keys:
            for k in extra_keys:
                k = k.strip()
                if k and k not in collected:
                    collected.append(k)

        # Build state objects
        for idx, k in enumerate(collected):
            self._keys.append(_KeyState(key=k, index=idx + 1))

        if self._keys:
            logger.info(
                "OpenRouter key pool loaded: %d key(s), cooldown=%ds",
                len(self._keys), self._cooldown,
            )
        else:
            logger.warning("OpenRouter key pool: no keys found in environment")

    # -- public API --------------------------------------------------------

    @property
    def pool_size(self) -> int:
        """Total number of keys in the pool."""
        return len(self._keys)

    @property
    def available_count(self) -> int:
        """Number of currently available (not in cooldown) keys."""
        with self._lock:
            return sum(1 for k in self._keys if k.available)

    def get_key(self) -> str:
        """Return the current best API key.

        Picks the first available key starting from the current index.
        If no keys are available, returns the one with the shortest
        remaining cooldown (least-wait strategy).

        Also re-reads env vars if they changed (e.g. test monkeypatching).
        """
        with self._lock:
            # Re-sync from env in case vars changed (monkeypatch, etc.)
            self._sync_from_env()

            if not self._keys:
                return ""

            # Try to recycle any expired keys first
            self._recycle_expired()

            # Find next available key starting from current index
            n = len(self._keys)
            for offset in range(n):
                idx = (self._current_index + offset) % n
                state = self._keys[idx]
                if state.available:
                    self._current_index = idx
                    return state.key

            # All exhausted — pick the one with shortest cooldown
            best = min(self._keys, key=lambda s: s.cooldown_until)
            self._current_index = best.index - 1
            remaining = max(0, best.cooldown_until - time.time())
            logger.warning(
                "All %d keys exhausted. Next available in %.0fs (key #%d)",
                n, remaining, best.index,
            )
            return best.key

    def mark_rate_limited(self, key: str) -> str:
        """Mark a key as rate-limited and return the next available key.

        Returns empty string if no keys are left.
        """
        with self._lock:
            for state in self._keys:
                if state.key == key:
                    state.mark_rate_limited(self._cooldown)
                    break

            # Advance to next key
            n = len(self._keys)
            self._current_index = (self._current_index + 1) % n
            self._recycle_expired()

            # Find next available
            for offset in range(n):
                idx = (self._current_index + offset) % n
                if self._keys[idx].available:
                    self._current_index = idx
                    next_key = self._keys[idx].key
                    logger.info(
                        "Rotated to key #%d (of %d)",
                        self._keys[idx].index, n,
                    )
                    return next_key

        # All exhausted — caller will handle
        return key  # return the same key; caller will fail and fall back

    def mark_success(self, key: str) -> None:
        """Mark a key as successfully used (resets failure counter)."""
        with self._lock:
            for state in self._keys:
                if state.key == key:
                    state.mark_success()
                    break

    def status(self) -> dict:
        """Human-readable pool status (no secret keys leaked)."""
        with self._lock:
            return {
                "pool_size": len(self._keys),
                "available": sum(1 for k in self._keys if k.available),
                "current_index": self._current_index + 1,
                "cooldown_s": self._cooldown,
                "keys": [k.status_dict() for k in self._keys],
            }

    def _sync_from_env(self) -> None:
        """Re-read env vars and update key list if changed. Caller must hold lock."""
        current_keys = [s.key for s in self._keys]
        new_keys: list[str] = []

        primary = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if primary:
            new_keys.append(primary)

        for i in range(2, 100):
            k = os.environ.get(f"OPENROUTER_API_KEY_{i}", "").strip()
            if k and k not in new_keys:
                new_keys.append(k)

        bulk = os.environ.get("OPENROUTER_KEYS", "").strip()
        if bulk:
            for k in bulk.split(","):
                k = k.strip()
                if k and k not in new_keys:
                    new_keys.append(k)

        if new_keys != current_keys:
            # Keys changed — rebuild state, preserving cooldown info where possible
            old_state = {s.key: s for s in self._keys}
            self._keys = []
            for idx, k in enumerate(new_keys):
                if k in old_state:
                    old = old_state[k]
                    old.index = idx + 1
                    self._keys.append(old)
                else:
                    self._keys.append(_KeyState(key=k, index=idx + 1))
            self._current_index = min(self._current_index, max(0, len(self._keys) - 1))
            logger.info("Key pool re-synced: %d key(s)", len(self._keys))

    def _recycle_expired(self) -> None:
        """Reset cooldown for any expired keys. Caller must hold lock."""
        now = time.time()
        for state in self._keys:
            if state.cooldown_until > 0 and now >= state.cooldown_until:
                if state.cooldown_until > 0:
                    logger.info("Key #%d recycled (cooldown expired)", state.index)
                state.cooldown_until = 0.0
                state.consecutive_failures = 0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_pool: OpenRouterKeyPool | None = None
_pool_lock = threading.Lock()


def get_key_pool() -> OpenRouterKeyPool:
    """Get or create the global key pool singleton."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                cooldown = float(
                    os.environ.get("OPENROUTER_KEY_COOLDOWN", str(_DEFAULT_COOLDOWN))
                )
                _pool = OpenRouterKeyPool(cooldown=cooldown)
    return _pool


def reset_key_pool() -> None:
    """Reset the global pool (for testing)."""
    global _pool
    with _pool_lock:
        _pool = None


__all__ = [
    "OpenRouterKeyPool",
    "get_key_pool",
    "reset_key_pool",
]
