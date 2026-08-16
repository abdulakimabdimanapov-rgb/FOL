"""Unit tests for the shared Brain vault integration.

When a ``shared_vault`` (``~/Obsidian/Brain``) is configured, the FOL app
mirrors its journal into the shared assistant structure (Profile/ Goals/
Models/ Conversations/) and merges the shared context into the LLM prompt —
so the FOL app and any AI assistant share one memory.

Tests use tmp_path vaults and never touch the real Obsidian vaults.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from modules.memory.brain import Brain


@pytest.fixture
def shared_brain(tmp_path: Path) -> Brain:
    """Brain with both a local vault and a shared assistant vault."""
    return Brain(
        vault_path=tmp_path / "local-vault",
        shared_vault=tmp_path / "shared-brain",
    )


@pytest.fixture
def shared_root(shared_brain: Brain) -> Path:
    return shared_brain._shared_vault  # type: ignore[return-value]


def test_creates_shared_structure(shared_brain: Brain, shared_root: Path):
    assert shared_root.exists()
    for folder in ("Profile", "Goals", "Models", "Conversations"):
        assert (shared_root / folder).exists(), folder


# ─── Mirroring turns into Conversations/ ────────────────────────────────

class TestSharedTurns:
    def test_record_turn_mirrors_to_shared_conversations(
        self, shared_brain: Brain, shared_root: Path
    ):
        ok = shared_brain.record_turn("Привет", "Привет! Чем помочь?")
        assert ok
        today = datetime.now().strftime("%Y-%m-%d")
        conv = shared_root / "Conversations" / f"{today}.md"
        assert conv.exists()
        text = conv.read_text(encoding="utf-8")
        assert "Привет" in text
        assert "Привет! Чем помочь?" in text
        assert "User:" in text
        assert "FOL:" in text

    def test_record_turn_appends_not_overwrites(
        self, shared_brain: Brain, shared_root: Path
    ):
        shared_brain.record_turn("a", "1")
        shared_brain.record_turn("b", "2")
        today = datetime.now().strftime("%Y-%m-%d")
        text = (shared_root / "Conversations" / f"{today}.md").read_text(encoding="utf-8")
        assert text.count("**User:**") == 2

    def test_no_shared_vault_means_no_mirror(self, tmp_path: Path):
        """Default Brain (no shared_vault) must not create shared files."""
        brain = Brain(vault_path=tmp_path / "vault")
        brain.record_turn("Привет", "Привет!")
        assert not (tmp_path / "shared-brain").exists()


# ─── Mirroring model changes into Models/Change-Log.md ─────────────────

class TestSharedModelLog:
    def test_model_change_mirrored(self, shared_brain: Brain, shared_root: Path):
        shared_brain.record_model_change("gpt-4o-mini")
        text = (shared_root / "Models" / "Change-Log.md").read_text(encoding="utf-8")
        assert "gpt-4o-mini" in text
        assert "[FOL]" in text


# ─── Mirroring profile / preferences / projects ─────────────────────────

class TestSharedProfile:
    def test_set_user_info_mirrors(self, shared_brain: Brain, shared_root: Path):
        shared_brain.set_user_info("name", "Alex")
        text = (shared_root / "Profile" / "User.md").read_text(encoding="utf-8")
        assert "- name: Alex" in text

    def test_upsert_updates_assistant_style_bold_key(
        self, shared_brain: Brain, shared_root: Path
    ):
        """Assistant-written bullets use `- **key:** value`; FOL's upsert must
        update that style in place instead of appending a duplicate."""
        (shared_root / "Profile" / "User.md").write_text(
            "# Пользователь\n\n- **Имя:** Абдулахим\n- **Роль:** разработчик\n",
            encoding="utf-8",
        )
        shared_brain.set_user_info("имя", "Абдулахим (обновлено)")
        text = (shared_root / "Profile" / "User.md").read_text(encoding="utf-8")
        assert text.count("Имя") == 1, "must update in place, not duplicate"
        assert "**Имя:** Абдулахим (обновлено)" in text

    def test_set_preference_mirrors(self, shared_brain: Brain, shared_root: Path):
        shared_brain.set_preference("language", "ru")
        text = (shared_root / "Profile" / "Preferences.md").read_text(encoding="utf-8")
        assert "- language: ru" in text

    def test_record_project_mirrors(self, shared_brain: Brain, shared_root: Path):
        shared_brain.record_project("FOL v2")
        text = (shared_root / "Profile" / "Projects.md").read_text(encoding="utf-8")
        assert "FOL v2" in text
        assert "In progress" in text


# ─── Reading shared context ─────────────────────────────────────────────

class TestSharedContext:
    def test_empty_shared_adds_nothing(self, shared_brain: Brain):
        ctx = shared_brain.get_brain_context()
        assert isinstance(ctx, str)

    def test_context_includes_shared_profile(
        self, shared_brain: Brain, shared_root: Path
    ):
        # Assistant wrote profile files directly into the shared vault.
        (shared_root / "Profile" / "User.md").write_text(
            "# User\n\n- name: Абдулахим\n- роль: разработчик\n", encoding="utf-8"
        )
        ctx = shared_brain.get_brain_context()
        assert "Абдулахим" in ctx
        assert "Shared profile" in ctx

    def test_context_includes_shared_goals(self, shared_brain: Brain, shared_root: Path):
        (shared_root / "Goals" / "Wants.md").write_text(
            "# Цели\n\n- сдать IELTS\n- заработать онлайн\n", encoding="utf-8"
        )
        ctx = shared_brain.get_brain_context()
        assert "IELTS" in ctx
        assert "Shared goals" in ctx

    def test_context_includes_shared_recent_conversations(
        self, shared_brain: Brain, shared_root: Path
    ):
        conv = shared_root / "Conversations" / "2026-08-12-some-chat.md"
        conv.parent.mkdir(exist_ok=True)
        conv.write_text(
            "# 2026-08-12\n\n- **10:00** **User:** открыть сафари\n  **FOL:** ок\n",
            encoding="utf-8",
        )
        ctx = shared_brain.get_brain_context()
        assert "открыть сафари" in ctx

    def test_mirrored_turns_visible_in_context(self, shared_brain: Brain):
        shared_brain.record_turn("Найди новости про OpenAI", "Нашёл новости.")
        ctx = shared_brain.get_brain_context()
        assert "Найди новости про OpenAI" in ctx

    def test_shared_profile_survives_truncation(self, shared_brain: Brain):
        """Who the user is (shared profile, first sections) must survive even
        a tiny max_chars budget — volatile tails are cut first."""
        shared_root = shared_brain._shared_vault
        (shared_root / "Profile" / "User.md").write_text(
            "# User\n\n- name: Абдулахим\n- роль: разработчик\n", encoding="utf-8"
        )
        for i in range(30):
            shared_brain.record_turn(f"вопрос {i}", "ответ " * 40)
        ctx = shared_brain.get_brain_context(max_chars=300)
        assert "Абдулахим" in ctx, "shared profile must survive truncation"

    def test_record_project_shared_dedup(self, shared_brain: Brain, shared_root: Path):
        """Existing numbered headings like `## 1. FOL v2` must not duplicate."""
        (shared_root / "Profile" / "Projects.md").write_text(
            "# Проекты\n\n## 1. FOL v2\n- Status: done\n", encoding="utf-8"
        )
        shared_brain.record_project("FOL v2")
        text = (shared_root / "Profile" / "Projects.md").read_text(encoding="utf-8")
        assert text.count("FOL v2") == 1, "must not duplicate existing project"


# ─── Resilience ─────────────────────────────────────────────────────────

class TestSharedResilience:
    def test_shared_write_failure_never_raises(self, tmp_path: Path):
        locked = tmp_path / "blocked"
        locked.write_text("file", encoding="utf-8")  # file where dir expected
        brain = Brain(
            vault_path=tmp_path / "vault",
            shared_vault=locked / "nope",  # unwritable path
        )
        # must not raise
        assert brain.record_turn("x", "y") in (True, False)
        assert brain.record_model_change("m") in (True, False)
        assert brain.set_user_info("name", "Alex") in (True, False)

    def test_shared_context_never_raises(self, tmp_path: Path):
        brain = Brain(
            vault_path=tmp_path / "vault",
            shared_vault=tmp_path / "shared",
        )
        assert isinstance(brain.get_brain_context(), str)
