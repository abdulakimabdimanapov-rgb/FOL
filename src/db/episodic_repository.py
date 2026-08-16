"""Episodic memory — simplified for local mode (no Firestore).

Events are written to the local file via utils/episodic_writer instead.
Firestore-backed storage is a no-op in local mode.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("second-self")


def append_event(
    uid: str,
    summary: str,
    category: str,
    source: str,
    weight: float | None = None,
    timestamp: str = "",
) -> None:
    """Append an episodic event — no-op in local mode (uses file writer instead)."""
    pass


def get_recent_events(uid: str, n: int = 10) -> list[dict[str, Any]]:
    """Get the most recent episodic events — returns empty list in local mode."""
    return []


def get_episodic_md(uid: str, n: int = 50) -> str:
    """Reconstruct episodic.md — returns empty string in local mode."""
    return ""
