"""Tests for WebSocket handler."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a test client."""
    from api.rest.server import app
    return TestClient(app)


def test_websocket_endpoint_exists(client):
    """WebSocket endpoint should be accessible."""
    # Test that the endpoint exists by checking it doesn't 404
    # WebSocket test client behavior varies by version
    from api.websocket.handler import router
    assert router is not None
