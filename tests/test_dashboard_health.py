"""Phase 7 — runtime reliability tests.

Covers:
  - Deterministic health checks (dashboard/collector.check_service_health)
  - Automatic degraded-state detection (compute_system_state)
  - LLM / Ollama / memory status collection (no live services required — mocks)
  - Orchestrator /api/runtime endpoint shape (via TestClient, with mocks)

These tests never start real services — every external call is mocked,
so they run in CI on any machine.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

# Make dashboard/ importable (tests/ is on sys.path via conftest).
from dashboard import collector


# ---------------------------------------------------------------------------
# check_service_health — deterministic health checks
# ---------------------------------------------------------------------------


class TestCheckServiceHealth:
    def test_unknown_service_is_down(self):
        result = collector.check_service_health("nonexistent")
        assert result["status"] == "down"

    def test_port_down_is_down(self):
        with patch("dashboard.collector.check_port", return_value=False):
            result = collector.check_service_health("orchestrator")
        assert result["status"] == "down"
        assert result["detail"] == "port not listening"

    def test_no_health_path_uses_port_only(self):
        """nextjs has no /health — a listening port means OK."""
        with patch("dashboard.collector.check_port", return_value=True):
            result = collector.check_service_health("nextjs")
        assert result["status"] == "ok"

    def test_health_200_is_ok(self):
        with patch("dashboard.collector.check_port", return_value=True), \
             patch("dashboard.collector.http_get_json", return_value=(200, {"status": "ok"}, "")):
            result = collector.check_service_health("agent_server")
        assert result["status"] == "ok"
        assert result["http"] == 200

    def test_health_500_is_degraded(self):
        with patch("dashboard.collector.check_port", return_value=True), \
             patch("dashboard.collector.http_get_json", return_value=(500, None, "server error")):
            result = collector.check_service_health("agent_server")
        assert result["status"] == "degraded"

    def test_orchestrator_degraded_when_agent_down(self):
        """Orchestrator /health reports ok, but its agent-server is unhealthy
        → orchestrator must be DEGRADED, never fake-ok."""
        orch_health = {
            "status": "ok",
            "agent_server": {"status": "error", "error": "connection refused"},
        }
        with patch("dashboard.collector.check_port", return_value=True), \
             patch("dashboard.collector.http_get_json", return_value=(200, orch_health, "")):
            result = collector.check_service_health("orchestrator")
        assert result["status"] == "degraded"

    def test_orchestrator_ok_when_agent_ok(self):
        orch_health = {
            "status": "ok",
            "agent_server": {"status": "ok"},
        }
        with patch("dashboard.collector.check_port", return_value=True), \
             patch("dashboard.collector.http_get_json", return_value=(200, orch_health, "")):
            result = collector.check_service_health("orchestrator")
        assert result["status"] == "ok"

    def test_fol_starting_is_degraded(self):
        with patch("dashboard.collector.check_port", return_value=True), \
             patch("dashboard.collector.http_get_json", return_value=(200, {"status": "starting"}, "")):
            result = collector.check_service_health("fol")
        assert result["status"] == "degraded"

    def test_fol_healthy_is_ok(self):
        with patch("dashboard.collector.check_port", return_value=True), \
             patch("dashboard.collector.http_get_json", return_value=(200, {"status": "healthy"}, "")):
            result = collector.check_service_health("fol")
        assert result["status"] == "ok"

    def test_result_contains_port_and_critical(self):
        with patch("dashboard.collector.check_port", return_value=True), \
             patch("dashboard.collector.http_get_json", return_value=(200, {"status": "ok"}, "")):
            result = collector.check_service_health("orchestrator")
        assert result["port"] == 8420
        assert result["critical"] is True


# ---------------------------------------------------------------------------
# compute_system_state — automatic degraded-state detection
# ---------------------------------------------------------------------------


class TestComputeSystemState:
    def _services(self, **overrides):
        base = {
            "orchestrator": {"status": "ok"},
            "agent_server": {"status": "ok"},
            "fol": {"status": "ok"},
            "bridge": {"status": "ok"},
            "dashboard": {"status": "ok"},
            "nextjs": {"status": "ok"},
            "fastapi": {"status": "ok"},
            "ollama": {"status": "ok"},
        }
        base.update(overrides)
        return base

    def test_all_ok(self):
        state = collector.compute_system_state(self._services())
        assert state["state"] == "ok"
        assert state["down_services"] == []
        assert state["degraded_services"] == []

    def test_non_critical_down_is_degraded(self):
        state = collector.compute_system_state(self._services(bridge={"status": "down"}))
        assert state["state"] == "degraded"
        assert state["down_services"] == ["bridge"]

    def test_any_degraded_is_degraded(self):
        state = collector.compute_system_state(self._services(ollama={"status": "degraded"}))
        assert state["state"] == "degraded"

    def test_critical_down_is_down(self):
        state = collector.compute_system_state(self._services(orchestrator={"status": "down"}))
        assert state["state"] == "down"
        assert "orchestrator" in state["critical_down"]

    def test_agent_down_is_down(self):
        state = collector.compute_system_state(self._services(agent_server={"status": "down"}))
        assert state["state"] == "down"

    def test_fol_down_is_down(self):
        state = collector.compute_system_state(self._services(fol={"status": "down"}))
        assert state["state"] == "down"


# ---------------------------------------------------------------------------
# LLM / Ollama / memory status
# ---------------------------------------------------------------------------


class TestLlmStatus:
    def test_orchestrator_down_returns_unknown(self):
        with patch("dashboard.collector.http_get_json", return_value=(0, None, "unreachable")):
            result = collector.get_llm_status()
        assert result["status"] == "unknown"

    def test_parses_model_chain(self):
        payload = {
            "llm": {
                "status": "ready",
                "model_chain": ["openrouter/model-a", "ollama/llama3.2:3b"],
                "providers": ["openrouter", "ollama"],
                "fallback_log": [],
                "last_fallback_error": "",
                "tavily_configured": True,
            }
        }
        with patch("dashboard.collector.http_get_json", return_value=(200, payload, "")):
            result = collector.get_llm_status()
        assert result["status"] == "ready"
        assert result["model_chain"][1] == "ollama/llama3.2:3b"
        assert result["tavily_configured"] is True


class TestOllamaStatus:
    def test_down_when_unreachable(self):
        with patch("dashboard.collector.http_get_json", return_value=(0, None, "refused")):
            result = collector.get_ollama_status()
        assert result["status"] == "down"

    def test_ok_with_models(self):
        payload = {"models": [{"name": "llama3.2:3b"}, {"name": "qwen"}]}
        with patch("dashboard.collector.http_get_json", return_value=(200, payload, "")):
            result = collector.get_ollama_status()
        assert result["status"] == "ok"
        assert result["count"] == 2

    def test_degraded_without_models(self):
        payload = {"models": []}
        with patch("dashboard.collector.http_get_json", return_value=(200, payload, "")):
            result = collector.get_ollama_status()
        assert result["status"] == "degraded"


class TestMemoryStatus:
    def test_returns_file_flags(self, tmp_path, monkeypatch):
        mem_dir = tmp_path / ".secondself"
        mem_dir.mkdir()
        (mem_dir / "identity.md").write_text("# Identity", encoding="utf-8")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        with patch("dashboard.collector.http_get_json", return_value=(200, {"memory": {"obsidian_connected": True}}, "")):
            result = collector.get_memory_status()
        assert result["files"]["identity"]["exists"] is True
        assert result["files"]["preferences"]["exists"] is False
        assert result["obsidian_connected"] is True

    def test_handles_orchestrator_down(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        with patch("dashboard.collector.http_get_json", return_value=(0, None, "unreachable")):
            result = collector.get_memory_status()
        assert result["obsidian_connected"] is None


# ---------------------------------------------------------------------------
# Orchestrator /api/runtime endpoint
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("reset_globals")
class TestOrchestratorRuntimeEndpoint:
    def test_runtime_returns_expected_shape(self, client, mock_fol_health):
        """GET /api/runtime must expose the Phase 7 fields (no live services)."""
        with patch("server.call_agent_server", return_value={"status": "ok"}), \
             patch("server.check_obsidian_connection", return_value=False), \
             patch("server.check_fol_health", return_value={"status": "healthy"}):
            resp = client.get("/api/runtime")
        assert resp.status_code == 200
        data = resp.json()
        assert "uptime_seconds" in data
        assert "llm" in data
        assert "model_chain" in data["llm"]
        assert "agent" in data
        assert "job" in data
        assert "services" in data
        assert "memory" in data
        assert "recent_tool_calls" in data
        assert "recent_errors" in data

    def test_runtime_records_tool_calls(self, client, mock_fol_health):
        """_record_tool_call entries surface in /api/runtime (reversed)."""
        import server
        server._record_tool_call("open_app", ok=True)
        server._record_tool_call("screenshot", ok=False)
        with patch("server.call_agent_server", return_value={"status": "ok"}), \
             patch("server.check_obsidian_connection", return_value=False), \
             patch("server.check_fol_health", return_value={"status": "healthy"}):
            data = client.get("/api/runtime").json()
        tools = data["recent_tool_calls"]
        assert tools[0]["tool"] == "screenshot"
        assert tools[0]["ok"] is False
        assert tools[1]["tool"] == "open_app"

    def test_runtime_records_errors(self, client, mock_fol_health):
        import server
        server._record_error("llm", "boom")
        with patch("server.call_agent_server", return_value={"status": "ok"}), \
             patch("server.check_obsidian_connection", return_value=False), \
             patch("server.check_fol_health", return_value={"status": "healthy"}):
            data = client.get("/api/runtime").json()
        assert data["recent_errors"][0]["source"] == "llm"
        assert data["recent_errors"][0]["message"] == "boom"

    def test_runtime_never_exposes_secrets(self, client, mock_fol_health):
        """The endpoint must not leak API keys in any field."""
        import server
        server._record_error("llm", "sk-or-v1-abcdefghijklmnopqrstuvwxyz123456")
        with patch("server.call_agent_server", return_value={"status": "ok"}), \
             patch("server.check_obsidian_connection", return_value=False), \
             patch("server.check_fol_health", return_value={"status": "healthy"}):
            raw = client.get("/api/runtime").content.decode()
        assert "sk-or-v1-abcdefghijklmnopqrstuvwxyz123456" not in raw
        assert "sk-" not in raw
