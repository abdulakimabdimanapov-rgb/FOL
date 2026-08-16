"""Firestore is not available in local mode. All db modules handle None gracefully."""
from __future__ import annotations

import logging

log = logging.getLogger("second-self")


def get_db():
    """Return None — Firestore is not available in local mode."""
    return None
