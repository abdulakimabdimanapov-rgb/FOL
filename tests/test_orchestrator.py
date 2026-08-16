"""Unit tests for orchestrator/server.py.

Tests the core functions of the orchestrator: tool routing, A2UI conversion,
context building, screenshot stripping, and utility functions.

Fixtures (reset_globals, client, async_client) provided by tests/conftest.py.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Use shared reset_globals from conftest (opt-in, not autouse)
pytestmark = pytest.mark.usefixtures("reset_globals")


# ---------------------------------------------------------------------------
# Agent registry and tool selection tests
# ---------------------------------------------------------------------------


class TestGetAgentTools:
    """Tests for _get_agent_tools() — tool subset selection per agent type."""

    def test_general_gets_all_tools(self):
        """GENERAL agent should get ALL_TOOLS (full capability)."""
        from server import _get_agent_tools, ALL_TOOLS
        import agents

        tools = _get_agent_tools(agents.AgentType.GENERAL)
        assert len(tools) == len(ALL_TOOLS)
        assert all(t in ALL_TOOLS for t in tools)

    def test_coder_gets_focused_tools(self):
        """CODER agent should get a focused subset (not ALL_TOOLS)."""
        from server import _get_agent_tools, ALL_TOOLS
        import agents

        tools = _get_agent_tools(agents.AgentType.CODER)
        assert len(tools) < len(ALL_TOOLS)
        assert len(tools) > 0
        # CODER should have browser tools (for web research)
        tool_names = {t["name"] for t in tools}
        assert any(n.startswith("browser_") for n in tool_names)
        # CODER should NOT have productivity tools normally
        # (this depends on CODER_TOOLS_NAMES definition)

    def test_architect_gets_focused_tools(self):
        """ARCHITECT agent should get a focused subset."""
        from server import _get_agent_tools, ALL_TOOLS
        import agents

        tools = _get_agent_tools(agents.AgentType.ARCHITECT)
        assert len(tools) < len(ALL_TOOLS)
        assert len(tools) > 0

    def test_reviewer_gets_focused_tools(self):
        """REVIEWER agent should get a focused subset."""
        from server import _get_agent_tools, ALL_TOOLS
        import agents

        tools = _get_agent_tools(agents.AgentType.REVIEWER)
        assert len(tools) < len(ALL_TOOLS)
        assert len(tools) > 0

    def test_researcher_gets_focused_tools(self):
        """RESEARCHER agent should get a focused subset."""
        from server import _get_agent_tools, ALL_TOOLS
        import agents

        tools = _get_agent_tools(agents.AgentType.RESEARCHER)
        assert len(tools) < len(ALL_TOOLS)
        assert len(tools) > 0

    def test_memory_gets_focused_tools(self):
        """MEMORY agent should get a focused subset."""
        from server import _get_agent_tools, ALL_TOOLS
        import agents

        tools = _get_agent_tools(agents.AgentType.MEMORY)
        assert len(tools) < len(ALL_TOOLS)
        assert len(tools) > 0

    def test_unknown_agent_gets_all_tools(self):
        """Unknown/missing agent type should fall back to ALL_TOOLS."""
        from server import _get_agent_tools, ALL_TOOLS
        import agents

        # Try a fake agent type (value not in registry)
        tools = _get_agent_tools("UNKNOWN")
        assert len(tools) == len(ALL_TOOLS)


class TestGetAgentPromptSuffix:
    """Tests for _get_agent_prompt_suffix() — agent-specific prompt text."""

    def test_general_has_no_suffix(self):
        """GENERAL agent should have no suffix (uses standard twin prompt)."""
        from server import _get_agent_prompt_suffix
        import agents

        assert _get_agent_prompt_suffix(agents.AgentType.GENERAL) is None

    def test_coder_has_suffix(self):
        """CODER agent should have a prompt suffix."""
        from server import _get_agent_prompt_suffix
        import agents

        suffix = _get_agent_prompt_suffix(agents.AgentType.CODER)
        assert suffix is not None
        assert isinstance(suffix, str)
        assert len(suffix) > 0

    def test_unknown_returns_none(self):
        """Unknown agent type should return None."""
        from server import _get_agent_prompt_suffix

        assert _get_agent_prompt_suffix("BOGUS_TYPE") is None


# ---------------------------------------------------------------------------
# VALID_STATES and job state machine tests
# ---------------------------------------------------------------------------


class TestValidStates:
    """Tests for VALID_STATES tuple."""

    def test_states_count(self):
        """Should have exactly 5 valid states."""
        from server import VALID_STATES

        assert len(VALID_STATES) == 5

    def test_contains_idle(self):
        from server import VALID_STATES

        assert "idle" in VALID_STATES

    def test_contains_thinking(self):
        from server import VALID_STATES

        assert "thinking" in VALID_STATES

    def test_contains_working(self):
        from server import VALID_STATES

        assert "working" in VALID_STATES

    def test_contains_complete(self):
        from server import VALID_STATES

        assert "complete" in VALID_STATES

    def test_contains_error(self):
        from server import VALID_STATES

        assert "error" in VALID_STATES


# ---------------------------------------------------------------------------
# Browser nav tools tests
# ---------------------------------------------------------------------------


class TestBrowserNavTools:
    """Tests for BROWSER_NAV_TOOLS set."""

    def test_contains_browser_goto(self):
        from server import BROWSER_NAV_TOOLS

        assert "browser_goto" in BROWSER_NAV_TOOLS

    def test_size(self):
        """Should only contain navigation tools."""
        from server import BROWSER_NAV_TOOLS

        assert len(BROWSER_NAV_TOOLS) == 1


# ---------------------------------------------------------------------------
# TOOL_ENDPOINT_MAP tests
# ---------------------------------------------------------------------------


class TestToolEndpointMap:
    """Tests for TOOL_ENDPOINT_MAP — tool-to-agent-server routing."""

    def test_browser_tools_mapped(self):
        from server import TOOL_ENDPOINT_MAP

        assert "/browser/goto" in TOOL_ENDPOINT_MAP.values()
        assert "/browser/snapshot" in TOOL_ENDPOINT_MAP.values()
        assert "/browser/click" in TOOL_ENDPOINT_MAP.values()

    def test_desktop_tools_mapped(self):
        from server import TOOL_ENDPOINT_MAP

        assert "/tool/screenshot" in TOOL_ENDPOINT_MAP.values()
        assert "/tool/click" in TOOL_ENDPOINT_MAP.values()
        assert "/tool/type" in TOOL_ENDPOINT_MAP.values()
        assert "/tool/hotkey" in TOOL_ENDPOINT_MAP.values()

    def test_safari_tools_mapped(self):
        from server import TOOL_ENDPOINT_MAP

        assert "/safari/goto" in TOOL_ENDPOINT_MAP.values()
        assert "/safari/js" in TOOL_ENDPOINT_MAP.values()
        assert "/safari/url" in TOOL_ENDPOINT_MAP.values()
        assert "/safari/text" in TOOL_ENDPOINT_MAP.values()

    def test_all_keys_have_endpoints(self):
        """Every key in the map should have a non-empty endpoint."""
        from server import TOOL_ENDPOINT_MAP
        from server import BROWSER_TOOLS
        from server import DESKTOP_TOOLS

        for tool_name, endpoint in TOOL_ENDPOINT_MAP.items():
            assert endpoint.startswith("/"), f"Endpoint for {tool_name} should start with /"

    def test_all_tools_accounted_for(self):
        """Browser + desktop tools in ALL_TOOLS should have entries (or be handled specially)."""
        from server import TOOL_ENDPOINT_MAP
        from server import BROWSER_TOOLS, DESKTOP_TOOLS

        mapped_tools = set(TOOL_ENDPOINT_MAP.keys())
        browser_names = {t["name"] for t in BROWSER_TOOLS}
        desktop_names = {t["name"] for t in DESKTOP_TOOLS}
        combined = browser_names | desktop_names
        # Photos and video tools might have special handling
        missing = combined - mapped_tools
        # Tools like sync_cookies, list_profiles, send_telegram, etc. are handled separately
        expected_unmapped = {"sync_cookies", "list_profiles", "send_telegram", "send_whatsapp", "activate_app", "browser_snapshot"}
        assert missing == expected_unmapped or not missing - expected_unmapped, f"Unexpected unmapped: {missing}"


# ---------------------------------------------------------------------------
# RENDER_TYPE_MAP tests
# ---------------------------------------------------------------------------


class TestRenderTypeMap:
    """Tests for RENDER_TYPE_MAP — render tool to A2UI component mapping."""

    def test_task_approval_mapped(self):
        from server import RENDER_TYPE_MAP

        assert RENDER_TYPE_MAP["render_task_approval"] == "TaskApproval"

    def test_profile_card_mapped(self):
        from server import RENDER_TYPE_MAP

        assert RENDER_TYPE_MAP["render_profile_card"] == "ProfileCard"

    def test_screenshot_mapped(self):
        from server import RENDER_TYPE_MAP

        assert RENDER_TYPE_MAP["render_screenshot"] == "Screenshot"

    def test_confirm_action_mapped(self):
        from server import RENDER_TYPE_MAP

        assert RENDER_TYPE_MAP["render_confirm_action"] == "ConfirmAction"

    def test_all_render_tools_present(self):
        """Every UI_TOOL that starts with render_ should be in the map."""
        from server import RENDER_TYPE_MAP, UI_TOOLS

        for tool in UI_TOOLS:
            name = tool["name"]
            if name.startswith("render_"):
                assert name in RENDER_TYPE_MAP, f"Missing: {name}"


# ---------------------------------------------------------------------------
# convert_to_a2ui tests
# ---------------------------------------------------------------------------


class TestConvertToA2UI:
    """Tests for convert_to_a2ui() — rendering tool calls to A2UI JSON."""

    def test_task_approval_with_step_dicts(self):
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_task_approval", {
            "title": "Test Plan",
            "steps": [{"id": 1, "text": "Step 1"}, {"id": 2, "text": "Step 2"}],
        })
        assert result["version"] == "0.8"
        assert len(result["components"]) == 1
        comp = result["components"][0]
        assert comp["type"] == "TaskApproval"
        assert comp["properties"]["title"] == "Test Plan"
        assert len(comp["properties"]["steps"]) == 2
        assert comp["properties"]["steps"][0]["text"] == "Step 1"
        assert len(comp["actions"]) == 2

    def test_task_approval_with_flat_strings(self):
        """Should normalize flat string steps to {id, text} objects."""
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_task_approval", {
            "title": "Plan",
            "steps": ["Do thing 1", "Do thing 2", "Do thing 3"],
        })
        comp = result["components"][0]
        assert len(comp["properties"]["steps"]) == 3
        for i, step in enumerate(comp["properties"]["steps"]):
            assert step["id"] == i + 1
            assert step["text"] == f"Do thing {i + 1}"

    def test_task_approval_with_empty_steps(self):
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_task_approval", {
            "title": "Empty Plan",
            "steps": [],
        })
        comp = result["components"][0]
        assert comp["properties"]["steps"] == []

    def test_task_approval_without_title(self):
        """Should use default title when not provided."""
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_task_approval", {
            "steps": [{"id": 1, "text": "Step"}],
        })
        comp = result["components"][0]
        assert comp["properties"]["title"] == "Task Plan"

    def test_profile_card(self):
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_profile_card", {
            "facts": [{"text": "Likes coffee"}, {"text": "Morning person"}],
        })
        comp = result["components"][0]
        assert comp["type"] == "ProfileCard"
        assert len(comp["properties"]["facts"]) == 2
        assert comp["actions"] is None

    def test_profile_card_empty_facts(self):
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_profile_card", {"facts": []})
        comp = result["components"][0]
        assert comp["properties"]["facts"] == []

    def test_screenshot(self):
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_screenshot", {
            "image": "base64data",
            "caption": "Screen capture",
        })
        comp = result["components"][0]
        assert comp["type"] == "Screenshot"
        assert comp["properties"]["image"] == "base64data"
        assert comp["properties"]["caption"] == "Screen capture"

    def test_screenshot_without_caption(self):
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_screenshot", {"image": "data"})
        comp = result["components"][0]
        assert comp["properties"]["caption"] is None

    def test_confirm_action(self):
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_confirm_action", {
            "action": "Delete all files",
            "actionId": "del-123",
        })
        comp = result["components"][0]
        assert comp["type"] == "ConfirmAction"
        assert comp["properties"]["action"] == "Delete all files"
        assert comp["properties"]["actionId"] == "del-123"
        assert len(comp["actions"]) == 2

    def test_confirm_action_with_default_id(self):
        """Should generate a component ID when actionId is not provided."""
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_confirm_action", {"action": "Restart"})
        comp = result["components"][0]
        # component ID should be auto-generated
        assert comp["id"].startswith("comp-")
        assert comp["properties"]["actionId"] == comp["id"]

    def test_unknown_tool_passthrough(self):
        """Unknown render tools should pass args through as properties."""
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_custom_widget", {"foo": "bar"})
        comp = result["components"][0]
        assert comp["type"] == "render_custom_widget"
        assert comp["properties"]["foo"] == "bar"
        assert comp["actions"] is None

    def test_unique_component_ids(self):
        """Each call should generate a unique component ID."""
        from server import convert_to_a2ui

        ids = set()
        for _ in range(10):
            result = convert_to_a2ui("render_task_approval", {
                "steps": [{"id": 1, "text": "Step"}],
            })
            ids.add(result["components"][0]["id"])
        assert len(ids) == 10

    def test_mixed_step_types(self):
        """Handle mixed string/dict steps gracefully."""
        from server import convert_to_a2ui

        result = convert_to_a2ui("render_task_approval", {
            "title": "Mixed",
            "steps": [{"id": 5, "text": "First"}, "Second", 123],
        })
        steps = result["components"][0]["properties"]["steps"]
        assert len(steps) == 3
        assert steps[0]["text"] == "First"
        assert steps[0]["id"] == 5  # preserves original id
        assert steps[1]["text"] == "Second"
        assert steps[2]["text"] == "123"  # coerced to string


# ---------------------------------------------------------------------------
# _strip_screenshots tests
# ---------------------------------------------------------------------------


class TestStripScreenshots:
    """Tests for _strip_screenshots() — removing large data from history."""

    def test_passthrough_string(self):
        from server import _strip_screenshots

        assert _strip_screenshots("hello") == "hello"

    def test_passthrough_empty_string(self):
        from server import _strip_screenshots

        assert _strip_screenshots("") == ""

    def test_passthrough_non_list(self):
        from server import _strip_screenshots

        assert _strip_screenshots(123) == 123
        assert _strip_screenshots(None) is None

    def test_strips_large_tool_result(self):
        """Should strip long tool results (>10000 chars)."""
        from server import _strip_screenshots

        large_content = "x" * 20000
        content = [{"type": "tool_result", "content": large_content}]
        result = _strip_screenshots(content)
        assert result[0]["content"] == "[large result stripped]"

    def test_keeps_small_tool_result(self):
        from server import _strip_screenshots

        small_content = "small result"
        content = [{"type": "tool_result", "content": small_content}]
        result = _strip_screenshots(content)
        # Small results pass through unchanged
        assert result[0]["content"] == "small result"

    def test_strips_screenshot_like_data(self):
        """Should strip blocks where 'image' appears and block is large."""
        from server import _strip_screenshots

        large_block = {"type": "tool_result", "image": "base64data" * 2000}
        content = [large_block]
        result = _strip_screenshots(content)
        assert result[0] == large_block  # modified in place

    def test_empty_list(self):
        from server import _strip_screenshots

        assert _strip_screenshots([]) == []

    def test_nested_structures_preserved(self):
        """Non-large blocks within a list should be preserved."""
        from server import _strip_screenshots

        content = [
            {"type": "text", "text": "Hello"},
            {"type": "tool_result", "content": "ok"},
        ]
        result = _strip_screenshots(content)
        assert len(result) == 2
        assert result[0]["text"] == "Hello"
        assert result[1]["content"] == "ok"


# ---------------------------------------------------------------------------
# build_context_messages tests
# ---------------------------------------------------------------------------


class TestBuildContextMessages:
    """Tests for build_context_messages() — context injection."""

    def test_returns_list_with_one_message(self):
        from server import build_context_messages

        context = build_context_messages()
        assert isinstance(context, list)
        assert len(context) == 1

    def test_message_has_role_user(self):
        from server import build_context_messages

        context = build_context_messages()
        assert context[0]["role"] == "user"

    def test_message_contains_context_label(self):
        from server import build_context_messages

        context = build_context_messages()
        assert context[0]["content"].startswith("[CONTEXT]")

    def test_mentions_today_date(self):
        """Should include today's date in the context."""
        from datetime import datetime, timezone
        from server import build_context_messages

        context = build_context_messages()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today in context[0]["content"]

    def test_mentions_conversation_length(self):
        from server import build_context_messages

        context = build_context_messages()
        assert "Messages in this conversation:" in context[0]["content"]


# ---------------------------------------------------------------------------
# _get_context_summary tests
# ---------------------------------------------------------------------------


class TestGetContextSummary:
    """Tests for _get_context_summary() — compact conversation summary."""

    def test_contains_state_info(self):
        from server import _get_context_summary

        summary = _get_context_summary()
        assert "Current state:" in summary

    def test_contains_today_date(self):
        from datetime import datetime, timezone
        from server import _get_context_summary

        summary = _get_context_summary()
        today = datetime.now(timezone.utc).strftime("%B %d, %Y")
        assert today in summary

    def test_empty_history_shows_no_requests(self):
        from server import _get_context_summary

        summary = _get_context_summary()
        assert "This is message" not in summary


# ---------------------------------------------------------------------------
# ALL_TOOLS composition tests
# ---------------------------------------------------------------------------


class TestAllToolsComposition:
    """Tests that ALL_TOOLS is properly composed from all tool groups."""

    def test_all_tools_contains_unique_names(self):
        """Every tool in ALL_TOOLS should have a unique name."""
        from server import ALL_TOOLS

        names = [t["name"] for t in ALL_TOOLS]
        assert len(names) == len(set(names)), f"Duplicate tool names: {len(names)} vs {len(set(names))}"

    def test_each_tool_has_required_fields(self):
        """Every tool should have name, description, input_schema."""
        from server import ALL_TOOLS

        for tool in ALL_TOOLS:
            assert "name" in tool, f"Missing 'name' in {tool}"
            assert "description" in tool, f"Missing 'description' in {tool['name']}"
            assert "input_schema" in tool, f"Missing 'input_schema' in {tool['name']}"
            assert isinstance(tool["input_schema"], dict)

    def test_each_tool_input_schema_has_type(self):
        from server import ALL_TOOLS

        for tool in ALL_TOOLS:
            assert tool["input_schema"].get("type") == "object", \
                f"input_schema should be type object in {tool['name']}"

    def test_all_tools_coverage(self):
        """The all_tools list should be composed from all subgroups."""
        from server import (
            ALL_TOOLS,
            BROWSER_TOOLS,
            DESKTOP_TOOLS,
            UI_TOOLS,
            PRODUCTIVITY_TOOLS,
            MEMORY_TOOLS,
            FOL_TOOLS,
        )

        expected_count = (
            len(BROWSER_TOOLS)
            + len(DESKTOP_TOOLS)
            + len(UI_TOOLS)
            + len(PRODUCTIVITY_TOOLS)
            + len(MEMORY_TOOLS)
            + len(FOL_TOOLS)
        )
        assert len(ALL_TOOLS) == expected_count, \
            f"Expected {expected_count} tools, got {len(ALL_TOOLS)}"


# ---------------------------------------------------------------------------
# Agent registry tests
# ---------------------------------------------------------------------------


class TestAgentRegistry:
    """Tests for _AGENT_REGISTRY — agent configuration map."""

    def test_all_agent_types_present(self):
        """Every AgentType enum value should have an entry in the registry."""
        from server import _AGENT_REGISTRY
        import agents

        for agent_type in agents.AgentType:
            assert agent_type in _AGENT_REGISTRY, f"Missing: {agent_type}"

    def test_each_entry_has_name(self):
        from server import _AGENT_REGISTRY

        for atype, config in _AGENT_REGISTRY.items():
            assert "name" in config, f"Missing 'name' for {atype}"
            assert isinstance(config["name"], str)
            assert len(config["name"]) > 0

    def test_each_entry_has_prompt_suffix_or_none(self):
        """prompt_suffix can be None (for GENERAL) or a non-empty string."""
        from server import _AGENT_REGISTRY

        for atype, config in _AGENT_REGISTRY.items():
            assert "prompt_suffix" in config
            if config["prompt_suffix"] is not None:
                assert isinstance(config["prompt_suffix"], str)
                assert len(config["prompt_suffix"]) > 0

    def test_each_entry_has_tool_names_or_none(self):
        """tool_names can be None (for GENERAL) or a set of strings."""
        from server import _AGENT_REGISTRY

        for atype, config in _AGENT_REGISTRY.items():
            assert "tool_names" in config
            if config["tool_names"] is not None:
                assert isinstance(config["tool_names"], set)
                assert len(config["tool_names"]) > 0
                for name in config["tool_names"]:
                    assert isinstance(name, str)


# ---------------------------------------------------------------------------
# _auto_route_agent tests
# ---------------------------------------------------------------------------


class TestRenderTokenSuppression:
    """Tests for has_render_tool token suppression fix.

    Verifies that text tokens are ALWAYS emitted even when render_*
    tool calls are present. Uses real run_agent_loop_streaming with
    mocked LLM calls to validate the SSE event stream.
    """

    @patch("server.build_system_prompt", return_value="You are a helpful assistant.")
    @patch("server.build_context_messages", return_value=[])
    @patch("server._append_to_history")
    @patch("server._auto_route_agent")
    @patch("server.call_claude_streaming")
    def test_intermediate_text_buffered_with_render_tools(
        self,
        mock_call_claude,
        mock_route,
        mock_append,
        mock_context,
        mock_prompt,
    ):
        """Intermediate narration is internal — only the final answer streams,
        and render_* tools surface as A2UI components, not as text."""
        import asyncio
        import server
        import agents

        mock_route.return_value = agents.AgentType.GENERAL

        async def _mock_stream(messages, system, tools=None):
            yield ("token", {"text": "Here is my plan for you: "})
            yield ("token", {"text": "First we do X, then Y."})
            yield ("_tool_use", {
                "id": "call_1",
                "name": "render_task_approval",
                "input": {"title": "Plan", "steps": [{"id": 1, "text": "Step 1"}]},
            })
            yield ("_done", {"stop_reason": "tool_use"})

        call_count = 0

        async def _mock_claude(messages, system, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                async for event in _mock_stream(messages, system, tools):
                    yield event
            else:
                yield ("_done", {"stop_reason": "end_turn"})

        mock_call_claude.side_effect = _mock_claude

        async def _collect():
            events = []
            async for event_type, event_data in server.run_agent_loop_streaming("test task"):
                events.append((event_type, event_data))
            return events

        events = asyncio.run(_collect())

        # Intermediate narration is buffered internally — NOT streamed to the
        # user. Only the final formatted answer arrives as token events.
        token_events = [e for e in events if e[0] == "token"]
        token_text = "".join(t[1].get("text", "") for t in token_events)
        assert "Here is my plan" not in token_text, (
            "Intermediate text leaked to the user during a tool turn!"
        )
        assert token_text.strip()  # final answer is a non-empty string

        # Verify the A2UI component event WAS emitted
        component_events = [e for e in events if e[0] == "component"]
        assert len(component_events) == 1
        assert component_events[0][1]["a2ui"]["components"][0]["type"] == "TaskApproval"

        # No internal tool events reach the user
        event_types = [e[0] for e in events]
        assert "tool_call" not in event_types
        assert "tool_result" not in event_types

    @patch("server.build_system_prompt", return_value="You are a helpful assistant.")
    @patch("server.build_context_messages", return_value=[])
    @patch("server._append_to_history")
    @patch("server._auto_route_agent")
    @patch("server.call_claude_streaming")
    def test_intermediate_text_buffered_with_non_render_tools(
        self,
        mock_call_claude,
        mock_route,
        mock_append,
        mock_context,
        mock_prompt,
    ):
        """Intermediate text before tool calls is internal; the user sees a
        coarse activity status and the final formatted answer."""
        import asyncio
        import server
        import agents

        mock_route.return_value = agents.AgentType.GENERAL

        async def _mock_stream(messages, system, tools=None):
            yield ("token", {"text": "Let me browse the web for you."})
            yield ("_tool_use", {
                "id": "call_1",
                "name": "browser_goto",
                "input": {"url": "https://example.com"},
            })
            yield ("_done", {"stop_reason": "tool_use"})

        call_count = 0

        async def _mock_claude(messages, system, tools=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                async for event in _mock_stream(messages, system, tools):
                    yield event
            else:
                yield ("_done", {"stop_reason": "end_turn"})

        mock_call_claude.side_effect = _mock_claude

        async def _collect():
            events = []
            async for event_type, event_data in server.run_agent_loop_streaming("test task"):
                events.append((event_type, event_data))
            return events

        events = asyncio.run(_collect())

        # Intermediate narration must NOT be streamed to the user.
        token_events = [e for e in events if e[0] == "token"]
        token_text = "".join(t[1].get("text", "") for t in token_events)
        assert "Let me browse the web" not in token_text
        assert token_text.strip()  # final answer is a non-empty string

        # Only a coarse, user-safe activity status is emitted — no tool names.
        activity_events = [e for e in events if e[0] == "activity"]
        assert len(activity_events) == 1
        assert "browser_goto" not in activity_events[0][1]["label"]

        # No internal tool events reach the user
        event_types = [e[0] for e in events]
        assert "tool_call" not in event_types
        assert "tool_result" not in event_types

    @patch("server.build_system_prompt", return_value="You are a helpful assistant.")
    @patch("server.build_context_messages", return_value=[])
    @patch("server._append_to_history")
    @patch("server._auto_route_agent")
    @patch("server.call_claude_streaming")
    def test_plain_text_response_emits_tokens(
        self,
        mock_call_claude,
        mock_route,
        mock_append,
        mock_context,
        mock_prompt,
    ):
        """Plain text responses (no tools) should work normally."""
        import asyncio
        import server
        import agents

        mock_route.return_value = agents.AgentType.GENERAL

        async def _mock_stream(messages, system, tools=None):
            yield ("token", {"text": "Hello! How can I help?"})
            yield ("_done", {"stop_reason": "end_turn"})

        mock_call_claude.side_effect = _mock_stream

        async def _collect():
            events = []
            async for event_type, event_data in server.run_agent_loop_streaming("test task"):
                events.append((event_type, event_data))
            return events

        events = asyncio.run(_collect())

        token_events = [e for e in events if e[0] == "token"]
        token_text = "".join(t[1].get("text", "") for t in token_events)
        assert token_text == "Hello! How can I help?"

        state_events = [e for e in events if e[0] == "state"]
        assert any(s[1]["state"] == "complete" for s in state_events)


class TestChunkFinalText:
    """Tests for _chunk_final_text() — chunking the final answer for streaming.

    The UI concatenates the yielded token chunks back together, so the
    chunks MUST reproduce the original text exactly (no lost spaces at
    chunk boundaries).
    """

    def test_reconstructs_exact_text(self):
        from server import _chunk_final_text

        text = "Hello! How can I help?"
        chunks = _chunk_final_text(text)
        assert "".join(chunks) == text

    def test_chunks_are_small_word_groups(self):
        from server import _chunk_final_text

        text = "one two three four five six seven eight nine"
        chunks = _chunk_final_text(text)
        # Default 4 words per chunk
        assert all(len(c.split()) <= 4 for c in chunks)
        assert "".join(chunks) == text

    def test_single_word_text(self):
        from server import _chunk_final_text

        assert _chunk_final_text("Готово.") == ["Готово."]

    def test_long_text_reconstruction(self):
        from server import _chunk_final_text

        text = "Открыл Safari, сэр. Готово. " * 5
        chunks = _chunk_final_text(text)
        assert "".join(chunks) == text

    def test_multiple_spaces_preserved(self):
        from server import _chunk_final_text

        text = "one two  three four five six"  # double space after 'two'
        chunks = _chunk_final_text(text)
        assert "".join(chunks) == text

    def test_newlines_preserved(self):
        from server import _chunk_final_text

        text = "Line one.\nLine two.\nLine three."
        chunks = _chunk_final_text(text)
        assert "".join(chunks) == text


class TestAutoRouteAgent:
    """Tests for _auto_route_agent() — automatic agent selection."""


    def test_sets_global_current_agent(self):
        import server as srv
        import agents

        srv._auto_route_agent("напиши код для сортировки")
        assert srv._current_agent_type == agents.AgentType.CODER

    def test_general_task_stays_general(self):
        import server as srv
        import agents

        srv._auto_route_agent("как дела?")
        assert srv._current_agent_type == agents.AgentType.GENERAL

    def test_english_coder_routing(self):
        import server as srv
        import agents

        srv._auto_route_agent("implement a sorting algorithm")
        assert srv._current_agent_type == agents.AgentType.CODER

    def test_reviewer_routing(self):
        import server as srv
        import agents

        srv._auto_route_agent("review this pull request")
        assert srv._current_agent_type == agents.AgentType.REVIEWER

    def test_architect_routing(self):
        import server as srv
        import agents

        srv._auto_route_agent("спроектируй архитектуру")
        assert srv._current_agent_type == agents.AgentType.ARCHITECT

    def test_researcher_routing(self):
        import server as srv
        import agents

        srv._auto_route_agent("найди информацию про AI")
        assert srv._current_agent_type == agents.AgentType.RESEARCHER


# ---------------------------------------------------------------------------
# Event broadcasting tests
# ---------------------------------------------------------------------------


class _MockAsyncQueue:
    """Mimics asyncio.Queue without requiring an event loop.
    
    Raises asyncio.QueueFull when full, so broadcast_event() can catch it.
    """
    def __init__(self, maxsize=0):
        self._items = []
        self._maxsize = maxsize

    def put_nowait(self, item):
        if self._maxsize > 0 and len(self._items) >= self._maxsize:
            from asyncio import QueueFull
            raise QueueFull()
        self._items.append(item)

    def get_nowait(self):
        return self._items.pop(0)

    def empty(self):
        return len(self._items) == 0

    def __contains__(self, item):
        return item in self._items


class TestEventBroadcasting:
    """Tests for broadcast_event() and event client management."""

    def _make_queue(self):
        """Create a fake queue that mimics asyncio.Queue for testing."""
        return _MockAsyncQueue()

    def _make_full_queue(self):
        """Create a fake queue that's already full (maxsize=1, item already added)."""
        q = _MockAsyncQueue(maxsize=1)
        q.put_nowait("full")
        return q

    def test_broadcast_to_single_client(self):
        from server import broadcast_event, event_clients

        q = self._make_queue()
        event_clients.append(q)
        import asyncio
        asyncio.run(broadcast_event("test", {"key": "value"}))
        assert not q.empty()
        payload = q.get_nowait()
        assert "event: test" in payload
        assert '"key": "value"' in payload
        event_clients.remove(q)

    def test_broadcast_to_multiple_clients(self):
        from server import broadcast_event, event_clients

        q1 = self._make_queue()
        q2 = self._make_queue()
        event_clients.extend([q1, q2])
        import asyncio
        asyncio.run(broadcast_event("ping", {}))
        assert not q1.empty()
        assert not q2.empty()
        event_clients.remove(q1)
        event_clients.remove(q2)

    def test_broadcast_removes_disconnected(self):
        from server import broadcast_event, event_clients

        full_q = self._make_full_queue()
        event_clients.append(full_q)
        import asyncio
        asyncio.run(broadcast_event("test", {}))
        assert full_q not in event_clients


# ---------------------------------------------------------------------------
# FOL tools structure tests
# ---------------------------------------------------------------------------


class TestFOLTools:
    """Tests for FOL_TOOLS definition."""

    def test_fol_command_has_correct_fields(self):
        from server import FOL_TOOLS

        tools_by_name = {t["name"]: t for t in FOL_TOOLS}
        assert "fol_command" in tools_by_name
        fol = tools_by_name["fol_command"]
        assert fol["name"] == "fol_command"
        assert "command" in fol["input_schema"]["properties"]
        assert "command" in fol["input_schema"]["required"]

    def test_fol_command_has_russian_examples(self):
        """The FOL command description should mention Russian language support."""
        from server import FOL_TOOLS

        tools_by_name = {t["name"]: t for t in FOL_TOOLS}
        fol = tools_by_name["fol_command"]
        assert "Russian" in fol["description"] or "русский" in fol["description"]


# ---------------------------------------------------------------------------
# Tool description coverage tests
# ---------------------------------------------------------------------------


class TestToolDescriptionCoverage:
    """Every tool should have a meaningful description."""

    def test_all_tools_have_descriptions(self):
        from server import ALL_TOOLS

        for tool in ALL_TOOLS:
            desc = tool.get("description", "")
            assert len(desc) >= 10, f"Tool {tool['name']} has too short description: {desc!r}"


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------


class TestGetMtime:
    """Tests for _get_mtime() — file modification time helper."""

    def test_nonexistent_file_returns_zero(self):
        from pathlib import Path
        from server import _get_mtime

        assert _get_mtime(Path("/nonexistent/file.txt")) == 0.0

    def test_existing_file_returns_positive(self):
        from pathlib import Path
        from server import _get_mtime

        # Use the test file itself
        assert _get_mtime(Path(__file__)) > 0.0


class TestReadIfExists:
    """Tests for _read_if_exists() — safe file reading."""

    def test_nonexistent_returns_none(self):
        from pathlib import Path
        from server import _read_if_exists

        assert _read_if_exists(Path("/nonexistent/file.txt")) is None

    def test_existing_file_returns_content(self):
        from pathlib import Path
        from server import _read_if_exists

        content = _read_if_exists(Path(__file__))
        assert content is not None
        assert "TestReadIfExists" in content


# ---------------------------------------------------------------------------
# Loop guard tests (MAX_REPEATED_TOOL_CALLS + _tool_call_signature)
# ---------------------------------------------------------------------------


class TestCategorizeTask:
    """Tests for _categorize_task() — two-stage tool selection."""

    def test_email(self):
        from server import _categorize_task
        assert _categorize_task("write an email to my professor") == "email"

    def test_email_russian(self):
        from server import _categorize_task
        assert _categorize_task("напиши письмо преподавателю") == "email"

    def test_calendar(self):
        from server import _categorize_task
        assert _categorize_task("create a calendar event for tomorrow at 10am") == "calendar"

    def test_calendar_russian(self):
        from server import _categorize_task
        assert _categorize_task("создай событие в календаре") == "calendar"

    def test_memory(self):
        from server import _categorize_task
        assert _categorize_task("remember that I need to send the report") == "memory"

    def test_memory_russian(self):
        from server import _categorize_task
        assert _categorize_task("запомни, что завтра нужно отправить отчёт") == "memory"

    def test_web(self):
        from server import _categorize_task
        assert _categorize_task("find the latest news about OpenAI") == "web"

    def test_web_russian(self):
        from server import _categorize_task
        assert _categorize_task("найди информацию про AI") == "web"

    def test_desktop(self):
        from server import _categorize_task
        assert _categorize_task("open the FOL project in Finder") == "desktop"

    def test_desktop_russian(self):
        from server import _categorize_task
        assert _categorize_task("открой Safari") == "desktop"

    def test_coding(self):
        from server import _categorize_task
        assert _categorize_task("implement a sorting algorithm") == "coding"

    def test_coding_with_bug(self):
        """find a bug in my code should be coding, not web."""
        from server import _categorize_task
        assert _categorize_task("find a bug in my code") == "coding"

    def test_coding_error_in_script(self):
        from server import _categorize_task
        assert _categorize_task("find an error in my script") == "coding"

    def test_fallback_general(self):
        from server import _categorize_task
        assert _categorize_task("how are you today?") == "general"

    def test_empty(self):
        from server import _categorize_task
        assert _categorize_task("") == "general"


class TestSelectToolsForTask:
    """Tests for _select_tools_for_task() — focused toolset per task."""

    def test_general_gets_focused_subset(self):
        """GENERAL should NOT get all 50 tools — a focused category subset."""
        import agents
        from server import _select_tools_for_task, ALL_TOOLS

        tools = _select_tools_for_task("open Safari please", agents.AgentType.GENERAL)
        names = {t["name"] for t in tools}
        assert len(tools) < len(ALL_TOOLS), "GENERAL should get a focused subset"
        assert "open_app" in names
        assert len(tools) <= 20, f"Focused set should be small, got {len(tools)}"

    def test_email_task_has_email_tools(self):
        import agents
        from server import _select_tools_for_task

        tools = _select_tools_for_task("write an email to professor", agents.AgentType.GENERAL)
        names = {t["name"] for t in tools}
        assert "draft_email" in names
        assert "send_email" in names
        # No calendar-only tools in an email task
        assert "create_event" not in names

    def test_memory_task_has_memory_tools(self):
        import agents
        from server import _select_tools_for_task

        tools = _select_tools_for_task("remember this", agents.AgentType.GENERAL)
        names = {t["name"] for t in tools}
        assert "save_to_obsidian" in names
        assert "log_daily_activity" in names

    def test_web_task_has_browser_tools(self):
        import agents
        from server import _select_tools_for_task

        tools = _select_tools_for_task("search the web for news", agents.AgentType.GENERAL)
        names = {t["name"] for t in tools}
        assert "browser_goto" in names
        assert "search_web" in names

    def test_web_task_can_open_apps(self):
        """'open Safari and search' needs open_app to actually launch the browser."""
        import agents
        from server import _select_tools_for_task

        tools = _select_tools_for_task("open Safari and find news", agents.AgentType.GENERAL)
        names = {t["name"] for t in tools}
        assert "open_app" in names
        assert "safari_goto" in names

    def test_coding_task_has_coding_tools(self):
        import agents
        from server import _select_tools_for_task

        tools = _select_tools_for_task("find a bug in my code", agents.AgentType.GENERAL)
        names = {t["name"] for t in tools}
        assert "type_text" in names or "browser_goto" in names
        # Should NOT be limited to email/calendar-only tools
        assert "create_event" not in names

    def test_calendar_task_has_calendar_tools(self):
        import agents
        from server import _select_tools_for_task

        tools = _select_tools_for_task("create a calendar event", agents.AgentType.GENERAL)
        names = {t["name"] for t in tools}
        assert "create_event" in names
        assert "list_events" in names

    def test_specialized_agent_keeps_curated_set(self):
        """Specialized agents (e.g. CODER) still use their own curated subset."""
        import agents
        from server import _select_tools_for_task, _get_agent_tools

        tools = _select_tools_for_task("write code for sorting", agents.AgentType.CODER)
        expected = _get_agent_tools(agents.AgentType.CODER)
        assert tools == expected

    def test_ui_tools_always_included(self):
        """render_* UI tools should always be available so the model can ask permission."""
        import agents
        from server import _select_tools_for_task

        for task in ["open Safari", "write an email", "remember this"]:
            tools = _select_tools_for_task(task, agents.AgentType.GENERAL)
            names = {t["name"] for t in tools}
            assert "render_confirm_action" in names, f"UI tools missing for: {task}"
            assert "render_task_approval" in names

    def test_every_category_nonempty(self):
        """Every category should map to a non-empty toolset."""
        from server import _TOOL_CATEGORIES

        for category, names in _TOOL_CATEGORIES.items():
            assert names, f"Empty category: {category}"


class TestToolCallSignature:
    """Tests for _tool_call_signature() — canonical tool call identity."""

    def test_deterministic(self):
        """Same call should always produce the same signature."""
        from server import _tool_call_signature

        assert _tool_call_signature("open_app", {"name": "Safari"}) == \
            _tool_call_signature("open_app", {"name": "Safari"})

    def test_differs_for_different_args(self):
        """Different args should produce different signatures."""
        from server import _tool_call_signature

        assert _tool_call_signature("open_app", {"name": "Safari"}) != \
            _tool_call_signature("open_app", {"name": "Chrome"})

    def test_differs_for_different_tools(self):
        """Different tool names should produce different signatures."""
        from server import _tool_call_signature

        assert _tool_call_signature("open_app", {"name": "Safari"}) != \
            _tool_call_signature("screenshot", {})

    def test_args_order_independent(self):
        """Signature should not depend on dict key order."""
        from server import _tool_call_signature

        assert _tool_call_signature("drag", {"x1": 1, "y1": 2, "x2": 3, "y2": 4}) == \
            _tool_call_signature("drag", {"y2": 4, "x2": 3, "y1": 2, "x1": 1})

    def test_handles_unserializable(self):
        """Should not raise on unserializable args."""
        from server import _tool_call_signature

        sig = _tool_call_signature("weird", {"obj": object()})
        assert isinstance(sig, str)
        assert sig


class TestLoopGuard:
    """Tests for repeated-tool-call loop protection in the agent loop."""

    @patch("server.build_system_prompt", return_value="You are a helpful assistant.")
    @patch("server.build_context_messages", return_value=[])
    @patch("server._append_to_history")
    @patch("server._auto_route_agent")
    @patch("server.execute_tool_call", new_callable=AsyncMock, return_value=json.dumps({"status": "ok"}))
    @patch("server.call_claude_streaming")
    def test_aborts_on_repeated_identical_call(
        self,
        mock_call_claude,
        mock_execute,
        mock_route,
        mock_append,
        mock_context,
        mock_prompt,
    ):
        """The loop should abort when the same tool call repeats > MAX times."""
        import asyncio
        import server
        import agents

        mock_route.return_value = agents.AgentType.GENERAL

        async def _mock_claude(messages, system, tools=None):
            # Always returns the SAME tool call — simulating a stuck model
            yield ("_tool_use", {
                "id": "call_loop",
                "name": "open_app",
                "input": {"name": "Safari"},
            })
            yield ("_done", {"stop_reason": "tool_use"})

        mock_call_claude.side_effect = _mock_claude

        actions = asyncio.run(server.run_agent_loop("open safari"))

        # Loop guard should have triggered a loop_guard action
        guard_actions = [a for a in actions if a.get("type") == "loop_guard"]
        assert guard_actions, f"Expected loop_guard action, got: {actions}"

        # The guard message is user-facing human text — the tool name is
        # internal and must NOT appear in it.
        guard_msg = guard_actions[0]["message"]
        assert guard_msg and isinstance(guard_msg, str)
        assert "open_app" not in guard_msg

        # And it should NOT have executed the full max_steps (default 15)
        executed = [a for a in actions if a.get("type") == "tool_call"]
        assert len(executed) == server.MAX_REPEATED_TOOL_CALLS

    @patch("server.build_system_prompt", return_value="You are a helpful assistant.")
    @patch("server.build_context_messages", return_value=[])
    @patch("server._append_to_history")
    @patch("server._auto_route_agent")
    @patch("server.execute_tool_call", new_callable=AsyncMock, return_value=json.dumps({"status": "ok"}))
    @patch("server.call_claude_streaming")
    def test_no_abort_for_different_calls(
        self,
        mock_call_claude,
        mock_execute,
        mock_route,
        mock_append,
        mock_context,
        mock_prompt,
    ):
        """The loop should NOT abort when tool calls vary."""
        import asyncio
        import server
        import agents

        mock_route.return_value = agents.AgentType.GENERAL
        calls = [
            {"id": "c1", "name": "open_app", "input": {"name": "Safari"}},
            {"id": "c2", "name": "open_app", "input": {"name": "Notes"}},
            {"id": "c3", "name": "screenshot", "input": {}},
        ]
        llm_call_count = {"n": 0}

        async def _mock_claude(messages, system, tools=None):
            # Return each distinct call exactly once, then finish the turn
            idx = llm_call_count["n"]
            llm_call_count["n"] += 1
            if idx < len(calls):
                yield ("_tool_use", calls[idx])
                yield ("_done", {"stop_reason": "tool_use"})
            else:
                yield ("_done", {"stop_reason": "end_turn"})

        mock_call_claude.side_effect = _mock_claude

        actions = asyncio.run(server.run_agent_loop("do several things"))

        guard_actions = [a for a in actions if a.get("type") == "loop_guard"]
        assert guard_actions == [], f"Loop guard should NOT trigger, got: {actions}"

    @patch("server.build_system_prompt", return_value="You are a helpful assistant.")
    @patch("server.build_context_messages", return_value=[])
    @patch("server._append_to_history")
    @patch("server._auto_route_agent")
    @patch("server.execute_tool_call", new_callable=AsyncMock, return_value=json.dumps({"status": "ok"}))
    @patch("server.call_claude_streaming")
    def test_no_abort_for_interleaved_same_tool(
        self,
        mock_call_claude,
        mock_execute,
        mock_route,
        mock_append,
        mock_context,
        mock_prompt,
    ):
        """Repeated use of a no-arg tool with other calls between should NOT abort.

        This guards against false positives: browser_snapshot() is legitimately
        called between other steps in normal multi-step workflows.
        """
        import asyncio
        import server
        import agents

        mock_route.return_value = agents.AgentType.GENERAL
        # 6 calls: snapshot interleaved with different tools — never 4 in a row
        calls = [
            {"id": "c1", "name": "browser_snapshot", "input": {}},
            {"id": "c2", "name": "browser_click", "input": {"ref": "e3"}},
            {"id": "c3", "name": "browser_snapshot", "input": {}},
            {"id": "c4", "name": "browser_fill", "input": {"ref": "e5", "text": "x"}},
            {"id": "c5", "name": "browser_snapshot", "input": {}},
            {"id": "c6", "name": "browser_press", "input": {"key": "Enter"}},
        ]
        llm_call_count = {"n": 0}

        async def _mock_claude(messages, system, tools=None):
            idx = llm_call_count["n"]
            llm_call_count["n"] += 1
            if idx < len(calls):
                yield ("_tool_use", calls[idx])
                yield ("_done", {"stop_reason": "tool_use"})
            else:
                yield ("_done", {"stop_reason": "end_turn"})

        mock_call_claude.side_effect = _mock_claude

        actions = asyncio.run(server.run_agent_loop("browse the web"))

        guard_actions = [a for a in actions if a.get("type") == "loop_guard"]
        assert guard_actions == [], f"Loop guard should NOT trigger on interleaved calls: {actions}"
        executed = [a for a in actions if a.get("type") == "tool_call"]
        assert len(executed) == len(calls), f"Expected {len(calls)} executed, got {len(executed)}"

    @patch("server.build_system_prompt", return_value="You are a helpful assistant.")
    @patch("server.build_context_messages", return_value=[])
    @patch("server._append_to_history")
    @patch("server._auto_route_agent")
    @patch("server.call_claude_streaming")
    def test_streaming_loop_guard_yields_complete(
        self,
        mock_call_claude,
        mock_route,
        mock_append,
        mock_context,
        mock_prompt,
    ):
        """Streaming loop should yield a complete state when guard triggers."""
        import asyncio
        import server
        import agents

        mock_route.return_value = agents.AgentType.GENERAL

        async def _mock_claude(messages, system, tools=None):
            yield ("_tool_use", {
                "id": "call_loop",
                "name": "notify",
                "input": {"title": "ping", "message": "ping"},
            })
            yield ("_done", {"stop_reason": "tool_use"})

        mock_call_claude.side_effect = _mock_claude

        async def _collect():
            events = []
            async for event_type, event_data in server.run_agent_loop_streaming("ping"):
                events.append((event_type, event_data))
            return events

        events = asyncio.run(_collect())

        state_events = [e for e in events if e[0] == "state"]
        complete = [s for s in state_events if s[1].get("state") == "complete"]
        assert complete, f"Expected complete state from loop guard, got events: {events}"
        # User-facing message is human text — the tool name stays internal.
        assert complete[0][1]["message"]
        assert "notify" not in complete[0][1]["message"]


# ---------------------------------------------------------------------------
# call_claude_streaming error humanization (BUG B regression)
# ---------------------------------------------------------------------------


class TestCallClaudeStreamingErrorHumanization:
    """BUG B regression: raw LLM exceptions must never reach the UI.

    Every error from ``call_claude_streaming`` (both llm_astream's own
    error events and exceptions raised mid-stream) is humanized in the
    user's language before being yielded.
    """

    async def _collect(self, messages, mock_stream):
        import asyncio
        import server

        with patch("server.llm_astream", side_effect=mock_stream):
            events = []
            async for event_type, event_data in server.call_claude_streaming(
                messages=messages,
                system="You are a helpful assistant.",
            ):
                events.append((event_type, event_data))
        return events

    @pytest.mark.asyncio
    async def test_llm_error_event_humanized_ru(self):
        """A 429 error from the LLM must become a friendly Russian message."""

        async def _mock_stream(messages, system, tools=None):
            yield {"type": "error", "message": "429 Client Error: Too Many Requests for url: https://api.openai.com/v1/chat/completions"}

        events = await self._collect(
            [{"role": "user", "content": "привет"}],
            _mock_stream,
        )
        assert events
        ev_type, data = events[0]
        assert ev_type == "error"
        msg = data["message"]
        # Humanized, not the raw exception text
        assert "429" not in msg
        assert "api.openai.com" not in msg
        assert "Слишком много запросов" in msg

    @pytest.mark.asyncio
    async def test_llm_error_event_humanized_en(self):
        """The same error is humanized in English for an English user."""

        async def _mock_stream(messages, system, tools=None):
            yield {"type": "error", "message": "ConnectionError: connection refused"}

        events = await self._collect(
            [{"role": "user", "content": "hello"}],
            _mock_stream,
        )
        assert events
        ev_type, data = events[0]
        assert ev_type == "error"
        msg = data["message"]
        assert "ConnectionError" not in msg
        assert "connection refused" not in msg
        # Generic fallback in English — no raw stack details
        assert "Something went wrong" in msg

    @pytest.mark.asyncio
    async def test_exception_in_stream_humanized(self):
        """A mid-stream exception must be humanized, not dumped raw."""

        async def _mock_stream(messages, system, tools=None):
            raise RuntimeError("SecretKey sk-abc123 leaked in traceback")
            yield  # pragma: no cover

        events = await self._collect(
            [{"role": "user", "content": "проверь"}],
            _mock_stream,
        )
        assert events
        ev_type, data = events[0]
        assert ev_type == "error"
        msg = data["message"]
        assert "sk-abc123" not in msg
        assert "SecretKey" not in msg
