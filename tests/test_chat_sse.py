"""Integration tests for orchestrator/server.py HTTP endpoints.

Tests the POST /chat SSE streaming endpoint, GET /status, GET /health,
POST /reset, GET /agent, and POST /agent/switch endpoints.
Fixtures are in tests/conftest.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

# Make reset_globals run before every test in this file
pytestmark = pytest.mark.usefixtures("reset_globals")

# Shared helpers from helpers.py
from helpers import (
    _mock_chat_setup,
    _mock_command_setup,
    _parse_sse_events,
)


# ===========================================================================
# GET /health
# ===========================================================================

class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_ok(self, mock_agent_server, mock_obsidian, client):
        """Health endpoint should return status ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["agent_server"] == {"status": "ok"}
        assert data["obsidian_connected"] is False

    def test_health_reports_agent_server_status(self, mock_agent_server, mock_obsidian, client):
        """Health should reflect agent server status."""
        mock_agent_server.return_value = {"status": "error"}
        mock_obsidian.return_value = True
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_server"]["status"] == "error"

    def test_health_agent_server_error(self, mock_agent_server, mock_obsidian, client):
        """Health should handle agent server errors gracefully."""
        mock_agent_server.side_effect = Exception("Connection refused")
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in str(data["agent_server"])


# ===========================================================================
# GET /status
# ===========================================================================

class TestStatusEndpoint:
    """Tests for GET /status."""

    def test_status_idle(self, mock_fol_health, client):
        """Status should report idle state by default."""
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "idle"
        assert data["current_agent"] == "General"
        assert len(data["available_agents"]) == 6
        assert data["queued_messages"] == 0

    def test_status_after_chat_complete(self, mock_fol_health, client):
        """Status should reflect state after processing."""
        import server as srv
        srv.current_job["id"] = "test-id"
        srv.current_job["state"] = "complete"
        srv.current_job["task"] = "test task"
        srv.current_job["actions"] = [{"step": 1}]
        srv.current_job["started_at"] = 1000.0

        resp = client.get("/status")
        data = resp.json()
        assert data["state"] == "complete"
        assert data["task"] == "test task"
        assert data["actions_count"] == 1
        assert data["id"] == "test-id"

    def test_status_with_agent_routed(self, mock_fol_health, client):
        """Status should show the current agent type."""
        import server as srv
        from agents import AgentType
        srv._current_agent_type = AgentType.CODER

        resp = client.get("/status")
        data = resp.json()
        assert data["current_agent"] == "Coder"

    def test_status_fol_unreachable(self, mock_fol_health, client):
        """Status should still work when FOL server is down."""
        mock_fol_health.return_value = {"status": "unreachable"}
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fol_status"]["status"] == "unreachable"


# ===========================================================================
# POST /chat — validation
# ===========================================================================

class TestChatValidation:
    """Tests for POST /chat input validation."""

    def test_chat_empty_message(self, client):
        """Empty message should return 400."""
        resp = client.post("/chat", json={"message": ""})
        assert resp.status_code == 400
        assert resp.json()["error"] == "missing 'message' field"

    def test_chat_missing_message(self, client):
        """Missing message field should return 400."""
        resp = client.post("/chat", json={})
        assert resp.status_code == 400
        assert resp.json()["error"] == "missing 'message' field"

    def test_chat_invalid_json(self, client):
        """Invalid JSON body should return 400 (endpoint uses raw request.json())."""
        resp = client.post("/chat", content=b"not json", headers={"Content-Type": "application/json"})
        assert resp.status_code == 400

    def test_chat_returns_200_with_valid_message(self, client):
        """Valid message should return 200 with streaming response."""
        stack, mock_loop, _, _ = _mock_chat_setup()
        with stack:
            async def _mock_stream(task, max_steps=15, source="user"):
                yield ("state", {"state": "thinking"})
                yield ("token", {"text": "Hello!"})
                yield ("state", {"state": "complete", "message": "Done."})
            mock_loop.side_effect = _mock_stream

            resp = client.post("/chat", json={"message": "hello"})
            assert resp.status_code == 200
            assert resp.headers.get("content-type", "").startswith("text/event-stream")


# ===========================================================================
# POST /chat — SSE stream parsing
# ===========================================================================

class TestChatSSEStream:
    """Tests for POST /chat SSE event stream content."""

    @pytest.mark.asyncio
    async def test_sse_contains_token_events(self, async_client):
        """SSE stream should contain token events."""
        stack, mock_loop, _, _ = _mock_chat_setup()
        with stack:
            async def _mock_stream(task, max_steps=15, source="user"):
                yield ("state", {"state": "thinking"})
                yield ("token", {"text": "Hello "})
                yield ("token", {"text": "world!"})
                yield ("state", {"state": "complete", "message": "Done."})
            mock_loop.side_effect = _mock_stream

            async with async_client.stream("POST", "/chat", json={"message": "hello"}) as resp:
                assert resp.status_code == 200
                assert resp.headers.get("content-type", "").startswith("text/event-stream")
                lines = [line async for line in resp.aiter_lines()]

        events = _parse_sse_events(lines)
        assert len(events) >= 4

        # First event should be state: thinking
        assert events[0]["event"] == "state"
        assert events[0]["data"]["state"] == "thinking"

        # Token events should be present
        token_events = [e for e in events if e["event"] == "token"]
        assert len(token_events) >= 2
        assert token_events[0]["data"]["text"] == "Hello "
        assert token_events[1]["data"]["text"] == "world!"

    @pytest.mark.asyncio
    async def test_sse_contains_component_events(self, async_client):
        """SSE stream should contain component events for render tools."""
        stack, mock_loop, _, _ = _mock_chat_setup()
        with stack:
            async def _mock_stream(task, max_steps=15, source="user"):
                yield ("state", {"state": "thinking"})
                yield ("token", {"text": "Here is my plan:"})
                yield ("component", {
                    "a2ui": {
                        "version": "0.8",
                        "components": [{
                            "id": "comp-test",
                            "type": "TaskApproval",
                            "properties": {
                                "title": "My Plan",
                                "steps": [{"id": 1, "text": "Step 1"}],
                            },
                        }],
                    }
                })
                yield ("state", {"state": "complete", "message": "Done."})
            mock_loop.side_effect = _mock_stream

            async with async_client.stream("POST", "/chat", json={"message": "plan"}) as resp:
                assert resp.status_code == 200
                lines = [line async for line in resp.aiter_lines()]

        events = _parse_sse_events(lines)

        # Verify token events are NOT suppressed (the has_render_tool fix)
        token_events = [e for e in events if e["event"] == "token"]
        assert len(token_events) >= 1
        assert token_events[0]["data"]["text"] == "Here is my plan:"

        # Verify component events are present
        comp_events = [e for e in events if e["event"] == "component"]
        assert len(comp_events) >= 1
        assert comp_events[0]["data"]["a2ui"]["components"][0]["type"] == "TaskApproval"

    @pytest.mark.asyncio
    async def test_sse_ends_with_complete(self, async_client):
        """SSE stream should end with a complete state event."""
        stack, mock_loop, _, _ = _mock_chat_setup()
        with stack:
            async def _mock_stream(task, max_steps=15, source="user"):
                yield ("state", {"state": "thinking"})
                yield ("token", {"text": "Done."})
                yield ("state", {"state": "complete", "message": "Task finished."})
            mock_loop.side_effect = _mock_stream

            async with async_client.stream("POST", "/chat", json={"message": "test"}) as resp:
                assert resp.status_code == 200
                lines = [line async for line in resp.aiter_lines()]

        events = _parse_sse_events(lines)
        last_event = events[-1]
        assert last_event["event"] == "state"
        assert last_event["data"]["state"] == "complete"

    @pytest.mark.asyncio
    async def test_sse_filters_internal_tool_events(self, async_client):
        """tool_call/tool_result are internal — never streamed to the user."""
        stack, mock_loop, _, _ = _mock_chat_setup()
        with stack:
            async def _mock_stream(task, max_steps=15, source="user"):
                yield ("state", {"state": "thinking"})
                yield ("token", {"text": '{"type":"function","name":"browser_goto",'
                                        '"parameters":{"url":"https://example.com"}}'})
                yield ("tool_call", {"tool": "browser_goto", "args": {"url": "https://example.com"}, "step": 1})
                yield ("tool_result", {"tool": "browser_goto", "result": {"status": "ok"}, "step": 1})
                yield ("token", {"text": "Done."})
                yield ("state", {"state": "complete", "message": "Done."})
            mock_loop.side_effect = _mock_stream

            async with async_client.stream("POST", "/chat", json={"message": "search"}) as resp:
                assert resp.status_code == 200
                lines = [line async for line in resp.aiter_lines()]

        events = _parse_sse_events(lines)

        tool_call_events = [e for e in events if e["event"] == "tool_call"]
        tool_result_events = [e for e in events if e["event"] == "tool_result"]

        # Internal events never reach the user.
        assert tool_call_events == []
        assert tool_result_events == []

        # JSON function calls never appear in the streamed text.
        token_text = "".join(
            e["data"].get("text", "") for e in events if e["event"] == "token"
        )
        assert "function" not in token_text
        assert "browser_goto" not in token_text
        assert "example.com" not in token_text

        # Final message is still delivered as a plain string.
        assert any(
            e["event"] == "state" and e["data"]["state"] == "complete"
            for e in events
        )

    @pytest.mark.asyncio
    async def test_sse_streaming_returns_full_text(self, async_client):
        """The SSE stream should contain full text response, not partial code."""
        stack, mock_loop, _, _ = _mock_chat_setup()
        with stack:
            full_response = (
                "I've analyzed your request and here's what I found. "
                "The best approach is to use a recursive algorithm "
                "that processes each element in O(n log n) time. "
                "Let me implement this for you."
            )

            async def _mock_stream(task, max_steps=15, source="user"):
                yield ("state", {"state": "thinking"})
                for word in full_response.split():
                    yield ("token", {"text": word + " "})
                yield ("state", {"state": "complete", "message": full_response})
            mock_loop.side_effect = _mock_stream

            async with async_client.stream("POST", "/chat", json={"message": "implement algorithm"}) as resp:
                assert resp.status_code == 200
                lines = [line async for line in resp.aiter_lines()]

        events = _parse_sse_events(lines)
        token_events = [e for e in events if e["event"] == "token"]

        reconstructed = "".join(t["data"]["text"] for t in token_events)
        assert "I've analyzed your request" in reconstructed
        assert "recursive algorithm" in reconstructed
        assert "O(n log n)" in reconstructed
        assert len(reconstructed) > 100, "Full response should be substantial"


# ===========================================================================
# POST /chat — busy/queued handling
# ===========================================================================

class TestChatQueue:
    """Tests for POST /chat when server is busy."""

    def test_chat_queued_when_busy(self, client):
        """Chat should return 202 when server is busy."""
        import server as srv
        srv.current_job["state"] = "working"

        resp = client.post("/chat", json={"message": "hello"})
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["position"] == 1
        assert srv.current_job["message_queue"] == ["hello"]

    def test_chat_queues_multiple_messages(self, client):
        """Multiple messages while busy should be queued in order."""
        import server as srv
        srv.current_job["state"] = "working"

        client.post("/chat", json={"message": "first"})
        client.post("/chat", json={"message": "second"})
        resp = client.post("/chat", json={"message": "third"})

        assert resp.status_code == 202
        data = resp.json()
        assert data["position"] == 3
        assert len(srv.current_job["message_queue"]) == 3
        assert srv.current_job["message_queue"] == ["first", "second", "third"]

    def test_chat_not_queued_when_idle(self, client):
        """Chat should NOT queue when idle (returns 200)."""
        import server as srv
        assert srv.current_job["state"] == "idle"

        stack, mock_loop, _, _ = _mock_chat_setup()
        with stack:
            mock_loop.return_value.__aiter__.return_value = iter([
                ("state", {"state": "thinking"}),
                ("state", {"state": "complete", "message": "Done."}),
            ])

            resp = client.post("/chat", json={"message": "hello"})
            assert resp.status_code == 200


# ===========================================================================
# POST /reset
# ===========================================================================

class TestResetEndpoint:
    """Tests for POST /reset."""

    def test_reset_idle_state(self, client):
        """Reset when idle should stay idle."""
        resp = client.post("/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["state"] == "idle"

    def test_reset_clears_conversation(self, client):
        """Reset should clear conversation history."""
        import server as srv
        srv._conversation_history.append({"role": "user", "content": "hello"})
        srv._conversation_history.append({"role": "assistant", "content": "hi"})
        srv._current_agent_type = "test_agent"
        srv.current_job["state"] = "working"
        srv.current_job["task"] = "test task"
        srv.current_job["actions"] = [{"step": 1}]

        resp = client.post("/reset")
        assert resp.status_code == 200

        assert len(srv._conversation_history) == 0
        assert srv.current_job["state"] == "idle"
        assert srv.current_job["task"] is None
        assert len(srv.current_job["actions"]) == 0


# ===========================================================================
# GET /agent and POST /agent/switch
# ===========================================================================

class TestAgentEndpoint:
    """Tests for GET /agent and POST /agent/switch."""

    def test_get_agent_default(self, client):
        """Default agent should be General."""
        resp = client.get("/agent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "general"
        assert data["name"] == "General"

    def test_get_agent_available_list(self, client):
        """Available agents should include all types."""
        resp = client.get("/agent")
        data = resp.json()
        expected = {"architect", "coder", "reviewer", "researcher", "memory", "general"}
        assert set(data["available"]) == expected

    def test_switch_agent_valid(self, client):
        """Switch to a valid agent should succeed."""
        resp = client.post("/agent/switch", json={"agent": "coder"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["previous"] == "general"
        assert data["current"] == "coder"
        assert data["name"] == "Coder"

    def test_switch_agent_invalid(self, client):
        """Switch to an invalid agent should return 400."""
        resp = client.post("/agent/switch", json={"agent": "nonexistent"})
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data

    def test_switch_agent_then_get(self, client):
        """After switching, GET /agent should reflect the change."""
        client.post("/agent/switch", json={"agent": "reviewer"})
        resp = client.get("/agent")
        data = resp.json()
        assert data["current"] == "reviewer"
        assert data["name"] == "Reviewer"

    def test_switch_agent_russian_name(self, client):
        """Switch agent with Russian name should still work (lowered)."""
        resp = client.post("/agent/switch", json={"agent": "ARCHITECT"})
        assert resp.status_code == 200
        assert resp.json()["current"] == "architect"


# ===========================================================================
# Input normalization
# ===========================================================================

class TestChatInputNormalization:
    """Tests that chat input is normalized before processing."""

    def test_chat_normalizes_input(self, client):
        """Chat input should be normalized via normalize_user_input."""
        stack, mock_loop, _, _ = _mock_chat_setup()
        with patch("server.normalize_user_input") as mock_normalize:
            mock_normalize.return_value = "спасибо помоги"
            with stack:
                async def _mock_stream(task, max_steps=15, source="user"):
                    yield ("state", {"state": "thinking"})
                    yield ("token", {"text": "ok"})
                    yield ("state", {"state": "complete", "message": "ok"})
                mock_loop.side_effect = _mock_stream

                resp = client.post("/chat", json={"message": "spasiba pomogi"})
                assert resp.status_code == 200


# ===========================================================================
# POST /command
# ===========================================================================

class TestCommandEndpoint:
    """Tests for POST /command."""

    def test_command_returns_actions(self, client):
        """POST /command should return actions array."""
        stack, mock_loop, _, _ = _mock_command_setup()
        with stack:
            mock_loop.return_value = [{"step": 1, "type": "complete", "message": "Done."}]

            resp = client.post("/command", json={"task": "test"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["task"] == "test"
            assert len(data["actions"]) == 1

    def test_command_empty_task(self, client):
        """POST /command without task should return 400."""
        resp = client.post("/command", json={"task": ""})
        assert resp.status_code == 400
