"""Auth0 OAuth — disabled in local mode.

FOL now runs with local AI (Ollama) and doesn't require any authentication.
This file is kept as a stub for backwards compatibility.
"""
from __future__ import annotations

import logging

log = logging.getLogger("second-self")


def is_authenticated() -> bool:
    """Local mode — always returns True (no auth needed)."""
    return True


def get_user_info() -> dict:
    """Return mock user info for local mode."""
    return {
        "authenticated": True,
        "email": "local@fol.ai",
        "name": "Local User",
    }
