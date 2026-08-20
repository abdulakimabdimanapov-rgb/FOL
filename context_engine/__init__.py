"""Context Engine — compatibility package (canonical engine lives in FOL).

The unified context engine (active app, browser URL, screen capture, Vision
OCR) is now implemented in ``fol/modules/input/context.py``. This package
keeps the legacy import surface for the orchestrator:

    from context_engine.snapshot import get_snapshot, format_context_for_prompt

``ContextSnapshot`` stays reachable via ``context_engine.snapshot`` (lazy
PEP 562 re-export) but is deliberately NOT imported eagerly here, so
importing this package never pulls ``fol/`` onto sys.path.

Legacy modules kept for compatibility: ``app_monitor.py``, ``browser_url.py``.
"""

from context_engine.snapshot import get_snapshot, format_context_for_prompt

__all__ = ["get_snapshot", "format_context_for_prompt"]
