"""Tests for the canonical ConfirmationGate (Phase 4).

Covers: deterministic confirmation decisions, unknown-tool rejection (fail
closed), signature-bound approvals, approve/deny, rule-based shell detection
for fol_command, and natural-language decision classification.
"""

from __future__ import annotations

import pytest

from modules.tools.base import RiskLevel, ToolSpec
from modules.tools.gate import ConfirmationGate, GateDecision
from modules.tools.registry import ToolRegistry


def _spec(name: str, risk: str = "low", confirm: bool = False) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=f"{name} tool",
        schema={"type": "object", "properties": {}},
        risk_level=RiskLevel(risk),
        requires_confirmation=confirm,
        category="test",
    )


def _make_gate(*specs: ToolSpec) -> ConfirmationGate:
    reg = ToolRegistry()
    for s in specs:
        reg.register_spec(s)
    return ConfirmationGate(reg)


def test_low_risk_no_confirmation():
    gate = _make_gate(_spec("read", risk="low"))
    decision, action_id = gate.check("read", {})
    assert decision == GateDecision.OK
    assert action_id is None


def test_high_risk_requires_confirmation():
    gate = _make_gate(_spec("send", risk="high"))
    decision, action_id = gate.check("send", {})
    assert decision == GateDecision.CONFIRM
    assert action_id is not None
    assert action_id.startswith("act_")


def test_confirm_flag_forces_confirmation_even_at_medium():
    gate = _make_gate(_spec("sync", risk="medium", confirm=True))
    decision, _ = gate.check("sync", {})
    assert decision == GateDecision.CONFIRM


def test_critical_risk_confirmation():
    gate = _make_gate(_spec("delete", risk="critical"))
    decision, _ = gate.check("delete", {})
    assert decision == GateDecision.CONFIRM


def test_unknown_tool_fails_closed():
    gate = _make_gate(_spec("known", risk="low"))
    decision, _ = gate.check("unknown_tool", {})
    assert decision == GateDecision.REJECT


def test_approval_binds_to_signature():
    """Approve one signature; a different args signature stays blocked."""
    gate = _make_gate(_spec("send", risk="high"))
    decision, action_id = gate.check("send", {"to": "a@x.com"})
    assert decision == GateDecision.CONFIRM
    assert gate.approve(action_id)

    # Same signature → OK
    decision, _ = gate.check("send", {"to": "a@x.com"})
    assert decision == GateDecision.OK
    # Different signature → still blocked (cannot bypass by re-issuing)
    decision, _ = gate.check("send", {"to": "b@x.com"})
    assert decision == GateDecision.CONFIRM


def test_deny_removes_pending():
    gate = _make_gate(_spec("send", risk="high"))
    _, action_id = gate.check("send", {})
    assert gate.deny(action_id)
    # After denial the call is gated again (must ask again)
    decision, _ = gate.check("send", {})
    assert decision == GateDecision.CONFIRM


def test_approve_unknown_id_fails():
    gate = _make_gate(_spec("send", risk="high"))
    assert not gate.approve("act_nope")
    assert not gate.deny("act_nope")


def test_approve_all_pending():
    gate = _make_gate(_spec("send", risk="high"), _spec("type", risk="high"))
    _, id1 = gate.check("send", {})
    _, id2 = gate.check("type", {})
    assert gate.approve_all_pending() == 2
    assert gate.check("send", {})[0] == GateDecision.OK
    assert gate.check("type", {})[0] == GateDecision.OK


def test_deny_all_pending():
    gate = _make_gate(_spec("send", risk="high"), _spec("type", risk="high"))
    gate.check("send", {})
    gate.check("type", {})
    assert gate.deny_all_pending() == 2
    assert gate.check("send", {})[0] == GateDecision.CONFIRM


def test_reset_clears_state():
    gate = _make_gate(_spec("send", risk="high"))
    _, action_id = gate.check("send", {})
    gate.approve(action_id)
    gate.reset()
    assert not gate.has_pending()
    assert gate.approved_signatures() == set()


def test_rule_shell_markers_block_fol_command():
    """fol_command with shell-like content requires confirmation even at medium."""
    gate = _make_gate(_spec("fol_command", risk="medium"))
    for cmd in ["run ls -la", "выполни команду", "osascript -e 'x'", "sudo rm -rf /", "python3 -c x"]:
        decision, _ = gate.check("fol_command", {"command": cmd})
        assert decision == GateDecision.CONFIRM, f"expected CONFIRM for {cmd!r}"


def test_rule_benign_fol_command_passes():
    gate = _make_gate(_spec("fol_command", risk="medium"))
    decision, _ = gate.check("fol_command", {"command": "screenshot"})
    assert decision == GateDecision.OK


def test_classify_user_decision_approve():
    gate = _make_gate(_spec("x", risk="low"))
    for msg in ["Allowed: open_app Safari", "yes", "да", "Approved", "go ahead", "подтверждаю"]:
        assert gate.classify_user_decision(msg) == "approve", f"{msg!r}"


def test_classify_user_decision_deny():
    gate = _make_gate(_spec("x", risk="low"))
    for msg in ["Denied: open_app Safari", "no", "нет", "cancel", "don't", "не надо"]:
        assert gate.classify_user_decision(msg) == "deny", f"{msg!r}"


def test_classify_user_decision_neutral():
    gate = _make_gate(_spec("x", risk="low"))
    for msg in ["what is the weather", "", "maybe", "проверь код"]:
        assert gate.classify_user_decision(msg) is None, f"{msg!r}"


def test_needs_confirmation_unknown_is_false():
    gate = _make_gate(_spec("x", risk="low"))
    assert gate.needs_confirmation("nope", {}) is False


def test_signature_is_json_normalized():
    a = ConfirmationGate.signature("t", {"b": 1, "a": 2})
    b = ConfirmationGate.signature("t", {"a": 2, "b": 1})
    assert a == b
