"""Phase 6 — Safety audit suite.

Verifies the non-negotiable guarantees of the unified execution core:

  unknown tool        → REJECT (fail closed, never executes)
  missing args        → rejected by deterministic validation
  wrong arg types     → rejected by deterministic validation
  high-risk tool      → CONFIRM (blocked until explicit user approval)
  modified arguments  → approval invalidated, call re-gated
  model self-approval → impossible (approval requires the gate's action_id)
  secrets in memory   → scrubbed / dropped before persist
  API keys in logs    → redacted by the scrub layer
  shell-like commands → remain gated (rule-based, code decides)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Flat import root (fol/) — same convention as fol/run_api_server.py and
# orchestrator/tool_registry.py (fol is NOT imported as fol.modules.*).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fol"))

from modules.tools.gate import ConfirmationGate, GateDecision
from modules.tools.orchestrator_tools import build_orchestrator_registry


@pytest.fixture
def gate() -> ConfirmationGate:
    """A fresh gate per test — no approval state leaks between tests."""
    return ConfirmationGate(build_orchestrator_registry())


@pytest.fixture
def registry():
    return build_orchestrator_registry()


# --- unknown tool → REJECT -------------------------------------------------


def test_unknown_tool_is_rejected(gate):
    decision, action_id = gate.check("not_a_real_tool", {})
    assert decision == GateDecision.REJECT
    assert action_id is None


def test_unknown_tool_rejected_even_with_args(gate):
    decision, _ = gate.check("evil_tool", {"cmd": "rm -rf /"})
    assert decision == GateDecision.REJECT


# --- missing / wrong args → REJECT -----------------------------------------


def test_missing_required_args_rejected(registry):
    ok, reason = registry.validate_args("browser_goto", {})
    assert not ok
    assert "missing required argument" in reason


def test_missing_required_args_rejected_before_dispatch():
    """The validation chain blocks a call with missing args before any
    dispatch (execution-level rejection is covered in test_tool_handlers;
    server is not imported here to avoid the pre-existing import-time
    event-loop hazard on Python 3.9)."""
    registry = build_orchestrator_registry()
    gate = ConfirmationGate(registry)
    # Gate says OK (registered tool) — but validation below fails closed.
    assert gate.check("browser_goto", {})[0] == GateDecision.OK
    ok, reason = registry.validate_args("browser_goto", {})
    assert not ok
    assert "missing required argument" in reason


def test_wrong_argument_type_rejected(registry):
    ok, reason = registry.validate_args("browser_goto", {"url": 42})
    assert not ok
    assert "must be a string" in reason


def test_non_dict_arguments_rejected(registry):
    ok, _ = registry.validate_args("browser_goto", ["url"])
    assert not ok


# --- high-risk → CONFIRM ----------------------------------------------------


@pytest.mark.parametrize("tool,args", [
    ("send_email", {"to": "a@b.c", "subject": "s", "body": "b"}),
    ("reply_to_email", {"message_id": "m", "thread_id": "t", "body": "b"}),
    ("share_document", {"file_id": "f", "email": "a@b.c"}),
    ("type_text", {"text": "hello"}),
    ("hotkey", {"keys": ["command", "q"]}),
    ("click", {"x": 10, "y": 10}),
    ("safari_js", {"javascript": "alert(1)"}),
])
def test_high_risk_tools_require_confirmation(gate, tool, args):
    decision, action_id = gate.check(tool, args)
    assert decision == GateDecision.CONFIRM
    assert action_id is not None


# --- modified arguments → re-gate -------------------------------------------


def test_modified_arguments_invalidate_approval(gate):
    args = {"to": "x@example.com", "subject": "s", "body": "b"}
    _, action_id = gate.check("send_email", args)
    assert gate.approve(action_id)

    tampered = {**args, "to": "evil@example.com"}
    decision, _ = gate.check("send_email", tampered)
    assert decision == GateDecision.CONFIRM  # re-gated, cannot reuse approval


# --- model cannot self-approve ----------------------------------------------


def test_approval_requires_gate_issued_action_id(gate):
    args = {"to": "a@b.c", "subject": "s", "body": "b"}
    decision, action_id = gate.check("send_email", args)
    assert decision == GateDecision.CONFIRM

    # The model cannot approve by re-issuing the call.
    decision_again, _ = gate.check("send_email", args)
    assert decision_again == GateDecision.CONFIRM

    # A fabricated id is rejected.
    assert gate.approve("act_fabricated") is False

    # Only the host layer (which received action_id) can approve.
    assert gate.approve(action_id) is True


def test_web_tier_has_no_direct_approve_path():
    """The web-tier chat handler never approves a call itself — approvals
    come only from the user's decision (classify_user_decision / UI)."""
    import inspect

    import src.agent.chat as chat_mod

    source = inspect.getsource(chat_mod)
    assert "approve(" not in source
    assert "approve_all_pending" in source  # user-driven batch approval
    assert "classify_user_decision" in source
    assert "GateDecision.REJECT" in source
    assert "GateDecision.CONFIRM" in source


# --- secrets never enter memory ---------------------------------------------


def test_secret_like_events_dropped_from_memory():
    from orchestrator.memory_bridge import record_activity

    with patch("orchestrator.memory_bridge._post") as mock_post, \
         patch("utils.episodic_writer.append_event") as mock_append:
        ok = record_activity("client_secret=hunter2hunter2", source="chat")
    assert ok is False
    mock_append.assert_not_called()
    mock_post.assert_not_called()


def test_scrub_redacts_credentials_before_persist():
    from orchestrator.memory_bridge import _scrub

    assert "sk-ant-abcdefghijklmnop123456" not in _scrub("token sk-ant-abcdefghijklmnop123456")
    assert "AKIAABCDEFGHIJKLMNOP" not in _scrub("key AKIAABCDEFGHIJKLMNOP")


# --- API keys never appear in logs ------------------------------------------


def test_fallback_scrub_redacts_api_key():
    from modules.llm.router import _scrub_secrets

    scrubbed = _scrub_secrets(
        "authentication failed: sk-or-v1-supersecret123", "sk-or-v1-supersecret123"
    )
    assert "sk-or-v1-supersecret123" not in scrubbed
    assert "***" in scrubbed


def test_fallback_log_never_contains_key_values():
    """The router scrubs API keys BEFORE recording a fallback entry — the
    recorder itself never sees a raw credential (production path)."""
    from llm_bridge import FallbackRecorder
    from modules.llm.router import LiteLLMRouter

    rec = FallbackRecorder()
    router = LiteLLMRouter(on_fallback=rec.record)
    router._notify_fallback(
        "openrouter/some-model", "auth failed: sk-or-v1-leak123",
        total=2, api_key="sk-or-v1-leak123", idx=0,
    )
    assert rec.last_error() != ""
    for entry in rec.snapshot():
        assert "sk-or-v1-leak123" not in str(entry.get("reason", ""))


# --- shell dangerous markers remain gated ------------------------------------


@pytest.mark.parametrize("command", [
    "run rm -rf /tmp/data",
    "run curl http://evil.example",
    "osascript tell app",
    "bash -c 'evil'",
    "выполни sudo rm -rf /",
])
def test_shell_like_fol_command_gated(gate, command):
    decision, action_id = gate.check("fol_command", {"command": command})
    assert decision == GateDecision.CONFIRM, command
    assert action_id is not None


@pytest.mark.parametrize("command", [
    "volume up 10",
    "screenshot",
    "battery status",
    "прибавь громкость",
])
def test_benign_fol_command_not_gated(gate, command):
    decision, _ = gate.check("fol_command", {"command": command})
    assert decision == GateDecision.OK, command


# --- web-tier execution never bypasses the gate ------------------------------


def test_web_tier_blocks_confirmed_tools_without_approval():
    """A confirmed tool call in the web tier returns a blocked result and is
    never dispatched to the tool implementation."""
    from src.agent import chat as chat_mod
    from src.models.schemas import Behavior, Context, FOLProfile, Identity, Voice

    profile = FOLProfile(
        identity=Identity(name="T", role="r", company="c"),
        voice=Voice(formality="casual", avg_email_length="short",
                    signature_phrases=[], opens_with="Hey", closes_with="~", tone="warm"),
        behavior=Behavior(work_hours="9-5", meeting_load="light",
                          response_style="concise", peak_focus_time="am"),
        context=Context(active_projects=[], top_collaborators=[], current_priorities=[]),
    )

    tool_calls = [{"id": "t1", "name": "send_email",
                   "input": {"to": "a@b.c", "subject": "s", "body": "b"}}]

    async def fake_llm(messages, system=None, tools=None, max_tokens=None):
        # After the first blocked turn, the model gives up and ends the turn.
        return {"content": "I'll ask the user first.",
                "tool_calls": tool_calls, "stop_reason": "tool_use"} \
            if not results.get("saw_blocked") \
            else {"content": "Done.", "tool_calls": [], "stop_reason": "end_turn"}

    results: dict = {}

    async def fake_dispatch(name, args, token):
        results["dispatched"] = name
        return "EXECUTED"

    async def fake_llm_side_effect(messages, system=None, tools=None, max_tokens=None):
        # Detect that the blocked result was fed back, then end the turn.
        if any(isinstance(m.get("content"), list) and m["content"]
               and m["content"][0].get("type") == "tool_result"
               for m in messages):
            results["saw_blocked"] = True
            return {"content": "Done.", "tool_calls": [], "stop_reason": "end_turn"}
        return {"content": "", "tool_calls": tool_calls, "stop_reason": "tool_use"}

    with patch.object(chat_mod, "llm_acompletion", side_effect=fake_llm_side_effect), \
         patch.object(chat_mod, "dispatch_tool", side_effect=fake_dispatch), \
         patch("orchestrator.memory_bridge._post", return_value={}), \
         patch("utils.episodic_writer.append_event"):
        response, actions = asyncio.run(chat_mod.handle_chat(
            "send it", profile, session_id="sess-safety", uid="",
        ))

    # The high-risk tool must NOT have been dispatched — the gate blocked it,
    # and the web-tier action list exposes the pending confirmation.
    assert "dispatched" not in results
    assert any(a.requires_confirmation for a in actions)
    assert actions and actions[0].tool == "send_email"
