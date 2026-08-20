"""Tests for RiskScorer and updated ConfirmationGate with 5-level risk scoring."""

from __future__ import annotations

import pytest

from modules.tools.base import RiskLevel, ToolSpec
from modules.tools.gate import ConfirmationGate, GateDecision, RiskLevel5, RiskScorer
from modules.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helper: build a registry with sample tools
# ---------------------------------------------------------------------------

def _make_registry() -> ToolRegistry:
    """Create a ToolRegistry with tools from each risk category."""
    registry = ToolRegistry()

    tools = [
        # Level 1: Safe Read
        ToolSpec(name="screenshot", description="Take screenshot", schema={}, risk_level=RiskLevel.LOW, requires_confirmation=False, category="desktop"),
        ToolSpec(name="read_file", description="Read file", schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, risk_level=RiskLevel.LOW, requires_confirmation=False, category="system"),
        ToolSpec(name="system_info", description="System info", schema={}, risk_level=RiskLevel.LOW, requires_confirmation=False, category="system"),
        # Level 2: UI Navigation
        ToolSpec(name="open_app", description="Open app", schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}, risk_level=RiskLevel.LOW, requires_confirmation=False, category="desktop"),
        ToolSpec(name="browser_goto", description="Navigate", schema={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}, risk_level=RiskLevel.LOW, requires_confirmation=False, category="browser"),
        # Level 3: Interactive GUI
        ToolSpec(name="click", description="Click", schema={"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]}, risk_level=RiskLevel.MEDIUM, requires_confirmation=False, category="desktop"),
        ToolSpec(name="type_text", description="Type text", schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, risk_level=RiskLevel.MEDIUM, requires_confirmation=False, category="desktop"),
        # Level 4: File Mutation
        ToolSpec(name="write_file", description="Write file", schema={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}, risk_level=RiskLevel.HIGH, requires_confirmation=True, category="system"),
        ToolSpec(name="send_email", description="Send email", schema={"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}, risk_level=RiskLevel.HIGH, requires_confirmation=True, category="productivity"),
        # Level 5: System Dangerous
        ToolSpec(name="fol_command", description="FOL command", schema={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}, risk_level=RiskLevel.HIGH, requires_confirmation=True, category="fol"),
        ToolSpec(name="execute_command", description="Execute shell", schema={"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}, risk_level=RiskLevel.CRITICAL, requires_confirmation=True, category="system"),
    ]

    for spec in tools:
        registry.register_spec(spec)
    return registry


# ---------------------------------------------------------------------------
# RiskScorer Tests
# ---------------------------------------------------------------------------

class TestRiskScorer:
    def test_safe_read_tools(self):
        """Level 1: screenshots, read_file, system_info → SAFE_READ."""
        assert RiskScorer.score("screenshot", {}) == RiskLevel5.SAFE_READ
        assert RiskScorer.score("read_file", {"path": "/foo"}) == RiskLevel5.SAFE_READ
        assert RiskScorer.score("system_info", {}) == RiskLevel5.SAFE_READ
        assert RiskScorer.score("browser_snapshot", {}) == RiskLevel5.SAFE_READ
        assert RiskScorer.score("clipboard_get", {}) == RiskLevel5.SAFE_READ

    def test_ui_navigation_tools(self):
        """Level 2: open_app, browser_goto → UI_NAVIGATION."""
        assert RiskScorer.score("open_app", {"name": "Safari"}) == RiskLevel5.UI_NAVIGATION
        assert RiskScorer.score("close_app", {"name": "Safari"}) == RiskLevel5.UI_NAVIGATION
        assert RiskScorer.score("browser_goto", {"url": "https://example.com"}) == RiskLevel5.UI_NAVIGATION
        assert RiskScorer.score("safari_goto", {"url": "https://example.com"}) == RiskLevel5.UI_NAVIGATION
        assert RiskScorer.score("activate_app", {"name": "VS Code"}) == RiskLevel5.UI_NAVIGATION

    def test_interactive_gui_tools(self):
        """Level 3: click, type_text, hotkey → INTERACTIVE_GUI."""
        assert RiskScorer.score("click", {"x": 100, "y": 200}) == RiskLevel5.INTERACTIVE_GUI
        assert RiskScorer.score("type_text", {"text": "hello"}) == RiskLevel5.INTERACTIVE_GUI
        assert RiskScorer.score("hotkey", {"keys": ["command", "c"]}) == RiskLevel5.INTERACTIVE_GUI
        assert RiskScorer.score("browser_click", {"ref": "5"}) == RiskLevel5.INTERACTIVE_GUI
        assert RiskScorer.score("browser_fill", {"ref": "3", "text": "search"}) == RiskLevel5.INTERACTIVE_GUI

    def test_file_mutation_tools(self):
        """Level 4: write_file, send_email, create_event → FILE_MUTATION."""
        assert RiskScorer.score("write_file", {"path": "/foo", "content": "x"}) == RiskLevel5.FILE_MUTATION
        assert RiskScorer.score("send_email", {"to": "a@b.com", "subject": "Hi", "body": "Hello"}) == RiskLevel5.FILE_MUTATION
        assert RiskScorer.score("create_event", {"title": "Meeting", "date": "2026-08-18"}) == RiskLevel5.FILE_MUTATION
        assert RiskScorer.score("send_telegram", {"contact": "user", "message": "hi"}) == RiskLevel5.FILE_MUTATION
        assert RiskScorer.score("save_to_obsidian", {"content": "note"}) == RiskLevel5.FILE_MUTATION

    def test_system_dangerous_tools(self):
        """Level 5: execute_command, fol_command with shell → SYSTEM_DANGEROUS."""
        assert RiskScorer.score("execute_command", {"command": "ls"}) == RiskLevel5.SYSTEM_DANGEROUS
        assert RiskScorer.score("fol_command", {"command": "run ls -la"}) == RiskLevel5.SYSTEM_DANGEROUS
        assert RiskScorer.score("fol_command", {"command": "sudo reboot"}) == RiskLevel5.SYSTEM_DANGEROUS
        assert RiskScorer.score("fol_command", {"command": "osascript -e 'tell app' "}) == RiskLevel5.SYSTEM_DANGEROUS
        assert RiskScorer.score("sync_cookies", {}) == RiskLevel5.SYSTEM_DANGEROUS

    def test_fol_command_non_shell(self):
        """fol_command without shell markers → FILE_MUTATION (Level 4)."""
        assert RiskScorer.score("fol_command", {"command": "screenshot"}) == RiskLevel5.FILE_MUTATION
        assert RiskScorer.score("fol_command", {"command": "system status"}) == RiskLevel5.FILE_MUTATION

    def test_unknown_tool_default(self):
        """Unknown tools default to INTERACTIVE_GUI (Level 3)."""
        assert RiskScorer.score("unknown_tool_xyz", {}) == RiskLevel5.INTERACTIVE_GUI

    def test_to_decision_mapping(self):
        """RiskLevel5 maps to correct GateDecision."""
        assert RiskScorer.to_decision(RiskLevel5.SAFE_READ) == GateDecision.OK
        assert RiskScorer.to_decision(RiskLevel5.UI_NAVIGATION) == GateDecision.OK
        assert RiskScorer.to_decision(RiskLevel5.INTERACTIVE_GUI) == GateDecision.PEEK_CONFIRM
        assert RiskScorer.to_decision(RiskLevel5.FILE_MUTATION) == GateDecision.CONFIRM
        assert RiskScorer.to_decision(RiskLevel5.SYSTEM_DANGEROUS) == GateDecision.STRICT_CONFIRM


# ---------------------------------------------------------------------------
# ConfirmationGate with Risk Scoring Tests
# ---------------------------------------------------------------------------

class TestConfirmationGateRiskScoring:
    def test_safe_read_passes(self):
        """Level 1 tools pass through without confirmation."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        decision, action_id = gate.check("screenshot", {})
        assert decision == GateDecision.OK
        assert action_id is None

    def test_ui_navigation_passes(self):
        """Level 2 tools pass through without confirmation."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        decision, action_id = gate.check("open_app", {"name": "Safari"})
        assert decision == GateDecision.OK
        assert action_id is None

    def test_interactive_peek_confirm(self):
        """Level 3 tools get PEEK_CONFIRM."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        decision, action_id = gate.check("click", {"x": 100, "y": 200})
        assert decision == GateDecision.PEEK_CONFIRM
        assert action_id is not None

    def test_file_mutation_confirm(self):
        """Level 4 tools get CONFIRM."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        decision, action_id = gate.check("write_file", {"path": "/foo", "content": "x"})
        assert decision == GateDecision.CONFIRM
        assert action_id is not None

    def test_system_dangerous_strict(self):
        """Level 5 tools get STRICT_CONFIRM."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        decision, action_id = gate.check("fol_command", {"command": "sudo rm -rf /"})
        assert decision == GateDecision.STRICT_CONFIRM
        assert action_id is not None

    def test_unknown_tool_rejects(self):
        """Unknown tools get REJECT."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        decision, action_id = gate.check("nonexistent_tool", {})
        assert decision == GateDecision.REJECT
        assert action_id is None

    def test_approved_bypasses_gate(self):
        """Approved signatures bypass the gate (return OK)."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        # First call → CONFIRM
        decision1, action_id = gate.check("write_file", {"path": "/foo", "content": "x"})
        assert decision1 == GateDecision.CONFIRM
        # Approve
        gate.approve(action_id)
        # Second call → OK (approved)
        decision2, _ = gate.check("write_file", {"path": "/foo", "content": "x"})
        assert decision2 == GateDecision.OK

    def test_score_risk_method(self):
        """score_risk returns RiskLevel5."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        assert gate.score_risk("screenshot", {}) == RiskLevel5.SAFE_READ
        assert gate.score_risk("click", {"x": 0, "y": 0}) == RiskLevel5.INTERACTIVE_GUI
        assert gate.score_risk("fol_command", {"command": "sudo ls"}) == RiskLevel5.SYSTEM_DANGEROUS

    def test_needs_confirmation_uses_risk_level(self):
        """needs_confirmation uses the 5-level risk scoring."""
        registry = _make_registry()
        gate = ConfirmationGate(registry)
        # Level 1-2: no confirmation
        assert gate.needs_confirmation("screenshot", {}) is False
        assert gate.needs_confirmation("open_app", {"name": "Safari"}) is False
        # Level 3-5: confirmation needed
        assert gate.needs_confirmation("click", {"x": 0, "y": 0}) is True
        assert gate.needs_confirmation("write_file", {"path": "/x", "content": "y"}) is True
        assert gate.needs_confirmation("fol_command", {"command": "sudo ls"}) is True
