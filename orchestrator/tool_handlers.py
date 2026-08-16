"""orchestrator/tool_handlers.py — canonical tool handlers (Phase 5).

Every executable tool's runtime logic lives here as a registry-attached
handler. ``build_handlers(ctx)`` returns ``{tool_name: async handler}`` where
each handler takes the tool arguments dict and returns a JSON string (the same
contract the legacy ``execute_tool_call`` had — so the SSE/agent-loop layer is
unchanged).

Handlers receive a ``HandlerContext`` of host-layer collaborators
(agent-server client, FOL API client, productivity/memory executors, cookie
sync, messaging) instead of importing ``server`` directly — this avoids a
circular import and keeps the module unit-testable.

Dispatch flow after Phase 5:

    execute_tool_call(name, args)          (thin wrapper)
        → ConfirmationGate.check           (code decides; never the model)
        → ToolRegistry.validate_args       (deterministic)
        → registry.execute → handler(args)
        → JSON string

Handlers deliberately delegate to the proven host functions (``call_agent_server``,
``execute_productivity_tool``, ``execute_memory_tool``, ``_execute_cookie_sync``,
``telegram_send`` …) — no execution logic is duplicated, it is *moved* here so
the registry is the single dispatch point.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


# ---------------------------------------------------------------------------
# Cookie-sync hint state (shared mutable object — one source of truth)
# ---------------------------------------------------------------------------

class CookieState:
    """Shared mutable cookie-sync hint state.

    ``browser_goto`` offers cookie sync on the first navigation without
    authenticated sessions. The orchestrator and the handlers share one
    instance so ``/reset`` and long-running syncs stay consistent.
    """

    def __init__(self) -> None:
        self.synced: bool = False
        self.offered: bool = False

    def reset(self) -> None:
        self.synced = False
        self.offered = False


# ---------------------------------------------------------------------------
# Context — host-layer collaborators injected by orchestrator/server.py
# ---------------------------------------------------------------------------

@dataclass
class HandlerContext:
    """Collaborators the handlers need. Injected by the orchestrator at startup."""

    call_agent_server: Callable[[str, dict | None, str], dict]
    call_fol_api: Callable[[str, dict | None, str], dict]
    execute_productivity_tool: Callable[[str, dict, str, str], Awaitable[str] | str]
    execute_memory_tool: Callable[[str, dict], Awaitable[str] | str]
    get_all_profile_info: Callable[[], list[dict]]
    execute_cookie_sync: Callable[..., Awaitable[dict] | dict]
    telegram_send: Callable[[str, str], dict]
    whatsapp_send: Callable[[str, str], dict]
    activate_native_app: Callable[[str], dict]
    get_google_token: Callable[[], str | None]
    try_reload_google_token: Callable[[], None]
    tavily_api_key: str
    # Tool name → agent-server endpoint map (defined in orchestrator/server.py)
    endpoint_map: dict[str, str] = field(default_factory=dict)
    # Cookie-sync hint state (browser_goto → first navigation without cookies)
    browser_nav_tools: set[str] = field(default_factory=set)
    cookie_state: CookieState = field(default_factory=CookieState)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _json(value: Any) -> str:
    return json.dumps(value)


# ---------------------------------------------------------------------------
# Handler factories (each returns the async handler for one tool / category)
# ---------------------------------------------------------------------------

def _agent_server_handler(ctx: HandlerContext, tool_name: str) -> Callable[[dict], Awaitable[str]]:
    """Generic handler for agent-server endpoint tools (browser/desktop/safari)."""

    async def handler(args: dict) -> str:
        endpoint = ctx.endpoint_map.get(tool_name)
        if not endpoint:
            return _json({"error": f"Unknown tool: {tool_name}"})
        result = await asyncio.to_thread(ctx.call_agent_server, endpoint, args, "POST")
        if tool_name == "screenshot" and "image" in result:
            return _json({"status": "ok", "description": "Screenshot captured. I can see the desktop."})
        return _json(result)

    return handler


def _browser_goto_handler(ctx: HandlerContext) -> Callable[[dict], Awaitable[str]]:
    """browser_goto — first navigation without cookies offers cookie sync."""

    async def handler(args: dict) -> str:
        if not ctx.cookie_state.synced and not ctx.cookie_state.offered:
            ctx.cookie_state.offered = True
            profiles = await asyncio.to_thread(ctx.get_all_profile_info)
            profile_list = ", ".join(
                f"'{p['display_name']}' ({p['browser']}){' [last used]' if p.get('last_used') else ''}"
                for p in profiles
            )
            return _json({
                "status": "no_cookies",
                "message": (
                    f"The browser has no authenticated sessions. "
                    f"Ask the user which profile they'd like to sync cookies from. "
                    f"Available profiles: {profile_list}. "
                    f"Use render_confirm_action to ask, then call sync_cookies "
                    f"with the chosen profile name. "
                    f"After syncing (or if they decline), retry this browser_goto."
                ),
            })
        endpoint = ctx.endpoint_map.get("browser_goto")
        if not endpoint:
            return _json({"error": "browser_goto has no endpoint"})
        result = await asyncio.to_thread(ctx.call_agent_server, endpoint, args, "POST")
        return _json(result)

    return handler


def _sync_cookies_handler(ctx: HandlerContext) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        result = await ctx.execute_cookie_sync(args.get("profile"), args.get("browser"))
        return _json(result)

    return handler


def _list_profiles_handler(ctx: HandlerContext) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        profiles = await asyncio.to_thread(ctx.get_all_profile_info)
        return _json({"status": "ok", "profiles": profiles})

    return handler


def _telegram_handler(ctx: HandlerContext) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        return _json(ctx.telegram_send(args.get("contact", ""), args.get("message", "")))

    return handler


def _whatsapp_handler(ctx: HandlerContext) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        return _json(ctx.whatsapp_send(args.get("contact", ""), args.get("message", "")))

    return handler


def _activate_app_handler(ctx: HandlerContext) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        return _json(ctx.activate_native_app(args.get("name", "")))

    return handler


def _fol_command_handler(ctx: HandlerContext) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        command = args.get("command", "")
        if not command:
            return _json({"error": "Empty command"})
        # method omitted on purpose — call_fol_api defaults to POST (matches the
        # documented handler contract and keeps tests/patch call signatures stable)
        result = await asyncio.to_thread(ctx.call_fol_api, "/api/chat", {"message": command})
        response = result.get("response", "")
        error = result.get("error", "")
        if error:
            return _json({"error": f"FOL command failed: {error}", "response": response})
        return _json({"status": "ok", "response": response, "tool": "fol"})

    return handler


def _render_handler() -> Callable[[dict], Awaitable[str]]:
    """UI render tools — the SSE layer emits the A2UI component; the registry
    handler just confirms the render (used by the non-streaming path)."""

    async def handler(args: dict) -> str:
        return _json({"status": "rendered", "awaiting_user_action": True})

    return handler


def _memory_tools_handler(ctx: HandlerContext, tool_name: str) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        result = ctx.execute_memory_tool(tool_name, args)
        if asyncio.iscoroutine(result):
            result = await result
        return result if isinstance(result, str) else _json(result)

    return handler


def _productivity_tools_handler(ctx: HandlerContext, tool_name: str) -> Callable[[dict], Awaitable[str]]:
    async def handler(args: dict) -> str:
        token = ctx.get_google_token()
        if not token:
            ctx.try_reload_google_token()
            token = ctx.get_google_token()
        if not token:
            return _json({
                "error": "google_auth_required",
                "message": "You need to sign in with Google first. Ask the user to sign in via the notch UI, then retry.",
            })
        result = ctx.execute_productivity_tool(tool_name, args, token, ctx.tavily_api_key)
        if asyncio.iscoroutine(result):
            return await result
        return str(result)

    return handler


# ---------------------------------------------------------------------------
# Public factory — the single place that maps tool names → handlers
# ---------------------------------------------------------------------------

# Agent-server endpoint tools (name → endpoint map lives in tool_registry).
_AGENT_SERVER_TOOLS = (
    # Browser
    "browser_click", "browser_fill", "browser_snapshot", "browser_text", "browser_press",
    # Desktop (PyAutoGUI)
    "screenshot", "click", "type_text", "hotkey", "open_app", "close_app",
    "drag", "clipboard_get", "clipboard_set", "notify", "scroll",
    # Safari (AppleScript)
    "safari_goto", "safari_js", "safari_get_url", "safari_get_text",
)

_UI_TOOLS = ("render_task_approval", "render_profile_card", "render_screenshot", "render_confirm_action")


def build_handlers(ctx: HandlerContext) -> dict[str, Callable[[dict], Awaitable[str]]]:
    """Build the canonical ``{name: handler}`` map for every executable tool.

    This is the single mapping of tool name → execution logic. The registry
    becomes the dispatch mechanism: ``execute_tool_call`` is a thin wrapper
    over gate → validate → ``registry.execute``.
    """
    from tool_registry import MEMORY_TOOL_NAMES, PRODUCTIVITY_TOOL_NAMES

    handlers: dict[str, Callable[[dict], Awaitable[str]]] = {}

    # Browser navigation + cookie sync
    handlers["browser_goto"] = _browser_goto_handler(ctx)
    handlers["list_profiles"] = _list_profiles_handler(ctx)
    handlers["sync_cookies"] = _sync_cookies_handler(ctx)

    # Agent-server endpoint tools
    for name in _AGENT_SERVER_TOOLS:
        handlers[name] = _agent_server_handler(ctx, name)

    # Messaging + native app helpers
    handlers["send_telegram"] = _telegram_handler(ctx)
    handlers["send_whatsapp"] = _whatsapp_handler(ctx)
    handlers["activate_app"] = _activate_app_handler(ctx)

    # Memory tools (per-tool wrapper carrying the name)
    for name in sorted(MEMORY_TOOL_NAMES):
        handlers[name] = _memory_tools_handler(ctx, name)

    # FOL JARVIS command
    handlers["fol_command"] = _fol_command_handler(ctx)

    # Productivity tools (per-tool wrapper carrying the name)
    for name in sorted(PRODUCTIVITY_TOOL_NAMES):
        handlers[name] = _productivity_tools_handler(ctx, name)

    # UI render tools — never executed, but registered so dispatch is complete
    for name in _UI_TOOLS:
        handlers[name] = _render_handler()

    return handlers


__all__ = ["HandlerContext", "CookieState", "build_handlers"]
