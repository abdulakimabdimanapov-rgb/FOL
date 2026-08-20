"""Compatibility shim — desktop context snapshot → canonical FOL engine.

The canonical unified context engine now lives in
``fol/modules/input/context.py`` (:class:`ContextEngine` /
:class:`ContextSnapshot`). This module keeps the legacy names the orchestrator
and its tests rely on (``get_snapshot`` / ``format_context_for_prompt`` /
``ContextSnapshot``) and delegates lazily, so the orchestrator's
``build_context_messages`` keeps working unchanged.

``app_monitor.py`` / ``browser_url.py`` remain in place for any legacy
consumers (the test conftest patches ``context_engine.browser_url``).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _fol_module():
    """Import the canonical engine lazily (fol/ may not be on sys.path yet)."""
    from modules.input.context import ContextEngine, ContextSnapshot  # noqa: F401

    return ContextEngine, ContextSnapshot


def get_snapshot(use_cache: bool = False) -> Any:
    """Build a structured desktop context snapshot via the FOL engine."""
    ContextEngine, _ = _fol_module()
    return ContextEngine().capture(use_cache=use_cache)


def format_context_for_prompt(snapshot: Any) -> str:
    """Prompt-ready one-liner (same shape as before)."""
    try:
        return snapshot.to_prompt()
    except AttributeError:
        # Legacy duck-typed snapshots (e.g. MagicMock in tests) fall back to
        # the old string assembly.
        parts = [f"Active: {snapshot.app_name} ({snapshot.app_category})"]
        if getattr(snapshot, "browser_url", ""):
            parts.append(f"URL: {snapshot.browser_url}")
        return " | ".join(parts)


def __getattr__(name: str) -> Any:
    """Lazy re-export of the canonical ``ContextSnapshot`` (PEP 562)."""
    if name == "ContextSnapshot":
        _, ContextSnapshot = _fol_module()
        return ContextSnapshot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["get_snapshot", "format_context_for_prompt", "ContextSnapshot"]
