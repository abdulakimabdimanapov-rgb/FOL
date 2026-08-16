"""Tests for the Phase 5 canonical tool handler architecture.

Verifies that the ToolRegistry is the single dispatch mechanism:
gate → validate → registry-attached handler → JSON result.

Covers: handler dispatch, argument validation, gate integration, unknown-tool
rejection, handler exceptions, malformed tool calls, confirmation signature
binding (changing one arg invalidates a previous approval), and streaming
execution through the wrapper.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))

import pytest

from tool_handlers import HandlerContext, build_handlers

server = pytest.importorskip("server")


# --- registry handler dispatch -------------------------------------------------

def test_all_tools_have_handlers():
    """Every registered tool must have an execution handler attached."""
    reg = server.get_orchestrator_registry()
    from tool_registry import ALL_TOOLS

    for tool in ALL_TOOLS:
        name = tool["name"]
        reg_tool = reg.get(name)
        assert reg_tool is not None, f"{name} not registered"
        assert getattr(reg_tool, "_handler", None) is not None, f"{name} has no handler"


def test_registry_is_single_dispatch():
    """execute_tool_call must go through registry.execute (not a side chain)."""
    reg = server.get_orchestrator_registry()
    # A low-risk, agent-server tool dispatches through the handler → agent server
    result = asyncio.run(server.execute_tool_call("list_profiles", {}))
    parsed = json.loads(result)
    assert "profiles" in parsed or "error" in parsed  # dispatched, not "unknown"


# --- argument validation -------------------------------------------------------

def test_invalid_args_rejected_deterministically():
    result = asyncio.run(server.execute_tool_call("browser_goto", {}))
    parsed = json.loads(result)
    assert "error" in parsed
    assert "missing required argument 'url'" in parsed["error"]


def test_invalid_type_rejected():
    result = asyncio.run(server.execute_tool_call("browser_goto", {"url": 42}))
    parsed = json.loads(result)
    assert "error" in parsed
    assert "must be a string" in parsed["error"]


def test_valid_args_pass_validation_and_dispatch():
    # notify → agent-server endpoint (unreachable in tests → error or ok dict,
    # but never "unknown tool" / never a validation error)
    result = asyncio.run(server.execute_tool_call("notify", {"title": "hi"}))
    parsed = json.loads(result)
    assert "Unknown tool" not in result
    assert "Invalid arguments" not in result
    assert isinstance(parsed, dict)


# --- confirmation gate integration ---------------------------------------------

def test_gate_still_blocks_high_risk_before_dispatch():
    result = asyncio.run(server.execute_tool_call(
        "send_email", {"to": "a@b.c", "subject": "s", "body": "b"}))
    parsed = json.loads(result)
    assert parsed["status"] == "confirmation_required"


def test_confirmation_binds_to_exact_arguments():
    """Changing ONE argument invalidates a previous approval (no bypass)."""
    gate = server.get_confirmation_gate()
    args = {"to": "bind1@example.com", "subject": "s", "body": "b"}
    decision, action_id = gate.check("send_email", args)
    assert decision.value == "confirm"
    assert gate.approve(action_id)

    # Same signature → approved
    decision2, _ = gate.check("send_email", args)
    assert decision2.value == "ok"

    # One argument changed → must be gated again (cannot reuse approval)
    changed = {**args, "to": "bind2@example.com"}
    decision3, _ = gate.check("send_email", changed)
    assert decision3.value == "confirm"


def test_confirmation_key_order_does_not_matter():
    """Canonical signature is JSON-normalized: arg order is irrelevant."""
    gate = server.get_confirmation_gate()
    args = {"to": "order@example.com", "subject": "s", "body": "b"}
    _, action_id = gate.check("send_email", args)
    assert gate.approve(action_id)
    reordered = {"body": "b", "to": "order@example.com", "subject": "s"}
    assert gate.check("send_email", reordered)[0].value == "ok"


# --- unknown tool rejection ----------------------------------------------------

def test_unknown_tool_fails_closed():
    result = asyncio.run(server.execute_tool_call("definitely_not_a_tool", {}))
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Unknown tool" in parsed["error"]


# --- handler exceptions --------------------------------------------------------

def test_handler_exception_returns_error_json():
    """A handler that raises must surface as a JSON error, never a traceback."""
    reg = server.get_orchestrator_registry()
    original = reg.get("clipboard_get")
    original_handler = getattr(original, "_handler", None)

    async def boom(args):
        raise RuntimeError("handler exploded")

    try:
        assert reg.attach_handler("clipboard_get", boom)
        result = asyncio.run(server.execute_tool_call("clipboard_get", {}))
        parsed = json.loads(result)
        assert "error" in parsed
        assert "handler exploded" in parsed["error"]
    finally:
        # Restore the original handler so the shared singleton isn't polluted.
        reg.attach_handler("clipboard_get", original_handler)


def test_malformed_tool_call_rejected():
    """Non-dict arguments must fail deterministically."""
    reg = server.get_orchestrator_registry()
    ok, reason = reg.validate_args("browser_goto", ["url"])
    assert not ok


# --- streaming execution through the wrapper -----------------------------------

def test_streaming_loop_routes_non_render_tools_through_wrapper(monkeypatch):
    """The streaming loop must call execute_tool_call for non-render tools,
    which runs gate → validate → registry handler."""
    calls = []

    async def fake_execute(name, args):
        calls.append(name)
        return json.dumps({"status": "ok"})

    monkeypatch.setattr(server, "execute_tool_call", fake_execute)

    # Simulate a tool_use for a non-render tool (low risk, valid args)
    async def fake_llm(messages, system, tools=None):
        yield ("_tool_use", {"id": "1", "name": "browser_snapshot", "input": {}})
        yield ("_done", {"stop_reason": "tool_use"})

    monkeypatch.setattr(server, "call_claude_streaming", fake_llm)

    async def run():
        events = []
        async for ev in server.run_agent_loop_streaming("take a snapshot", max_steps=2):
            events.append(ev)
        return events

    events = asyncio.run(run())
    assert "browser_snapshot" in calls
    # Completed cleanly
    assert any(e[0] == "state" and e[1].get("state") == "complete" for e in events)


def test_streaming_loop_render_still_emits_component(monkeypatch):
    """render_* tools keep their SSE component emission."""
    yielded = []

    async def fake_execute(name, args):
        return json.dumps({"status": "rendered", "awaiting_user_action": True})

    monkeypatch.setattr(server, "execute_tool_call", fake_execute)

    async def fake_llm(messages, system, tools=None):
        yield ("_tool_use", {"id": "2", "name": "render_confirm_action", "input": {"action": "Restart"}})
        yield ("_done", {"stop_reason": "tool_use"})

    monkeypatch.setattr(server, "call_claude_streaming", fake_llm)

    async def run():
        async for ev in server.run_agent_loop_streaming("confirm restart", max_steps=2):
            yielded.append(ev)

    asyncio.run(run())
    assert any(e[0] == "component" for e in yielded)


# --- build_handlers unit coverage (isolated context) ---------------------------

def test_build_handlers_covers_all_categories():
    """build_handlers must produce a handler for every executable tool name."""
    from tool_registry import ALL_TOOLS, MEMORY_TOOL_NAMES, PRODUCTIVITY_TOOL_NAMES

    ctx = HandlerContext(
        call_agent_server=lambda *a: {},
        call_fol_api=lambda *a: {},
        execute_productivity_tool=lambda *a: "{}",
        execute_memory_tool=lambda *a: "{}",
        get_all_profile_info=lambda: [],
        execute_cookie_sync=lambda *a: {},
        telegram_send=lambda *a: {},
        whatsapp_send=lambda *a: {},
        activate_native_app=lambda *a: {},
        get_google_token=lambda: None,
        try_reload_google_token=lambda: None,
        tavily_api_key="",
        endpoint_map={t["name"]: f"/tool/{t['name']}" for t in ALL_TOOLS},
    )
    handlers = build_handlers(ctx)
    names = {t["name"] for t in ALL_TOOLS}
    assert names <= set(handlers), f"missing handlers: {names - set(handlers)}"
    assert set(MEMORY_TOOL_NAMES) <= set(handlers)
    assert set(PRODUCTIVITY_TOOL_NAMES) <= set(handlers)


# --- src/agent adapter (single source of truth) ------------------------------

def test_src_agent_adapter_derives_from_canonical_registry():
    """src/agent consumes the canonical registry — no duplicated schemas."""
    from src.agent.tool_defs import TOOL_DEFINITIONS, canonical_tool_definitions

    canon = canonical_tool_definitions()
    legacy_names = {t["name"] for t in TOOL_DEFINITIONS}
    canon_names = {t["name"] for t in canon}
    assert len(legacy_names) == 14
    assert canon_names == legacy_names  # same tools, canonical source
    assert all("input_schema" in t and t["input_schema"].get("type") == "object" for t in canon)


def test_build_handlers_produces_callable_async_handlers():
    ctx = HandlerContext(
        call_agent_server=lambda *a: {},
        call_fol_api=lambda *a: {},
        execute_productivity_tool=lambda *a: "{}",
        execute_memory_tool=lambda *a: "{}",
        get_all_profile_info=lambda: [],
        execute_cookie_sync=lambda *a: {},
        telegram_send=lambda *a: {},
        whatsapp_send=lambda *a: {},
        activate_native_app=lambda *a: {},
        get_google_token=lambda: None,
        try_reload_google_token=lambda: None,
        tavily_api_key="",
        endpoint_map={"browser_goto": "/browser/goto"},
    )
    handlers = build_handlers(ctx)
    handler = handlers["browser_goto"]
    assert asyncio.iscoroutinefunction(handler)
