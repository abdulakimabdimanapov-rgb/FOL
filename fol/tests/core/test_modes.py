"""Tests for the Modes feature (ROADMAP Этап 2) — companion/assistant/agent/focus."""

from __future__ import annotations

import pytest

from core.app import FOL


def _make_fol() -> FOL:
    """Hermetic FOL instance — no real tools, memory, obsidian or network."""
    fol = FOL()
    fol._llm = None
    fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
    fol._long_term_memory = None
    fol._obsidian = None
    fol._identity = None
    fol._vision = None
    return fol


class TestModeSwitching:
    @pytest.mark.parametrize(
        "cmd,expected",
        [
            ("режим фокус", "focus"),
            ("режим фокуса", "focus"),
            ("focus mode", "focus"),
            ("mode focus", "focus"),
            ("режим ассистент", "assistant"),
            ("режим помощник", "assistant"),
            ("assistant mode", "assistant"),
            ("режим агент", "agent"),
            ("agent mode", "agent"),
            ("режим компаньон", "companion"),
            ("companion mode", "companion"),
            ("режим общение", "companion"),
        ],
    )
    def test_switch_modes(self, cmd: str, expected: str):
        fol = _make_fol()
        out = fol._handle_builtin_command(cmd)
        assert fol._mode == expected, f"{cmd!r} should set mode {expected}"
        assert out
        assert "активирован" in out.lower() or "activated" in out.lower()

    def test_mode_start_default(self):
        assert _make_fol()._mode == "companion"

    @pytest.mark.parametrize(
        "cmd",
        [
            # The ROADMAP voice form — wake word + mode.
            "FOL, режим фокус",
            "FOL, режим Focus",
            "f.o.l., режим фокус",
            "ФОЛ, режим фокус",
            # Trailing politeness.
            "режим фокус пожалуйста",
            "focus mode please",
            "mode focus please",
            # Capitalization is normalized.
            "Режим Фокус",
            "Focus Mode",
        ],
    )
    def test_wake_word_and_politeness_forms(self, cmd: str):
        fol = _make_fol()
        out = fol._handle_builtin_command(cmd)
        assert fol._mode == "focus", f"{cmd!r} should switch to focus"
        assert "активирован" in out.lower() or "activated" in out.lower()

    def test_unknown_mode_shows_status(self):
        fol = _make_fol()
        out = fol._handle_builtin_command("режим космос")
        assert fol._mode == "companion"  # unchanged
        assert "Доступные режимы" in out


class TestModeStatus:
    def test_status_ru(self):
        fol = _make_fol()
        out = fol._handle_builtin_command("режим")
        assert "Компаньон" in out
        assert "Фокус" in out and "Ассистент" in out and "Агент" in out

    def test_status_ru_question_form(self):
        fol = _make_fol()
        out = fol._handle_builtin_command("какой режим?")
        assert "Текущий режим" in out

    def test_status_en(self):
        fol = _make_fol()
        out = fol._handle_builtin_command("mode status")
        assert "Current mode" in out

    def test_status_bare_mode(self):
        fol = _make_fol()
        out = fol._handle_builtin_command("mode")
        assert "Current mode" in out

    def test_status_oblique_form(self):
        # "в каком режиме?" is also a status question.
        fol = _make_fol()
        out = fol._handle_builtin_command("в каком режиме мы сейчас?")
        assert "Текущий режим" in out

    def test_voice_mode_not_hijacked(self):
        # "режим голоса" belongs to the voice subsystem, not the modes feature.
        fol = _make_fol()
        out = fol._handle_builtin_command("режим голоса")
        assert out == "__VOICE_MODE__"
        assert fol._mode == "companion"


class TestModeBehavior:
    def test_mode_hint_in_llm_context(self):
        fol = _make_fol()
        fol._record_turn("привет", "Привет! Чем могу помочь?")
        fol._mode = "focus"
        ctx = fol._get_context("что-нибудь")
        assert "CURRENT MODE: Focus" in ctx
        assert "short sentences" in ctx.lower()

    def test_mode_hint_present_even_without_history(self):
        # A fresh session still tells the LLM about the active mode.
        fol = _make_fol()
        fol._mode = "agent"
        ctx = fol._get_context("сделай что-нибудь")
        assert "CURRENT MODE: Agent" in ctx

    def test_focus_hint_changes_with_mode(self):
        fol = _make_fol()
        fol._record_turn("привет", "Привет!")
        fol._mode = "agent"
        ctx = fol._get_context("что-нибудь")
        assert "CURRENT MODE: Agent" in ctx

    def test_mode_in_system_status(self):
        fol = _make_fol()
        fol._mode = "focus"
        assert "Mode: focus" in fol._system_status()

    def test_mode_persists_across_clear(self):
        # A mode is a session setting — clearing the chat does not reset it.
        fol = _make_fol()
        fol._handle_builtin_command("режим фокус")
        fol._clear_history("ru")
        assert fol._mode == "focus"

    @pytest.mark.asyncio
    async def test_process_switches_mode(self):
        fol = _make_fol()
        out = await fol.process("режим фокус")
        assert fol._mode == "focus"
        assert "активирован" in out.lower()

    @pytest.mark.asyncio
    async def test_process_status_command(self):
        fol = _make_fol()
        out = await fol.process("какой режим?")
        assert "Текущий режим" in out
