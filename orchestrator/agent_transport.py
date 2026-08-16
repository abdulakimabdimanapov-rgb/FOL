"""orchestrator/agent_transport.py — transport-level tool→endpoint mapping (Phase 6).

The HTTP transport mapping (orchestrator tool name → agent-server HTTP
endpoint) is **transport metadata**, not tool metadata. It deliberately lives
OUTSIDE the canonical ``ToolRegistry`` (``fol/modules/tools/``): the registry
owns schema / risk / confirmation; this module owns the routing table and
validates it against the registry so every mapped tool is a real, registered
tool (unknown names fail loud with a clear message).

Runtime configuration:
- ``AGENT_SERVER_URL`` — base URL of the agent-server (default
  ``http://localhost:8421``), overridable via the environment. Used by the
  orchestrator's HTTP client — no code change needed to point the desktop
  execution layer at a different host/port.
- ``AGENT_SERVER_ENDPOINTS`` — the documented agent-server endpoint contract
  (mirrors ``agent-server/server.py``'s ``TOOLS`` route table plus the
  special ``/browser/sync-cookies`` handler). Used to catch typos in the
  endpoint values without importing agent-server (which needs a GUI session).

The mapping is intentionally NOT moved into the ToolRegistry: the canonical
core must stay free of HTTP transport coupling.
"""

from __future__ import annotations

import os
from typing import Any

# Base URL of the agent-server (desktop execution layer, port 8421 by default).
AGENT_SERVER_URL = os.environ.get("AGENT_SERVER_URL", "http://localhost:8421")

# Documented agent-server HTTP contract — mirrors agent-server/server.py's
# TOOLS route table + /browser/sync-cookies (heavier dedicated handler).
AGENT_SERVER_ENDPOINTS: frozenset[str] = frozenset({
    # Desktop (PyAutoGUI)
    "/tool/screenshot", "/tool/click", "/tool/double_click", "/tool/type",
    "/tool/hotkey", "/tool/scroll", "/tool/open_app", "/tool/close_app",
    "/tool/drag", "/tool/clipboard_get", "/tool/clipboard_set", "/tool/notify",
    "/tool/move", "/tool/screen_size",
    # Safari (AppleScript)
    "/safari/goto", "/safari/js", "/safari/url", "/safari/text",
    # Browser (agent-browser CLI)
    "/browser/goto", "/browser/click", "/browser/fill", "/browser/snapshot",
    "/browser/screenshot", "/browser/text", "/browser/press", "/browser/close",
    # Cookie sync (dedicated handler)
    "/browser/sync-cookies",
})

# Tool name → agent-server endpoint (single definition point for the
# orchestrator's HTTP transport). Keys MUST be canonical registry tools —
# see validate_endpoint_map().
TOOL_ENDPOINT_MAP: dict[str, str] = {
    # Browser tools (agent-browser)
    "browser_goto": "/browser/goto",
    "browser_click": "/browser/click",
    "browser_fill": "/browser/fill",
    "browser_snapshot": "/browser/snapshot",
    "browser_text": "/browser/text",
    "browser_press": "/browser/press",
    # Desktop tools (PyAutoGUI)
    "screenshot": "/tool/screenshot",
    "click": "/tool/click",
    "type_text": "/tool/type",
    "hotkey": "/tool/hotkey",
    "open_app": "/tool/open_app",
    "close_app": "/tool/close_app",
    "drag": "/tool/drag",
    "clipboard_get": "/tool/clipboard_get",
    "clipboard_set": "/tool/clipboard_set",
    "notify": "/tool/notify",
    "scroll": "/tool/scroll",
    # Safari tools (AppleScript)
    "safari_goto": "/safari/goto",
    "safari_js": "/safari/js",
    "safari_get_url": "/safari/url",
    "safari_get_text": "/safari/text",
}


def validate_endpoint_map(
    registry: Any,
    *,
    endpoint_map: dict[str, str] | None = None,
    endpoints: frozenset[str] | None = None,
) -> list[str]:
    """Validate the tool→endpoint map against the canonical registry.

    Returns a list of problems (empty when consistent):

    - every mapped tool name must be registered in the canonical ToolRegistry
      (a mapped name that is not a real tool would otherwise be silently
      routable — fail loud instead);
    - every endpoint value must be a documented agent-server endpoint
      (catches typos in the transport table).

    Pure check — no mutation, no imports of the agent-server (which needs a
    GUI session and is not importable in tests).
    """
    problems: list[str] = []
    ep_set = endpoints if endpoints is not None else AGENT_SERVER_ENDPOINTS
    mapping = endpoint_map if endpoint_map is not None else TOOL_ENDPOINT_MAP

    for tool_name, endpoint in sorted(mapping.items()):
        if registry is not None and not registry.has(tool_name):
            problems.append(
                f"TOOL_ENDPOINT_MAP key '{tool_name}' is not a registered canonical tool"
            )
        if not endpoint.startswith("/"):
            problems.append(
                f"TOOL_ENDPOINT_MAP value for '{tool_name}' is not an HTTP path: {endpoint!r}"
            )
        elif endpoint not in ep_set:
            problems.append(
                f"TOOL_ENDPOINT_MAP value for '{tool_name}' is not a documented "
                f"agent-server endpoint: {endpoint}"
            )
    return problems


def endpoint_map_problems() -> list[str] | None:
    """Validate the real map against the canonical registry (lazy import).

    Returns a list of mapping problems, or ``None`` when validation itself
    could not run (registry unavailable) — deliberately distinct from an
    actually broken map, so callers can log the two cases differently.
    """
    try:
        from tool_registry import get_orchestrator_registry

        return validate_endpoint_map(get_orchestrator_registry())
    except Exception:  # pragma: no cover - defensive
        return None


__all__ = [
    "AGENT_SERVER_URL",
    "AGENT_SERVER_ENDPOINTS",
    "TOOL_ENDPOINT_MAP",
    "validate_endpoint_map",
    "endpoint_map_problems",
]
