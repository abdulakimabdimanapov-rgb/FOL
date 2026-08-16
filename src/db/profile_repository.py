"""Profile CRUD — simplified for local mode (no Firestore)."""
from __future__ import annotations

import logging
from typing import Any

from src.models.schemas import RichProfile, FOLProfile

log = logging.getLogger("second-self")


def save_slim_profile(
    uid: str,
    profile: FOLProfile,
    sources: list[str],
) -> None:
    """Save the slim profile — no-op in local mode (Firestore not available)."""
    log.info("Local mode: profile not saved to cloud (uid=%s)", uid)


def get_slim_profile(uid: str) -> FOLProfile | None:
    """Load the slim profile — always returns None in local mode."""
    return None


def save_rich_profile(uid: str, rich: RichProfile) -> None:
    """Save the rich profile — no-op in local mode."""
    log.info("Local mode: rich profile not saved to cloud (uid=%s)", uid)


def get_rich_profile(uid: str) -> RichProfile | None:
    """Load the rich profile — always returns None in local mode."""
    return None
