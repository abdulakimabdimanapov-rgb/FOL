"""Phase 6 regression tests — web-tier unification.

Verifies that the web-tier agent (``src/agent/chat.py``) consumes the
canonical ``ToolRegistry`` schemas (via ``canonical_tool_definitions()``) and
is gated by the SAME canonical ``ConfirmationGate`` as the orchestrator —
risk metadata, rejection and approval semantics are identical across tiers,
and the model can never self-approve a dangerous action.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Flat import root (fol/) — same convention as orchestrator/tool_registry.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fol"))

from modules.tools.gate import ConfirmationGate, GateDecision


# ---------------------------------------------------------------------------
# canonical schema consumption
# ---------------------------------------------------------------------------


def test_chat_passes_canonical_schemas_to_llm():
    """handle_chat must call the LLM with canonical_tool_definitions(), never
    a second schema copy."""
    from src.agent.chat import handle_chat
    from src.agent.tool_defs import canonical_tool_definitions
    from src.models.schemas import Behavior, Context, FOLProfile, Identity, Voice

    profile = FOLProfile(
        identity=Identity(name="Test User", role="engineer", company="FOL"),
        voice=Voice(formality="casual", avg_email_length="short",
                    signature_phrases=[], opens_with="Hey", closes_with="~",
                    tone="warm"),
        behavior=Behavior(work_hours="9am-5pm", meeting_load="light",
                          response_style="concise", peak_focus_time="morning"),
        context=Context(active_projects=[], top_collaborators=[],
                        current_priorities=[]),
    )

    captured: dict = {}

    async def fake_llm(messages, system=None, tools=None, max_tokens=None):
        captured["tools"] = tools
        return {"content": "Done.", "tool_calls": [], "stop_reason": "end_turn"}

    with patch("src.agent.chat.llm_acompletion", side_effect=fake_llm), \
         patch("orchestrator.memory_bridge._post", return_value={}), \
         patch("utils.episodic_writer.append_event") as mock_append:
        asyncio.run(handle_chat(
            "hello", profile, session_id="sess-canon", uid="",
        ))

    assert captured.get("tools") is not None
    canonical = canonical_tool_definitions()
    names = {t["name"] for t in captured["tools"]}
    assert names == {t["name"] for t in canonical}
    assert len(names) == 14  # the canonical productivity toolset, no duplicates


def test_chat_does_not_reference_legacy_TOOL_DEFINITIONS():
    """The web-tier chat handler must import only the canonical adapter."""
    import inspect

    import src.agent.chat as chat_mod

    source = inspect.getsource(chat_mod)
    # chat.py should not construct tool schemas from the legacy dict.
    assert "TOOL_DEFINITIONS" not in source
    assert "canonical_tool_definitions" in source


# ---------------------------------------------------------------------------
# gate parity: web tier == orchestrator
# ---------------------------------------------------------------------------


def _fresh_web_gate() -> ConfirmationGate:
    from modules.tools.orchestrator_tools import build_orchestrator_registry

    return ConfirmationGate(build_orchestrator_registry())


def _orchestrator_gate() -> ConfirmationGate:
    from server import get_confirmation_gate

    return get_confirmation_gate()


_TOOL_CASES = [
    # (tool, args, expected decision for both tiers)
    ("send_email", {"to": "a@b.c", "subject": "s", "body": "b"}, GateDecision.CONFIRM),
    ("reply_to_email", {"message_id": "m1", "thread_id": "t1", "body": "b"}, GateDecision.CONFIRM),
    ("share_document", {"file_id": "f", "email": "a@b.c"}, GateDecision.CONFIRM),
    ("browser_goto", {"url": "https://example.com"}, GateDecision.OK),
    ("search_web", {"query": "ai"}, GateDecision.OK),
    ("draft_email", {"to": "a@b.c", "subject": "s", "body": "b"}, GateDecision.OK),
    ("browser_snapshot", {}, GateDecision.OK),
]


@pytest.mark.parametrize("tool,args,expected", _TOOL_CASES)
def test_web_gate_parity_with_orchestrator(tool, args, expected):
    """The web-tier gate and the orchestrator gate decide identically."""
    web = _fresh_web_gate()
    orch = _orchestrator_gate()
    web_decision, _ = web.check(tool, args)
    orch_decision, _ = orch.check(tool, args)
    assert web_decision == expected, f"web tier: {web_decision}"
    assert orch_decision == expected, f"orchestrator: {orch_decision}"


def test_web_gate_rejects_unknown_tool():
    gate = _fresh_web_gate()
    decision, _ = gate.check("definitely_not_a_tool", {})
    assert decision == GateDecision.REJECT


def test_web_gate_model_cannot_self_approve():
    """The model re-issuing a gated call gets CONFIRM every time until the
    user approves through the returned action_id. A bogus/guessed id never
    works, and the model has no approval path of its own."""
    gate = _fresh_web_gate()
    args = {"to": "a@b.c", "subject": "s", "body": "b"}

    d1, action_id = gate.check("send_email", args)
    assert d1 == GateDecision.CONFIRM
    assert action_id is not None

    # Re-issue identical call before approval → still gated.
    d2, _ = gate.check("send_email", args)
    assert d2 == GateDecision.CONFIRM

    # A guessed action id cannot approve.
    assert gate.approve("act_" + "0" * 12) is False

    # Only the real id (returned to the host layer) approves.
    assert gate.approve(action_id) is True
    d3, _ = gate.check("send_email", args)
    assert d3 == GateDecision.OK


def test_web_gate_modified_args_require_regate():
    """Approval binds to the exact signature: any argument change re-gates."""
    gate = _fresh_web_gate()
    args = {"to": "bind@example.com", "subject": "s", "body": "b"}
    _, action_id = gate.check("send_email", args)
    assert gate.approve(action_id)

    changed = {**args, "body": "changed!"}
    d, _ = gate.check("send_email", changed)
    assert d == GateDecision.CONFIRM
