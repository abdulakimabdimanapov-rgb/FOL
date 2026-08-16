"""Preferences store — user preferences and settings."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from config.constants import FOL_DIR

logger = logging.getLogger(__name__)


class PreferencesStore:
    """Stores user preferences with persistence."""

    def __init__(self, prefs_path: Path | None = None) -> None:
        self._path = prefs_path or (FOL_DIR / "preferences.json")
        self._prefs: dict[str, Any] = {}

    async def initialize(self) -> None:
        """Load preferences from disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                self._prefs = json.loads(self._path.read_text(encoding="utf-8"))
                logger.info("Preferences loaded", count=len(self._prefs))
            except Exception as exc:
                logger.error("Failed to load preferences", error=str(exc))

    async def shutdown(self) -> None:
        """Save preferences to disk."""
        await self.save()

    async def save(self) -> None:
        """Persist preferences."""
        try:
            self._path.write_text(json.dumps(self._prefs, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save preferences", error=str(exc))

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        return self._prefs.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        """Set a preference value."""
        self._prefs[key] = value
        await self.save()

    async def delete(self, key: str) -> bool:
        """Delete a preference."""
        if key in self._prefs:
            del self._prefs[key]
            await self.save()
            return True
        return False

    async def get_all(self) -> dict[str, Any]:
        """Get all preferences."""
        return self._prefs.copy()

    async def set_defaults(self, defaults: dict[str, Any]) -> None:
        """Set default values (won't overwrite existing)."""
        for key, value in defaults.items():
            if key not in self._prefs:
                self._prefs[key] = value
        await self.save()

    @property
    def count(self) -> int:
        return len(self._prefs)
