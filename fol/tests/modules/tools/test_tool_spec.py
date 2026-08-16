"""Regression tests for canonical tool metadata.

Covers the Phase 2 tool contract: name, description, schema, risk level,
execution method and confirmation requirement — exposed through
``ToolSpec`` and ``ToolRegistry``.
"""

from __future__ import annotations

import pytest

from modules.tools.base import AbstractTool, Permission, RiskLevel, ToolResult, ToolSpec
from modules.tools.registry import ToolRegistry
from modules.tools.system.execute_command import ExecuteCommand
from modules.tools.desktop.agent_tools import DesktopClick, DesktopScreenshot


# ===========================================================================
# RiskLevel
# ===========================================================================


class TestRiskLevel:
    def test_enum_values(self):
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_from_permission(self):
        assert RiskLevel.from_permission(Permission.NONE) is RiskLevel.LOW
        assert RiskLevel.from_permission(Permission.LOW) is RiskLevel.LOW
        assert RiskLevel.from_permission(Permission.MEDIUM) is RiskLevel.MEDIUM
        assert RiskLevel.from_permission(Permission.HIGH) is RiskLevel.HIGH
        assert RiskLevel.from_permission(Permission.CRITICAL) is RiskLevel.CRITICAL


# ===========================================================================
# AbstractTool defaults + effective risk
# ===========================================================================


class _SilentTool(AbstractTool):
    """Minimal tool for metadata tests (no side effects)."""

    name = "silent"
    description = "does nothing"
    parameters = {"type": "object", "properties": {"x": {"type": "string"}}}

    async def execute(self, params: dict[str, object]) -> ToolResult:
        return ToolResult(success=True, output="ok")


class TestAbstractToolMetadata:
    def test_defaults(self):
        tool = _SilentTool()
        assert tool.risk_level is RiskLevel.LOW
        assert tool.requires_confirmation is False
        assert tool.schema == tool.parameters
        assert tool.effective_risk_level is RiskLevel.LOW

    def test_permissions_drive_effective_risk(self):
        class _PermTool(_SilentTool):
            required_permissions = [Permission.HIGH]

        assert _PermTool().effective_risk_level is RiskLevel.HIGH

    def test_explicit_risk_wins(self):
        class _ExplicitTool(_SilentTool):
            risk_level = RiskLevel.CRITICAL
            requires_confirmation = True

        tool = _ExplicitTool()
        assert tool.effective_risk_level is RiskLevel.CRITICAL
        assert tool.requires_confirmation is True


# ===========================================================================
# ToolSpec
# ===========================================================================


class TestToolSpec:
    def test_fields_and_execution(self):
        tool = _SilentTool()
        spec = tool.to_spec()
        assert spec.name == "silent"
        assert spec.description == "does nothing"
        assert spec.schema == tool.parameters
        assert spec.risk_level is RiskLevel.LOW
        assert spec.requires_confirmation is False
        assert spec.execution is tool

    def test_to_openai_format(self):
        spec = _SilentTool().to_spec()
        converted = spec.to_openai()
        assert converted["type"] == "function"
        assert converted["function"]["name"] == "silent"
        assert converted["function"]["parameters"] == spec.schema

    def test_to_anthropic_format(self):
        spec = _SilentTool().to_spec()
        converted = spec.to_anthropic()
        assert converted["name"] == "silent"
        assert converted["input_schema"] == spec.schema

    def test_frozen(self):
        spec = _SilentTool().to_spec()
        with pytest.raises(Exception):
            spec.name = "other"  # type: ignore[misc]


# ===========================================================================
# Real tools carry the intended risk metadata
# ===========================================================================


class TestRealToolMetadata:
    def test_execute_command_is_high_risk_and_confirmed(self):
        spec = ExecuteCommand().to_spec()
        assert spec.risk_level is RiskLevel.HIGH
        assert spec.requires_confirmation is True

    def test_desktop_click_is_high_risk_and_confirmed(self):
        spec = DesktopClick().to_spec()
        assert spec.risk_level is RiskLevel.HIGH
        assert spec.requires_confirmation is True

    def test_desktop_screenshot_is_low_risk(self):
        spec = DesktopScreenshot().to_spec()
        assert spec.risk_level is RiskLevel.LOW
        assert spec.requires_confirmation is False


# ===========================================================================
# Registry — specs, confirmation gating, anthropic format
# ===========================================================================


class TestRegistrySpecs:
    def _registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(_SilentTool())
        registry.register(ExecuteCommand())
        registry.register(DesktopScreenshot())
        return registry

    def test_specs_lists_all(self):
        registry = self._registry()
        names = {spec.name for spec in registry.specs()}
        assert names == {"silent", "execute_command", "desktop_screenshot"}

    def test_get_spec(self):
        registry = self._registry()
        spec = registry.get_spec("execute_command")
        assert spec is not None
        assert spec.risk_level is RiskLevel.HIGH

    def test_get_spec_missing_returns_none(self):
        assert self._registry().get_spec("nope") is None

    def test_requires_confirmation(self):
        registry = self._registry()
        assert registry.requires_confirmation("execute_command") is True
        assert registry.requires_confirmation("desktop_screenshot") is False

    def test_high_risk_tools(self):
        registry = self._registry()
        high = {spec.name for spec in registry.high_risk_tools()}
        assert high == {"execute_command"}

    def test_to_anthropic_tools(self):
        registry = self._registry()
        converted = registry.to_anthropic_tools()
        assert len(converted) == 3
        assert all("input_schema" in t for t in converted)

    def test_to_openai_tools_unchanged_shape(self):
        registry = self._registry()
        converted = registry.to_openai_tools()
        assert len(converted) == 3
        assert converted[0]["type"] == "function"
