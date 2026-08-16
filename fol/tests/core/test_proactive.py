"""Tests for Proactive Mode wiring in the FOL app (ROADMAP Etap 5).

Follows the hermetic ``_make_fol()`` convention from ``test_modes.py``: no
real tools, memory, obsidian or network. Covers the RU/EN toggle commands,
status, on-demand requests, EventBus publication and system-status visibility.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.app import FOL
from core.event_bus import EventType


def _make_fol() -> FOL:
    """Hermetic FOL instance — no real tools, memory, obsidian or network."""
    fol = FOL()
    fol._llm = None
    fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
    fol._long_term_memory = None
    fol._obsidian = None
    fol._identity = None
    fol._vision = None
    # Reset the shared settings singleton so a toggle in one test cannot leak
    # proactive_enabled into the next (FOL() reads it during _init_proactive).
    fol.config.proactive_enabled = False
    fol._proactive = None
    return fol


class TestDefaults:
    def test_proactive_uninitialized_until_used(self):
        fol = _make_fol()
        assert fol._proactive is None

    def test_setting_defaults_off(self):
        from config.settings import Settings

        s = Settings()
        assert s.proactive_enabled is False
        assert s.proactive_interval_minutes >= 1
        assert s.proactive_cooldown_minutes >= 1
        assert s.proactive_max_per_hour >= 1

    def test_system_status_shows_off(self):
        fol = _make_fol()
        out = fol._system_status()
        assert "Proactive: off" in out

    def test_help_lists_proactive(self):
        fol = _make_fol()
        assert "proactive on / off" in fol._help()
        assert "предложи что-нибудь" in fol._help()


class TestToggleCommands:
    @pytest.mark.parametrize(
        "cmd,expected_enabled",
        [
            ("proactive on", True),
            ("проактивность вкл", True),
            ("проактивный режим вкл", True),
            ("proactive off", False),
            ("проактивность выкл", False),
        ],
    )
    def test_toggle_commands(self, cmd: str, expected_enabled: bool):
        fol = _make_fol()
        out = fol._handle_builtin_command(cmd)
        assert fol._proactive is not None
        assert fol._proactive.enabled is expected_enabled
        assert out
        # Runtime toggle state lives ONLY on the service — the shared settings
        # singleton must never be mutated (no cross-test/session leakage).
        assert fol.config.proactive_enabled is False

    def test_status_ru(self):
        fol = _make_fol()
        fol._handle_builtin_command("проактивность вкл")
        out = fol._handle_builtin_command("проактивность статус")
        assert "включён" in out
        assert "Предложений за час" in out

    def test_status_en(self):
        fol = _make_fol()
        out = fol._handle_builtin_command("proactive status")
        assert "Proactive mode: off" in out
        assert "Session commands" in out

    def test_status_bare_russian(self):
        fol = _make_fol()
        out = fol._handle_builtin_command("проактивность")
        assert "Проактивный режим" in out

    @pytest.mark.asyncio
    async def test_process_toggle(self):
        fol = _make_fol()
        out = await fol.process("проактивность вкл")
        assert fol._proactive.enabled is True
        assert "включён" in out


class TestEventBusPublication:
    @pytest.mark.asyncio
    async def test_tick_publishes_proactive_suggestion_event(self):
        fol = _make_fol()
        fol._init_proactive()
        fol._proactive.set_enabled(True)
        # Deterministic trigger: > 120 min session → very_long_session rule.
        fol._proactive._session_start = time.time() - 200 * 60

        received = []

        async def handler(event):
            received.append(event)

        fol.event_bus.subscribe(EventType.PROACTIVE_SUGGESTION, handler)
        suggestion = await fol.proactive_tick()
        assert suggestion is not None
        assert len(received) == 1
        assert received[0].type == EventType.PROACTIVE_SUGGESTION
        # The EventBus carries the suggestion object — single canonical payload.
        assert received[0].payload["suggestion"] is suggestion

    @pytest.mark.asyncio
    async def test_tick_no_event_when_disabled(self):
        fol = _make_fol()
        fol._init_proactive()  # enabled=False by default
        received = []

        async def handler(event):
            received.append(event)

        fol.event_bus.subscribe(EventType.PROACTIVE_SUGGESTION, handler)
        suggestion = await fol.proactive_tick()
        assert suggestion is None
        assert received == []

    @pytest.mark.asyncio
    async def test_toggle_emits_proactive_toggled_event(self):
        fol = _make_fol()
        received = []

        async def handler(event):
            received.append(event)

        fol.event_bus.subscribe(EventType.PROACTIVE_TOGGLED, handler)
        fol._handle_builtin_command("proactive on")
        # emit() schedules the publish as a task — yield so it actually runs.
        await asyncio.sleep(0.01)
        assert any(
            e.type == EventType.PROACTIVE_TOGGLED and e.payload.get("enabled") is True
            for e in received
        )


class TestOnDemandRequest:
    @pytest.mark.parametrize(
        "cmd",
        [
            "предложи что-нибудь",
            "предложи идею",
            "proactive now",
            "suggest something",
        ],
    )
    def test_is_proactive_request(self, cmd: str):
        fol = _make_fol()
        assert fol._is_proactive_request(cmd.lower())

    def test_non_request_not_hijacked(self):
        fol = _make_fol()
        assert fol._is_proactive_request("что предложишь по проекту?") is False

    @pytest.mark.asyncio
    async def test_request_when_disabled_explains(self):
        fol = _make_fol()
        out = await fol.process("предложи что-нибудь")
        assert "проактивность вкл" in out  # RU hint how to enable

    @pytest.mark.asyncio
    async def test_request_enabled_returns_suggestion(self):
        fol = _make_fol()
        fol._init_proactive()
        fol._proactive.set_enabled(True)
        fol._proactive._session_start = time.time() - 200 * 60  # long session
        out = await fol.process("предложи что-нибудь")
        assert "💡" in out
        assert fol._proactive.last_suggestion is not None

    @pytest.mark.asyncio
    async def test_request_recorded_as_command(self):
        fol = _make_fol()
        fol._init_proactive()
        fol._proactive.set_enabled(True)
        await fol.process("suggest something")
        assert fol._proactive.total_commands >= 1


class TestStatsRecording:
    @pytest.mark.asyncio
    async def test_process_records_commands(self):
        fol = _make_fol()
        fol._init_proactive()
        fol._proactive.set_enabled(True)
        await fol.process("привет")
        assert fol._proactive.total_commands == 1

    def test_tool_use_recorded(self):
        fol = _make_fol()
        fol._init_proactive()
        # No real tool registry — call the recording hook directly.
        fol._proactive.record_tool_use("search_files")
        ctx = fol._proactive._build_context()
        assert ctx["recent_tool_count"].get("search_files") == 1
