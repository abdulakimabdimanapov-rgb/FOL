"""Tests for orchestrator ToolRegistry integration (Phase 4).

Verifies that:
- the orchestrator's tool catalogs are derived from the canonical registry
- the deterministic confirmation gate blocks gated tools in execute_tool_call
- unknown tools are rejected (fail closed)
- the /confirm endpoint approves/denies deterministically
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))

import pytest

from tool_registry import (
    ALL_TOOLS,
    BROWSER_TOOLS,
    DESKTOP_TOOLS,
    FOL_TOOLS,
    MEMORY_TOOLS,
    PRODUCTIVITY_TOOLS,
    UI_TOOLS,
    get_confirmation_gate,
    get_orchestrator_registry,
)

# Server import is heavy (FastAPI + agent wiring) but the orchestrator tests
# already import it in the same suite — do it lazily here.
server = pytest.importorskip("server")


# --- catalogs derive from the canonical registry ---------------------------

def test_catalogs_match_registry():
    reg = get_orchestrator_registry()
    reg_names = set(reg.names())
    catalog_names = {t["name"] for t in ALL_TOOLS}
    assert catalog_names == reg_names


def test_category_split_consistent():
    reg = get_orchestrator_registry()
    by_cat: dict[str, set[str]] = {}
    for name in ["BROWSER_TOOLS", "DESKTOP_TOOLS", "UI_TOOLS", "PRODUCTIVITY_TOOLS",
                 "MEMORY_TOOLS", "FOL_TOOLS"]:
        lst = globals()[name]
        by_cat[name] = {t["name"] for t in lst}
    # No name appears in two categories
    all_names = [n for s in by_cat.values() for n in s]
    assert len(all_names) == len(set(all_names))


def test_server_tools_are_registry_derived():
    # The server no longer defines its own tool dicts — they come from tool_registry
    assert server.ALL_TOOLS is ALL_TOOLS or server.ALL_TOOLS == ALL_TOOLS
    assert server.BROWSER_TOOLS is BROWSER_TOOLS or server.BROWSER_TOOLS == BROWSER_TOOLS
    assert server.PRODUCTIVITY_TOOLS == PRODUCTIVITY_TOOLS
    assert server.MEMORY_TOOLS == MEMORY_TOOLS


# --- confirmation gate blocks gated tools ----------------------------------


def _run_execute_tool_call(name, args):
    import asyncio

    return asyncio.run(server.execute_tool_call(name, args))


def test_execute_tool_call_gates_high_risk():
    result = json.loads(_run_execute_tool_call("send_email", {"to": "a@b.c", "subject": "s", "body": "b"}))
    assert result.get("status") == "confirmation_required"
    assert result.get("action_id", "").startswith("act_")


def test_execute_tool_call_gates_sync_cookies():
    result = json.loads(_run_execute_tool_call("sync_cookies", {}))
    assert result.get("status") == "confirmation_required"


def test_execute_tool_call_gates_type_text():
    """type_text is INTERACTIVE_GUI → PEEK_CONFIRM (light notification, no block).

    In the 5-level RiskScorer, interactive GUI tools (click, type, hotkey)
    get PEEK_CONFIRM instead of CONFIRM — they execute with a lightweight
    auto-dismiss notification.  Verify the gate decision directly since
    PEEK_CONFIRM falls through to execution (needs agent server).
    """
    gate = get_confirmation_gate()
    decision, _ = gate.check("type_text", {"text": "hello"})
    assert decision.value == "peek"


def test_execute_tool_call_unknown_rejected():
    result = json.loads(_run_execute_tool_call("no_such_tool", {}))
    assert "error" in result
    assert "Unknown tool" in result["error"]


def test_execute_tool_call_low_risk_passes_gate():
    # list_profiles is low risk: gate passes, then normal execution path runs
    # (no agent-server here, but the gate must not block it)
    gate = get_confirmation_gate()
    decision, _ = gate.check("list_profiles", {})
    assert decision.value == "ok"


def test_gate_approve_then_execute_ok():
    """Approve via the gate → the same signature now executes (no re-gate)."""
    gate = get_confirmation_gate()
    # Unique args so we never collide with other tests' approvals
    args = {"to": "unique-approve@example.com", "subject": "s", "body": "b"}
    decision, action_id = gate.check("send_email", args)
    assert decision.value == "confirm"
    assert gate.approve(action_id)
    decision2, _ = gate.check("send_email", args)
    assert decision2.value == "ok"


# --- /confirm endpoint -----------------------------------------------------

def test_confirm_endpoint_approve():
    gate = get_confirmation_gate()
    args = {"to": "unique-confirm@example.com", "subject": "s", "body": "b"}
    _, action_id = gate.check("send_email", args)
    import asyncio

    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    resp = client.post("/confirm", json={"action_id": action_id, "decision": "approve"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "approve"


def test_confirm_endpoint_deny():
    gate = get_confirmation_gate()
    args = {"to": "unique-deny@example.com", "subject": "s", "body": "b"}
    _, action_id = gate.check("send_email", args)
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    resp = client.post("/confirm", json={"action_id": action_id, "decision": "deny"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "deny"


def test_confirm_endpoint_bad_decision():
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    resp = client.post("/confirm", json={"action_id": "act_xyz", "decision": "maybe"})
    assert resp.status_code == 400


def test_confirm_endpoint_unknown_id():
    from fastapi.testclient import TestClient

    client = TestClient(server.app)
    resp = client.post("/confirm", json={"action_id": "act_nope", "decision": "approve"})
    assert resp.status_code == 404


# --- /chat approval resolution ---------------------------------------------

def test_chat_approve_resolves_pending():
    gate = get_confirmation_gate()
    args = {"to": "unique-chat@example.com", "subject": "s", "body": "b"}
    _, action_id = gate.check("send_email", args)
    assert action_id in gate.pending()
    server._resolve_user_confirmation("Allowed: send email")
    assert action_id not in gate.pending()
    assert gate.check("send_email", args)[0].value == "ok"


def test_chat_deny_clears_pending():
    gate = get_confirmation_gate()
    args = {"to": "unique-chat2@example.com", "subject": "s", "body": "b"}
    _, action_id = gate.check("send_email", args)
    server._resolve_user_confirmation("Denied: send email")
    assert action_id not in gate.pending()
    assert gate.check("send_email", args)[0].value == "confirm"
