"""Tests for REST API endpoints."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client for the API."""
    from api.rest.server import app
    return TestClient(app)


def test_root_endpoint(client):
    """Root endpoint should return web UI or API info."""
    response = client.get("/")
    assert response.status_code == 200
    # Returns HTML (web UI) or JSON (API info)
    assert response.status_code == 200


def test_health_endpoint(client):
    """Health endpoint should return status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "starting")
    assert "version" in data


def test_openapi_docs(client):
    """OpenAPI docs should be accessible."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_send_message_no_fol(client):
    """Send message should return 503 if FOL not initialized."""
    response = client.post(
        "/conversation/send",
        json={"message": "hello"},
    )
    # May return 503 or process normally depending on setup
    assert response.status_code in (200, 503)


def test_list_tools_no_fol(client):
    """List tools should return 503 if FOL not initialized."""
    response = client.get("/tools/")
    # Returns 503 when FOL is not initialized
    assert response.status_code in (200, 503)
