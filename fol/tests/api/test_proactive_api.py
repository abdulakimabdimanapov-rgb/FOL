"""Tests for the proactive REST endpoints and WebSocket delivery.

REST tests use a fake FOL instance patched into ``api.rest.server`` (the
routes only touch ``_init_proactive`` / ``_proactive`` / ``proactive_tick``).
The WebSocket test verifies the canonical delivery path: a suggestion emitted
by the service reaches connected clients as an ``EVENT_PROACTIVE`` message.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from modules.llm.proactive import ProactiveSuggestion


class FakeProactive:
    """Minimal stand-in for ProactiveService used by the routes."""

    def __init__(self) -> None:
        self.enabled = False
        self._stats = {
            "enabled": False,
            "total_commands": 0,
            "session_minutes": 0,
            "cooldown_minutes": 5,
            "max_per_hour": 3,
            "emitted_this_hour": 0,
            "rules": 12,
            "last_suggestion": None,
        }

    def stats(self) -> dict:
        return dict(self._stats)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._stats["enabled"] = enabled


class FakeFol:
    """Hermetic FOL stand-in exposing only what the proactive routes use."""

    def __init__(self) -> None:
        self._proactive = FakeProactive()

    def _init_proactive(self) -> None:
        pass

    def _proactive_on(self, lang: str) -> None:
        self._proactive.set_enabled(True)

    def _proactive_off(self, lang: str) -> None:
        self._proactive.set_enabled(False)

    async def proactive_tick(self, *, force: bool = False):
        return None


@pytest.fixture
def client():
    from api.rest.server import app

    return TestClient(app)


@pytest.fixture
def fake_fol() -> FakeFol:
    return FakeFol()


class TestProactiveStatus:
    def test_status_returns_503_without_fol(self, client):
        with patch("api.rest.server._fol_instance", None):
            resp = client.get("/proactive/status")
            assert resp.status_code == 503

    def test_status_default_off(self, client, fake_fol):
        with patch("api.rest.server._fol_instance", fake_fol):
            resp = client.get("/proactive/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["enabled"] is False
            assert data["rules"] == 12
            assert data["max_per_hour"] == 3


class TestProactiveToggle:
    def test_toggle_on(self, client, fake_fol):
        with patch("api.rest.server._fol_instance", fake_fol):
            resp = client.post("/proactive/toggle", json={"enabled": True})
            assert resp.status_code == 200
            assert resp.json()["enabled"] is True
            assert fake_fol._proactive.enabled is True

    def test_toggle_off(self, client, fake_fol):
        fake_fol._proactive.set_enabled(True)
        with patch("api.rest.server._fol_instance", fake_fol):
            resp = client.post("/proactive/toggle", json={"enabled": False})
            assert resp.status_code == 200
            assert resp.json()["enabled"] is False

    def test_toggle_validation(self, client, fake_fol):
        with patch("api.rest.server._fol_instance", fake_fol):
            resp = client.post("/proactive/toggle", json={})
            assert resp.status_code == 422  # missing required field

    def test_toggle_503_without_fol(self, client):
        with patch("api.rest.server._fol_instance", None):
            resp = client.post("/proactive/toggle", json={"enabled": True})
            assert resp.status_code == 503


class TestProactiveCheck:
    def test_check_without_fol_503(self, client):
        with patch("api.rest.server._fol_instance", None):
            resp = client.post("/proactive/check")
            assert resp.status_code == 503

    def test_check_returns_suggestion(self, client):
        fol = FakeFol()

        async def tick(*, force=False):
            return ProactiveSuggestion(
                title="Время для перерыва ⏸️",
                description="Вы работаете больше часа.",
                action="suggest_break",
                priority=0.55,
                category="health",
            )

        fol.proactive_tick = tick  # type: ignore[method-assign]
        with patch("api.rest.server._fol_instance", fol):
            resp = client.post("/proactive/check")
            assert resp.status_code == 200
            data = resp.json()
            assert data["enabled"] is False
            assert data["suggestion"] is not None
            assert data["suggestion"]["title"] == "Время для перерыва ⏸️"
            assert data["suggestion"]["category"] == "health"

    def test_check_no_suggestion(self, client, fake_fol):
        with patch("api.rest.server._fol_instance", fake_fol):
            resp = client.post("/proactive/check")
            assert resp.status_code == 200
            assert resp.json()["suggestion"] is None


class TestWebSocketBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast_proactive_sends_event(self):
        from api.websocket.handler import _clients, broadcast_proactive

        sent = []

        class FakeWS:
            async def send_text(self, msg: str) -> None:
                sent.append(msg)

        _clients.clear()
        _clients.add(FakeWS())
        try:
            suggestion = ProactiveSuggestion(
                title="Почта 📧",
                description="Могу открыть почту.",
                action="open_mail",
                priority=0.4,
                category="productivity",
            )
            await broadcast_proactive(suggestion)
            assert len(sent) == 1
            data = json.loads(sent[0])
            assert data["type"] == "proactive_suggestion"
            assert data["payload"]["title"] == "Почта 📧"
            assert data["payload"]["category"] == "productivity"
        finally:
            _clients.clear()

    @pytest.mark.asyncio
    async def test_broadcast_proactive_none_is_noop(self):
        from api.websocket.handler import _clients, broadcast_proactive

        sent = []

        class FakeWS:
            async def send_text(self, msg: str) -> None:
                sent.append(msg)

        _clients.clear()
        _clients.add(FakeWS())
        try:
            await broadcast_proactive(None)
            assert sent == []
        finally:
            _clients.clear()

    def test_event_type_constant(self):
        from api.websocket.events import EVENT_PROACTIVE

        assert EVENT_PROACTIVE == "proactive_suggestion"

    @pytest.mark.asyncio
    async def test_event_bus_to_ws_bridge(self):
        """The canonical EventBus → WebSocket bridge: a PROACTIVE_SUGGESTION
        event published by FOL.proactive_tick() reaches connected clients."""
        from api.websocket.handler import _clients, forward_event_proactive
        from core.event_bus import Event, EventType

        sent = []

        class FakeWS:
            async def send_text(self, msg: str) -> None:
                sent.append(msg)

        _clients.clear()
        _clients.add(FakeWS())
        try:
            suggestion = ProactiveSuggestion(
                title="Перерыв ⏸️", description="Пора отдохнуть.", action="suggest_break",
            )
            event = Event(
                type=EventType.PROACTIVE_SUGGESTION,
                source="app",
                payload={"suggestion": suggestion},
            )
            await forward_event_proactive(event)
            assert len(sent) == 1
            data = json.loads(sent[0])
            assert data["type"] == "proactive_suggestion"
            assert data["payload"]["title"] == "Перерыв ⏸️"
        finally:
            _clients.clear()

    @pytest.mark.asyncio
    async def test_event_bus_to_ws_bridge_skips_empty_payload(self):
        from api.websocket.handler import _clients, forward_event_proactive
        from core.event_bus import Event, EventType

        sent = []

        class FakeWS:
            async def send_text(self, msg: str) -> None:
                sent.append(msg)

        _clients.clear()
        _clients.add(FakeWS())
        try:
            event = Event(type=EventType.PROACTIVE_SUGGESTION, payload={})
            await forward_event_proactive(event)
            assert sent == []
        finally:
            _clients.clear()
