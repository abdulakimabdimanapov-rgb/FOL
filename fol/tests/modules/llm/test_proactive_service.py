"""Tests for ProactiveService — the runtime layer of Proactive Mode (ROADMAP Etap 5).

Covers the anti-nagging policy required by the ROADMAP: default OFF, ON/OFF
toggle, cooldown between suggestions, per-hour cap, forced (on-demand) checks,
session statistics, dismissal and suggestion generation. Deterministic: rules
that depend on the clock (hour/weekend) are avoided by driving session stats
(repeated commands / long session) instead.
"""

from __future__ import annotations

import time

import pytest

from modules.llm.proactive import ProactiveAssistant, ProactiveService


@pytest.fixture
def service() -> ProactiveService:
    return ProactiveService(enabled=True)


def _repeat(service: ProactiveService, command: str = "запусти тесты", times: int = 3) -> None:
    """Record the same command ``times`` times → repeated_command rule fires."""
    for _ in range(times):
        service.record_command(command)


class TestDefaultOff:
    def test_disabled_by_default(self):
        svc = ProactiveService()
        assert svc.enabled is False

    @pytest.mark.asyncio
    async def test_check_returns_none_when_off(self):
        svc = ProactiveService()
        _repeat(svc)  # would fire when enabled
        assert await svc.check() is None


class TestToggle:
    def test_set_enabled(self):
        svc = ProactiveService()
        svc.set_enabled(True)
        assert svc.enabled is True
        svc.set_enabled(False)
        assert svc.enabled is False

    @pytest.mark.asyncio
    async def test_reenable_clears_cooldown_and_cap(self):
        svc = ProactiveService(enabled=True, cooldown_minutes=60, max_per_hour=1)
        _repeat(svc)
        assert await svc.check() is not None
        # Cooldown + cap now both active → suppressed.
        assert await svc.check() is None
        # Real OFF→ON transition resets both → a fresh suggestion is allowed.
        svc.set_enabled(False)
        svc.set_enabled(True)
        assert await svc.check() is not None

    @pytest.mark.asyncio
    async def test_repeated_set_enabled_true_does_not_reset_antinagging(self):
        """set_enabled(True) while already enabled must NOT clear the cooldown
        or the hourly cap — otherwise a spam of "proactive on" (or REST
        toggles) could defeat the anti-nagging policy."""
        svc = ProactiveService(enabled=True, cooldown_minutes=60, max_per_hour=1)
        _repeat(svc)
        assert await svc.check() is not None
        assert await svc.check() is None  # cooldown active
        svc.set_enabled(True)  # already enabled → no reset
        assert await svc.check() is None
        # A real OFF→ON transition DOES reset (covered by test above).
        svc.set_enabled(False)
        svc.set_enabled(True)
        assert await svc.check() is not None


class TestSuggestionGeneration:
    @pytest.mark.asyncio
    async def test_repeated_command_fires(self):
        svc = ProactiveService(enabled=True)
        _repeat(svc)
        s = await svc.check()
        assert s is not None
        assert "автоматизац" in s.title.lower() or "frequent" in s.title.lower()

    @pytest.mark.asyncio
    async def test_long_session_fires(self):
        # > 120 min session → very_long_session rule (deterministic, no clock dep).
        svc = ProactiveService(enabled=True, session_start=time.time() - 200 * 60)
        s = await svc.check()
        assert s is not None
        assert "перерыв" in s.description.lower() or "break" in s.description.lower()

    @pytest.mark.asyncio
    async def test_no_rule_no_suggestion(self):
        svc = ProactiveService(enabled=True)
        # Two commands: total != 1 (first_command off), no repeats, fresh
        # session; middle of the day, weekday → no time rule fires either.
        svc.record_command("привет")
        svc.record_command("как дела")
        s = await svc.check(context_extra={"hour": 14, "is_weekend": False})
        assert s is None


class TestCooldown:
    @pytest.mark.asyncio
    async def test_cooldown_suppresses_second_immediate_check(self):
        svc = ProactiveService(enabled=True, cooldown_minutes=30)
        _repeat(svc)
        first = await svc.check()
        assert first is not None
        assert await svc.check() is None  # still in cooldown

    @pytest.mark.asyncio
    async def test_cooldown_expiry_allows_new_suggestion(self):
        svc = ProactiveService(enabled=True, cooldown_minutes=5)
        _repeat(svc)
        assert await svc.check() is not None
        # Simulate time passing past the cooldown window.
        svc._last_emitted_at = time.time() - 6 * 60
        assert await svc.check() is not None


class TestHourlyCap:
    @pytest.mark.asyncio
    async def test_cap_blocks_after_max_per_hour(self):
        svc = ProactiveService(enabled=True, cooldown_minutes=0, max_per_hour=2)
        _repeat(svc)
        assert await svc.check() is not None
        assert await svc.check() is not None
        # Cap exhausted → suppressed even though cooldown is 0.
        assert await svc.check() is None

    @pytest.mark.asyncio
    async def test_old_emissions_fall_out_of_window(self):
        svc = ProactiveService(enabled=True, cooldown_minutes=0, max_per_hour=1)
        _repeat(svc)
        assert await svc.check() is not None
        assert await svc.check() is None
        # Emissions older than an hour no longer count toward the cap.
        svc._emission_times = [time.time() - 3601]
        assert await svc.check() is not None


class TestForce:
    @pytest.mark.asyncio
    async def test_force_bypasses_cooldown(self):
        svc = ProactiveService(enabled=True, cooldown_minutes=60)
        _repeat(svc)
        assert await svc.check() is not None
        # Cooldown active → normal check suppressed, forced check allowed.
        assert await svc.check() is None
        assert await svc.check(force=True) is not None

    @pytest.mark.asyncio
    async def test_force_still_respects_toggle(self):
        svc = ProactiveService(enabled=False)
        _repeat(svc)
        assert await svc.check(force=True) is None


class TestDismiss:
    @pytest.mark.asyncio
    async def test_dismissed_suggestion_does_not_reappear(self):
        svc = ProactiveService(enabled=True, cooldown_minutes=0, max_per_hour=10)
        _repeat(svc, "запусти тесты")
        s1 = await svc.check()
        assert s1 is not None
        assert await svc.dismiss(s1.title) is True
        # Same rule, same context → dismissed title must not return.
        s2 = await svc.check(force=True)
        assert s2 is None or s2.title != s1.title

    @pytest.mark.asyncio
    async def test_dismiss_unknown_returns_false(self):
        assert await ProactiveService(enabled=True).dismiss("нет такого") is False


class TestStatsAndSession:
    def test_record_command_counts(self):
        svc = ProactiveService()
        svc.record_command("привет")
        svc.record_command("привет")
        svc.record_command("  ")
        assert svc.total_commands == 2
        assert svc.session_minutes() >= 0

    def test_record_tool_use(self):
        svc = ProactiveService()
        svc.record_tool_use("search_files")
        svc.record_tool_use("search_files")
        ctx = svc._build_context()
        assert ctx["recent_tool_count"] == {"search_files": 2}

    def test_stats_snapshot(self):
        svc = ProactiveService(enabled=True)
        svc.record_command("x")
        stats = svc.stats()
        assert stats["enabled"] is True
        assert stats["total_commands"] == 1
        assert stats["rules"] >= 3
        assert stats["max_per_hour"] == 3
        assert stats["last_suggestion"] is None

    @pytest.mark.asyncio
    async def test_last_suggestion_recorded(self):
        svc = ProactiveService(enabled=True)
        _repeat(svc)
        s = await svc.check()
        assert s is not None
        assert svc.last_suggestion is s
        assert svc.stats()["last_suggestion"] == s.title


class TestAssistantReuse:
    def test_uses_passed_assistant(self):
        assistant = ProactiveAssistant()
        svc = ProactiveService(assistant=assistant)
        assert svc._assistant is assistant
        assert svc.stats()["rules"] == assistant.rule_count
