"""Tests for the canonical orchestrator tool catalog (Phase 4).

Verifies the canonical ToolRegistry is the single source of truth for the
orchestrator: registration, lookup, anthropic schema generation, risk levels,
confirmation metadata, argument validation and fail-closed rejection of
unknown/invalid tool calls.
"""

from __future__ import annotations

from modules.tools.orchestrator_tools import build_orchestrator_registry
from modules.tools.registry import ToolRegistry


def _registry() -> ToolRegistry:
    return build_orchestrator_registry()


# --- registration / lookup -------------------------------------------------

def test_registry_builds_all_tools():
    reg = _registry()
    assert reg.count == 50  # 8 browser + 18 desktop + 4 ui + 1 fol + 14 productivity + 5 memory


def test_known_tools_registered():
    reg = _registry()
    for name in ["browser_goto", "open_app", "send_email", "save_to_obsidian", "fol_command",
                 "render_confirm_action", "type_text", "sync_cookies", "search_web"]:
        assert reg.has(name), f"{name} missing"


def test_registry_has_no_unknown_duplicates():
    reg = _registry()
    names = reg.names()
    assert len(names) == len(set(names))


# --- anthropic schema generation ------------------------------------------

def test_anthropic_schemas_valid():
    reg = _registry()
    for spec in reg.specs():
        anth = spec.to_anthropic()
        assert "name" in anth
        assert "description" in anth
        assert "input_schema" in anth
        assert anth["input_schema"].get("type") == "object"


def test_openai_schemas_valid():
    reg = _registry()
    for spec in reg.specs():
        oai = spec.to_openai()
        assert oai["type"] == "function"
        assert oai["function"]["name"]
        assert "parameters" in oai["function"]


# --- risk + confirmation metadata -----------------------------------------

def test_high_risk_tools_require_confirmation():
    reg = _registry()
    for name in ["type_text", "hotkey", "click", "drag", "safari_js",
                 "send_email", "reply_to_email", "share_document", "sync_cookies"]:
        spec = reg.get_spec(name)
        assert spec is not None
        assert spec.requires_confirmation or spec.risk_level.value in ("high", "critical"), name


def test_low_risk_read_tools_not_gated():
    reg = _registry()
    for name in ["browser_snapshot", "browser_text", "clipboard_get", "search_web",
                 "get_daily_summary", "render_confirm_action"]:
        assert not reg.requires_confirmation(name), name


def test_filter_by_category():
    reg = _registry()
    browser = reg.filter(category="browser")
    assert len(browser) == 8
    assert all(s.category == "browser" for s in browser)


def test_filter_by_risk_cap():
    reg = _registry()
    low = reg.filter(risk_at_most="low")
    assert all(s.risk_level.value == "low" for s in low)
    assert len(low) > 0


# --- argument validation (fail closed) ------------------------------------

def test_validate_args_required_missing():
    reg = _registry()
    ok, reason = reg.validate_args("browser_goto", {})
    assert not ok
    assert "required" in reason


def test_validate_args_type_mismatch():
    reg = _registry()
    ok, reason = reg.validate_args("browser_goto", {"url": 42})
    assert not ok
    assert "must be a string" in reason


def test_validate_args_valid():
    reg = _registry()
    ok, reason = reg.validate_args("browser_goto", {"url": "https://example.com"})
    assert ok, reason


def test_validate_args_unknown_tool_rejected():
    reg = _registry()
    ok, reason = reg.validate_args("not_a_real_tool", {})
    assert not ok
    assert "Unknown tool" in reason


def test_validate_args_non_dict_rejected():
    reg = _registry()
    ok, _ = reg.validate_args("browser_goto", ["url"])
    assert not ok
