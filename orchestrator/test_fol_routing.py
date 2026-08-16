"""
Tests for the Orchestrator → FOL API routing layer.
Covers: call_fol_api, check_fol_health, FOL_TOOLS definition,
execute_tool_call with fol_command, and the /fol/status + /fol/command endpoints.
"""

import json
import urllib.error
import urllib.request
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport

from server import (
    app, current_job, job_lock, set_job_state,
    call_fol_api, check_fol_health, FOL_TOOLS,
    FOL_API_URL, execute_tool_call,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def reset_job_state():
    """Reset global state before each test."""
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []
    yield
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []


@pytest_asyncio.fixture
async def client():
    """Create an httpx async client wired to the FastAPI app."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


# ---------------------------------------------------------------------------
# Helper: mock urllib.request.urlopen
# ---------------------------------------------------------------------------

def _make_mock_response(data: dict, status: int = 200):
    """Create a mock urllib response object."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# FOL_TOOLS structure tests
# ---------------------------------------------------------------------------

class TestFOLToolsDefinition:
    """Verify FOL_TOOLS tool definitions are well-formed."""

    def test_fol_tools_is_list(self):
        assert isinstance(FOL_TOOLS, list)
        assert len(FOL_TOOLS) == 1

    def test_fol_tools_has_fol_command(self):
        tool_names = [t["name"] for t in FOL_TOOLS]
        assert "fol_command" in tool_names

    def test_fol_tool_structure(self):
        tool = FOL_TOOLS[0]
        assert tool["name"] == "fol_command"
        assert "description" in tool
        assert "input_schema" in tool
        assert "command" in tool["input_schema"]["properties"]
        assert tool["input_schema"]["required"] == ["command"]

    def test_fol_tool_in_all_tools(self):
        """FOL tools should be included in ALL_TOOLS."""
        from server import ALL_TOOLS
        tool_names = [t["name"] for t in ALL_TOOLS]
        assert "fol_command" in tool_names


# ---------------------------------------------------------------------------
# call_fol_api unit tests
# ---------------------------------------------------------------------------

class TestCallFolApi:
    """Unit tests for call_fol_api()."""

    @patch("server.urllib.request.urlopen")
    def test_post_success(self, mock_urlopen):
        """POST to FOL API should return parsed JSON response."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "response": "System status: all nominal, sir.",
            "tool": "fol",
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        result = call_fol_api("/api/chat", {"message": "status"})

        assert result["response"] == "System status: all nominal, sir."
        assert result["tool"] == "fol"
        # Verify the request was built correctly
        call_args = mock_urlopen.call_args[0][0]
        assert FOL_API_URL in call_args.full_url
        assert call_args.method == "POST"

    @patch("server.urllib.request.urlopen")
    def test_get_success(self, mock_urlopen):
        """GET to FOL API should work for health checks."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "healthy", "version": "2.0.0",
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        result = call_fol_api("/health", method="GET")

        assert result["status"] == "healthy"
        call_args = mock_urlopen.call_args[0][0]
        assert call_args.method == "GET"

    @patch("server.urllib.request.urlopen")
    def test_http_error_returns_error_dict(self, mock_urlopen):
        """HTTPError with unparseable body should return error dict."""
        url = f"{FOL_API_URL}/api/chat"
        # Non-JSON body forces the fallback error path
        error_fp = MagicMock()
        error_fp.read.return_value = b"Internal Server Error"
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url, 500, "Internal Server Error", {}, error_fp
        )

        result = call_fol_api("/api/chat", {"message": ""})

        assert "error" in result
        assert "500" in str(result["error"])

    @patch("server.urllib.request.urlopen")
    def test_http_error_with_body_parsing(self, mock_urlopen):
        """HTTPError with a parseable JSON body should return it."""
        error_body = json.dumps({"detail": "Invalid command"}).encode()
        error_fp = MagicMock()
        error_fp.read.return_value = error_body
        url = f"{FOL_API_URL}/api/chat"
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url, 422, "Unprocessable", {}, error_fp
        )

        result = call_fol_api("/api/chat", {"message": "bad"})

        assert result == {"detail": "Invalid command"}

    @patch("server.urllib.request.urlopen")
    def test_url_error_returns_unreachable(self, mock_urlopen):
        """URLError when FOL server is down should return error."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = call_fol_api("/api/chat", {"message": "test"})

        assert "error" in result
        assert "unreachable" in str(result["error"]).lower()

    @patch("server.urllib.request.urlopen")
    def test_generic_exception_returns_error(self, mock_urlopen):
        """Any other exception should be caught and returned as error."""
        mock_urlopen.side_effect = RuntimeError("Something went wrong")

        result = call_fol_api("/api/chat", {"message": "test"})

        assert "error" in result
        assert "Something went wrong" in str(result["error"])


# ---------------------------------------------------------------------------
# check_fol_health unit tests
# ---------------------------------------------------------------------------

class TestCheckFolHealth:
    """Unit tests for check_fol_health()."""

    @patch("server.urllib.request.urlopen")
    def test_healthy(self, mock_urlopen):
        """check_fol_health should return the health response when FOL is up."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "healthy", "version": "2.0.0",
        }).encode()
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        result = check_fol_health()

        assert result["status"] == "healthy"

    @patch("server.urllib.request.urlopen")
    def test_unreachable(self, mock_urlopen):
        """check_fol_health should return unreachable when FOL is down."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = check_fol_health()

        assert result["status"] == "unreachable"
        assert "error" in result

    @patch("server.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        """check_fol_health should handle timeouts gracefully."""
        mock_urlopen.side_effect = TimeoutError("timed out")

        result = check_fol_health()

        assert result["status"] == "unreachable"


# ---------------------------------------------------------------------------
# execute_tool_call("fol_command") tests
# ---------------------------------------------------------------------------

class TestExecuteFolCommand:
    """Tests for execute_tool_call with fol_command."""

    @pytest.mark.asyncio
    @patch("server.call_fol_api")
    async def test_successful_command(self, mock_call_fol_api):
        """fol_command should route to call_fol_api and return response."""
        mock_call_fol_api.return_value = {
            "response": "The current time is 19:46:56, sir.",
        }

        result = await execute_tool_call("fol_command", {"command": "time"})
        result_data = json.loads(result)

        assert result_data["status"] == "ok"
        assert result_data["response"] == "The current time is 19:46:56, sir."
        assert result_data["tool"] == "fol"
        mock_call_fol_api.assert_called_once_with(
            "/api/chat", {"message": "time"}
        )

    @pytest.mark.asyncio
    @patch("server.call_fol_api")
    async def test_russian_command(self, mock_call_fol_api):
        """fol_command should support Russian commands."""
        mock_call_fol_api.return_value = {
            "response": "Громкость увеличена на 10%",
        }

        result = await execute_tool_call("fol_command", {"command": "прибавь громкость"})
        result_data = json.loads(result)

        assert result_data["status"] == "ok"
        assert "Громкость" in result_data["response"]
        assert "увеличена" in result_data["response"]
        mock_call_fol_api.assert_called_once_with(
            "/api/chat", {"message": "прибавь громкость"}
        )

    @pytest.mark.asyncio
    async def test_empty_command(self):
        """fol_command with empty command should return error."""
        result = await execute_tool_call("fol_command", {"command": ""})
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Empty command" in result_data["error"]

    @pytest.mark.asyncio
    @patch("server.call_fol_api")
    async def test_missing_command_key(self, mock_call_fol_api):
        """fol_command without command argument should return error."""
        result = await execute_tool_call("fol_command", {})
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Empty command" in result_data["error"]

    @pytest.mark.asyncio
    @patch("server.call_fol_api")
    async def test_fol_api_error(self, mock_call_fol_api):
        """When call_fol_api returns an error, it should be propagated."""
        mock_call_fol_api.return_value = {
            "error": "FOL server error: 500 Internal Server Error",
            "response": "",
        }

        result = await execute_tool_call("fol_command", {"command": "screenshot"})
        result_data = json.loads(result)

        assert "error" in result_data
        assert "FOL command failed" in result_data["error"]

    @pytest.mark.asyncio
    @patch("server.call_fol_api")
    async def test_fol_api_error_with_partial_response(self, mock_call_fol_api):
        """Error from FOL should include partial response if available."""
        mock_call_fol_api.return_value = {
            "error": "Rate limited",
            "response": "Please wait 10 seconds.",
        }

        result = await execute_tool_call("fol_command", {"command": "status"})
        result_data = json.loads(result)

        assert "error" in result_data
        assert "Rate limited" in result_data["error"]
        assert result_data["response"] == "Please wait 10 seconds."


# ---------------------------------------------------------------------------
# GET /fol/status endpoint tests
# ---------------------------------------------------------------------------

class TestFolStatusEndpoint:
    """Tests for GET /fol/status."""

    @pytest.mark.asyncio
    async def test_fol_status_healthy(self, client):
        """GET /fol/status should return FOL health when FOL is running."""
        with patch("server.check_fol_health", return_value={
            "status": "healthy", "version": "2.0.0",
            "llm": "active", "tools": "active",
        }):
            response = await client.get("/fol/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["version"] == "2.0.0"

    @pytest.mark.asyncio
    async def test_fol_status_unreachable(self, client):
        """GET /fol/status should report unreachable when FOL is down."""
        with patch("server.check_fol_health", return_value={
            "status": "unreachable", "error": "Connection refused",
        }):
            response = await client.get("/fol/status")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "unreachable"

    @pytest.mark.asyncio
    async def test_fol_status_included_in_full_status(self, client):
        """GET /status should include fol_status field."""
        with patch("server.check_fol_health", return_value={
            "status": "healthy",
        }), patch("server.call_agent_server", return_value={"status": "ok"}):
            response = await client.get("/status")
            assert response.status_code == 200
            data = response.json()
            assert "fol_status" in data
            assert data["fol_status"]["status"] == "healthy"


# ---------------------------------------------------------------------------
# POST /fol/command endpoint tests
# ---------------------------------------------------------------------------

class TestFolCommandEndpoint:
    """Tests for POST /fol/command."""

    @pytest.mark.asyncio
    async def test_missing_command(self, client):
        """POST /fol/command without command should return 400."""
        response = await client.post("/fol/command", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "Empty command"

    @pytest.mark.asyncio
    async def test_fol_not_running(self, client):
        """POST /fol/command when FOL is down should return 503."""
        with patch("server.check_fol_health", return_value={
            "status": "unreachable",
        }):
            response = await client.post("/fol/command", json={"command": "status"})
            assert response.status_code == 503
            data = response.json()
            assert data["error"] == "FOL server not running"

    @pytest.mark.asyncio
    async def test_successful_command(self, client):
        """POST /fol/command should proxy command to FOL and return result."""
        with patch("server.check_fol_health", return_value={
            "status": "healthy",
        }), patch("server.call_fol_api", return_value={
            "response": "System status: all nominal, sir.",
        }):
            response = await client.post("/fol/command", json={"command": "status"})
            assert response.status_code == 200
            data = response.json()
            assert "response" in data

    @pytest.mark.asyncio
    async def test_command_response_structure(self, client):
        """POST /fol/command response should include FOL response and metadata."""
        with patch("server.check_fol_health", return_value={
            "status": "healthy",
        }), patch("server.call_fol_api", return_value={
            "response": "Battery at 85%, sir.",
            "status": "ok",
        }):
            response = await client.post("/fol/command", json={"command": "battery"})
            assert response.status_code == 200
            data = response.json()
            assert data["response"] == "Battery at 85%, sir."
