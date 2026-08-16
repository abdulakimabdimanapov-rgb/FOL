"""Compatibility adapter — orchestrator ↔ canonical ToolRegistry (Phase 4).

The orchestrator no longer maintains independent tool dictionaries. Every tool
schema, description, risk level and confirmation requirement is defined once
in ``fol/modules/tools/orchestrator_tools.py`` and registered in the canonical
``ToolRegistry``. This module derives the legacy Anthropic-format dicts
(``BROWSER_TOOLS`` / ``DESKTOP_TOOLS`` / …) from the registry so the existing
orchestrator event contract, agent loop and tests keep working unchanged.

It also exposes:

- ``get_orchestrator_registry()`` — the canonical registry instance
- ``get_confirmation_gate()`` — the deterministic, code-enforced gate
- ``BROWSER_NAV_TOOLS`` — the subset the orchestrator uses for cookie-sync hinting
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_FOL_DIR = Path(__file__).resolve().parent.parent / "fol"
if str(_FOL_DIR) not in sys.path:
    sys.path.insert(0, str(_FOL_DIR))

_registry: Any = None
_gate: Any = None


def get_orchestrator_registry():
    """Build (once) the canonical orchestrator tool registry."""
    global _registry
    if _registry is None:
        from modules.tools.orchestrator_tools import build_orchestrator_registry

        _registry = build_orchestrator_registry()
    return _registry


def get_confirmation_gate():
    """Build (once) the deterministic confirmation gate over the registry."""
    global _gate
    if _gate is None:
        from modules.tools.gate import ConfirmationGate

        _gate = ConfirmationGate(get_orchestrator_registry())
    return _gate


def _category_tools(category: str) -> list[dict[str, Any]]:
    """Anthropic-format dicts for one category, derived from canonical specs."""
    registry = get_orchestrator_registry()
    return [spec.to_anthropic() for spec in registry.filter(category=category)]


# --- Derived legacy-format tool catalogs (single source of truth: registry) ---

BROWSER_TOOLS: list[dict[str, Any]] = _category_tools("browser")
DESKTOP_TOOLS: list[dict[str, Any]] = _category_tools("desktop")
UI_TOOLS: list[dict[str, Any]] = _category_tools("ui")
PRODUCTIVITY_TOOLS: list[dict[str, Any]] = _category_tools("productivity")
MEMORY_TOOLS: list[dict[str, Any]] = _category_tools("memory")
FOL_TOOLS: list[dict[str, Any]] = _category_tools("fol")

ALL_TOOLS: list[dict[str, Any]] = (
    BROWSER_TOOLS + DESKTOP_TOOLS + UI_TOOLS + PRODUCTIVITY_TOOLS + MEMORY_TOOLS + FOL_TOOLS
)

PRODUCTIVITY_TOOL_NAMES = {t["name"] for t in PRODUCTIVITY_TOOLS}
MEMORY_TOOL_NAMES = {t["name"] for t in MEMORY_TOOLS}

# Browser tool names that trigger the cookie sync prompt (navigation-related).
BROWSER_NAV_TOOLS = {"browser_goto"}


def anthropic_tools(names: set[str]) -> list[dict[str, Any]]:
    """Anthropic-format dicts for an explicit set of tool names (from registry)."""
    registry = get_orchestrator_registry()
    return [spec.to_anthropic() for spec in registry.filter(names=names)]


def risk_of(name: str) -> str:
    """Canonical risk level of a tool ('' for unknown)."""
    spec = get_orchestrator_registry().get_spec(name)
    return spec.risk_level.value if spec else ""


def requires_confirmation(name: str) -> bool:
    """Whether the registry metadata requires confirmation for ``name``."""
    return get_orchestrator_registry().requires_confirmation(name)


__all__ = [
    "ALL_TOOLS",
    "BROWSER_TOOLS",
    "DESKTOP_TOOLS",
    "UI_TOOLS",
    "PRODUCTIVITY_TOOLS",
    "PRODUCTIVITY_TOOL_NAMES",
    "MEMORY_TOOLS",
    "MEMORY_TOOL_NAMES",
    "FOL_TOOLS",
    "BROWSER_NAV_TOOLS",
    "anthropic_tools",
    "risk_of",
    "requires_confirmation",
    "get_orchestrator_registry",
    "get_confirmation_gate",
]
