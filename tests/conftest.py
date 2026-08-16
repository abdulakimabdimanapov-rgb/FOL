"""Shared fixtures for orchestrator/server.py integration tests.

Fixtures:
- reset_globals: resets server state between tests (non-autouse, opt-in via pytestmark)
- client: synchronous FastAPI TestClient
- async_client: async httpx client for SSE streaming

Helper functions are in helpers.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add paths so imports work
sys.path.insert(0, str(Path(__file__).parent))                     # tests/
sys.path.insert(0, str(Path(__file__).parent / ".." / "orchestrator"))  # orchestrator/
sys.path.insert(0, str(Path(__file__).parent / ".."))                 # project root
from agents import AgentType

import pytest
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio
import httpx
from httpx import ASGITransport
from fastapi.testclient import TestClient


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def reset_globals() -> None:
    """Reset global state and module-level vars between tests.

    NOT autouse — each test file must opt in via ``pytestmark``
    or declare it as a dependency.
    """
    import server as srv
    srv.current_job["id"] = None
    srv.current_job["state"] = "idle"
    srv.current_job["task"] = None
    srv.current_job["actions"] = []
    srv.current_job["started_at"] = None
    srv.current_job["message_queue"] = []
    srv._conversation_history.clear()
    srv._cookies_synced = False
    srv._cookies_sync_offered = False
    srv._user_uid = None
    srv._google_access_token = None
    srv._current_agent_type = AgentType.GENERAL
    srv._prompt_cache["key"] = None
    srv._prompt_cache["prompt"] = None


@pytest.fixture
def client() -> TestClient:
    """Return a TestClient with the server's FastAPI app (synchronous, non-SSE tests)."""
    from server import app
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def async_client() -> httpx.AsyncClient:
    """Return an async httpx client wired to the FastAPI app (for SSE streaming tests)."""
    from server import app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def mock_agent_server() -> object:
    """Patch ``server.call_agent_server`` to return ``{"status": "ok"}`` by default.

    Tests that need a different return value or side effect can reconfigure
    the yielded mock::

        def test_error(self, mock_agent_server, client):
            mock_agent_server.side_effect = Exception("Connection refused")
            ...
    """
    with patch("server.call_agent_server", return_value={"status": "ok"}) as mock:
        yield mock


@pytest.fixture
def mock_obsidian() -> object:
    """Patch ``server.check_obsidian_connection`` to return ``False`` by default."""
    with patch("server.check_obsidian_connection", return_value=False) as mock:
        yield mock


@pytest.fixture
def mock_fol_health() -> object:
    """Patch ``server.check_fol_health`` to return ``{"status": "healthy"}`` by default."""
    with patch("server.check_fol_health", return_value={"status": "healthy"}) as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_context_snapshot() -> None:
    """Mock all macOS subprocess calls in the context engine.

    Patches:
    - ``context_engine.snapshot.get_snapshot`` — calls ``osascript`` via ``get_active_app``
    - ``context_engine.browser_url.get_browser_url`` — calls ``osascript`` per browser

    These are used by ``build_context_messages()`` and add ~10-100ms per test.
    This fixture makes all tests fast and macOS-independent.
    """
    with patch("context_engine.snapshot.get_snapshot") as mock_snapshot:
        mock_snapshot.return_value = MagicMock(app_name="", browser_url="")
        with patch("context_engine.browser_url.get_browser_url") as mock_url:
            mock_url.return_value = {"url": "", "title": "", "domain": ""}
            yield
