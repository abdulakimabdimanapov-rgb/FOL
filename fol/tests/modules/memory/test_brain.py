"""Unit tests for the Freebuff Brain — persistent Obsidian memory that
survives model changes.

The Brain writes markdown files directly into a vault folder (no REST API),
so tests use a tmp_path vault and never touch the real Obsidian vault.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from modules.memory.brain import Brain, _slugify


@pytest.fixture
def brain(tmp_path: Path) -> Brain:
    return Brain(vault_path=tmp_path / "vault")


@pytest.fixture
def today() -> str:
    """Today's date in Work-Log naming format (what record_turn uses)."""
    return datetime.now().strftime("%Y-%m-%d")


# ─── Structure ───────────────────────────────────────────────────────────

class TestStructure:
    def test_creates_brain_folder_and_sections(self, brain: Brain):
        assert brain._brain_dir.exists()
        assert brain._work_dir.exists()
        for name in ("_index.md", "User.md", "Preferences.md", "Projects.md", "Model-Log.md"):
            assert (brain._brain_dir / name).exists(), name

    def test_index_has_links(self, brain: Brain):
        index = (brain._brain_dir / "_index.md").read_text(encoding="utf-8")
        assert "Freebuff Brain" in index
        assert "[[User]]" in index
        assert "[[Model-Log]]" in index


# ─── Work log ────────────────────────────────────────────────────────────

class TestWorkLog:
    def test_record_turn_writes_daily_file(self, brain: Brain):
        ok = brain.record_turn("Привет", "Привет! Чем могу помочь?")
        assert ok
        files = list(brain._work_dir.glob("*.md"))
        assert len(files) == 1
        text = files[0].read_text(encoding="utf-8")
        assert "Привет" in text
        assert "Чем могу помочь" in text
        assert "User:" in text
        assert "FOL:" in text

    def test_record_turn_appends_not_overwrites(self, brain: Brain):
        brain.record_turn("a", "1")
        brain.record_turn("b", "2")
        text = next(brain._work_dir.glob("*.md")).read_text(encoding="utf-8")
        assert text.count("**User:**") == 2

    def test_record_turn_never_raises(self, brain: Brain):
        # even weird input must not raise and must not crash the journal
        ok = brain.record_turn(None, None)  # type: ignore[arg-type]
        assert ok in (False, True)
        # a subsequent normal turn still works
        assert brain.record_turn("привет", "привет!")


# ─── Model log ───────────────────────────────────────────────────────────

class TestModelLog:
    def test_record_model_change_appends(self, brain: Brain):
        brain.record_model_change("gpt-4o-mini")
        brain.record_model_change("llama-3.3-70b")
        text = (brain._brain_dir / "Model-Log.md").read_text(encoding="utf-8")
        assert "gpt-4o-mini" in text
        assert "llama-3.3-70b" in text

    def test_model_history_visible_in_context(self, brain: Brain):
        brain.record_model_change("model-a")
        ctx = brain.get_brain_context()
        assert "model-a" in ctx
        assert "Model history" in ctx

    def test_consecutive_identical_models_not_duplicated(self, brain: Brain):
        brain.record_model_change("gpt-4o-mini")
        brain.record_model_change("gpt-4o-mini")  # restart, same model
        text = (brain._brain_dir / "Model-Log.md").read_text(encoding="utf-8")
        assert text.count("gpt-4o-mini") == 1
        # A real change IS recorded
        brain.record_model_change("llama-3.3-70b")
        text2 = (brain._brain_dir / "Model-Log.md").read_text(encoding="utf-8")
        assert "llama-3.3-70b" in text2


# ─── User info / preferences / projects ─────────────────────────────────

class TestUserInfo:
    def test_set_user_info_upserts(self, brain: Brain):
        brain.set_user_info("name", "Alex")
        brain.set_user_info("role", "developer")
        text = (brain._brain_dir / "User.md").read_text(encoding="utf-8")
        assert "- name: Alex" in text
        assert "- role: developer" in text
        # Upsert same key replaces, does not duplicate
        brain.set_user_info("name", "Alexandr")
        text2 = (brain._brain_dir / "User.md").read_text(encoding="utf-8")
        assert text2.count("- name:") == 1
        assert "- name: Alexandr" in text2

    def test_set_preference(self, brain: Brain):
        brain.set_preference("language", "ru")
        text = (brain._brain_dir / "Preferences.md").read_text(encoding="utf-8")
        assert "- language: ru" in text

    def test_record_project(self, brain: Brain):
        brain.record_project("FOL v2")
        text = (brain._brain_dir / "Projects.md").read_text(encoding="utf-8")
        assert "## FOL v2" in text
        assert "In progress" in text


# ─── Context assembly ────────────────────────────────────────────────────

class TestContext:
    def test_empty_brain_returns_empty(self, brain: Brain):
        ctx = brain.get_brain_context()
        assert isinstance(ctx, str)
        # No meaningful content yet (only headers) → empty-ish
        assert ctx == ""

    def test_context_contains_user_and_recent_work(self, brain: Brain):
        brain.set_user_info("name", "Alex")
        brain.record_turn("Открой Safari", "Открыл Safari.")
        brain.record_turn("Найди новости", "Нашёл новости.")
        ctx = brain.get_brain_context()
        assert "Alex" in ctx
        assert "Открой Safari" in ctx
        assert "Открыл Safari" in ctx

    def test_context_respects_max_chars(self, brain: Brain):
        for i in range(30):
            brain.record_turn(f"вопрос {i}", "ответ " * 20)
        ctx = brain.get_brain_context(max_chars=500)
        assert len(ctx) <= 500 + 50  # allowance for the tail slicing
        assert "вопрос 29" in ctx  # newest entries kept

    def test_profile_kept_when_over_budget(self, brain: Brain):
        """The user profile (first section) must survive truncation — the
        volatile activity tail is cut first."""
        brain.set_user_info("name", "Алекс")
        for i in range(40):
            brain.record_turn(f"вопрос {i}", "ответ " * 30)
        ctx = brain.get_brain_context(max_chars=400)
        assert "Алекс" in ctx, "profile must not be dropped by truncation"

    def test_slugify(self):
        assert _slugify("Hello World!") == "hello-world"
        assert _slugify("  A--B  ") == "a-b"


# ─── Work-log queries ──────────────────────────────────────────────────

class TestWorkLogQueries:
    def test_work_log_for_date_returns_entries(self, brain: Brain, today: str):
        brain.record_turn("Открой Safari", "Открыл Safari.")
        entries = brain.work_log_for_date(today)
        assert len(entries) == 1
        assert "Открой Safari" in entries[0]
        assert "Открыл Safari" in entries[0]

    def test_work_log_for_date_empty_for_other_day(self, brain: Brain):
        assert brain.work_log_for_date("2000-01-01") == []

    def test_recent_work_returns_newest_first(self, brain: Brain, today: str):
        brain.record_turn("первый", "ответ 1")
        brain.record_turn("второй", "ответ 2")
        recent = brain.recent_work(days=1, limit=10)
        assert len(recent) == 2
        assert recent[0]["date"] == today
        assert "второй" in recent[0]["entry"]  # newest first

    def test_search_work_log_finds_match(self, brain: Brain):
        brain.record_turn("Открой Safari", "Открыл Safari.")
        brain.record_turn("Найди новости про OpenAI", "Нашёл новости.")
        matches = brain.search_work_log("openai")
        assert len(matches) == 1
        assert "новости" in matches[0]["entry"]

    def test_search_case_insensitive_and_no_match(self, brain: Brain):
        brain.record_turn("Привет", "Привет!")
        assert brain.search_work_log("ПРИВЕТ")  # case-insensitive
        assert brain.search_work_log("чего-то нет такого") == []
        assert brain.search_work_log("   ") == []  # empty query

    def test_get_projects_lists_titles(self, brain: Brain):
        brain.record_project("FOL v2")
        brain.record_project("Поступление 2027")
        projects = brain.get_projects()
        assert "FOL v2" in projects
        assert "Поступление 2027" in projects


# ─── Daily summary ──────────────────────────────────────────────────────

class TestDailySummary:
    def test_empty_day_returns_empty(self, brain: Brain, today: str):
        assert brain.write_daily_summary(today) == ""

    def test_writes_summary_file(self, brain: Brain, today: str, monkeypatch):
        brain.record_turn("Открой Safari", "Открыл Safari.")
        brain.record_turn("Найди новости", "Нашёл новости об OpenAI.")
        # Avoid real Obsidian REST call in tests.
        monkeypatch.setattr(
            "modules.memory.brain._append_to_obsidian_daily",
            lambda *a, **k: {"ok": True},
        )
        summary = brain.write_daily_summary(today)
        assert "Итоги дня" in summary
        assert "Открой Safari" in summary
        assert "Нашёл новости" in summary
        # File written under Brain/Daily-Summary/
        f = brain._brain_dir / "Daily-Summary" / f"{today}.md"
        assert f.exists()
        assert "Открой Safari" in f.read_text(encoding="utf-8")

    def test_obsidian_daily_append_attempted(self, brain: Brain, today: str, monkeypatch):
        brain.record_turn("привет", "привет!")
        calls: list[tuple] = []
        monkeypatch.setattr(
            "modules.memory.brain._append_to_obsidian_daily",
            lambda date, content: calls.append(date),
        )
        brain.write_daily_summary(today)
        assert calls, "Obsidian Daily append must be attempted"
        assert calls[0] == today

    def test_append_only_once_per_day(self, brain: Brain, today: str, monkeypatch):
        """Idempotency: a second call (manual command after the evening task,
        or a restart) must NOT append the summary to the Daily note again."""
        brain.record_turn("привет", "привет!")
        calls: list[tuple] = []
        monkeypatch.setattr(
            "modules.memory.brain._append_to_obsidian_daily",
            lambda date, content: calls.append(date),
        )
        brain.write_daily_summary(today)
        brain.write_daily_summary(today)
        assert len(calls) == 1, "second call must not append to Obsidian again"

    def test_obsidian_failure_never_raises(self, brain: Brain, today: str, monkeypatch):
        brain.record_turn("x", "y")
        def _boom(*a, **k):
            raise RuntimeError("Obsidian down")
        monkeypatch.setattr("modules.memory.brain._append_to_obsidian_daily", _boom)
        summary = brain.write_daily_summary(today)
        assert "Итоги дня" in summary  # still returns the summary text

    def test_only_recent_entries_included(self, brain: Brain, today: str):
        for i in range(50):
            brain.record_turn(f"вопрос {i}", f"ответ {i}")
        import unittest.mock as mock
        with mock.patch(
            "modules.memory.brain._append_to_obsidian_daily", return_value={"ok": True}
        ):
            summary = brain.write_daily_summary(today)
        assert "вопрос 0" not in summary  # oldest dropped (limit 40)
        assert "вопрос 49" in summary


# ─── Stats & summary ─────────────────────────────────────────────────────

class TestStats:
    def test_stats_counts(self, brain: Brain):
        brain.set_user_info("name", "Alex")
        brain.record_model_change("m1")
        brain.record_turn("x", "y")
        s = brain.get_stats()
        assert s["User"] == 1
        assert s["Model-Log"] == 1
        assert s["work_log_entries"] >= 1
        assert s["work_log_files"] >= 1

    def test_summary_is_human_readable(self, brain: Brain):
        brain.record_model_change("gpt-4o-mini")
        brain.record_turn("привет", "привет!")
        summary = brain.summary()
        assert "Freebuff Brain" in summary
        assert "Model history" in summary
        assert "Work log" in summary


# ─── Resilience ──────────────────────────────────────────────────────────

class TestResilience:
    def test_init_never_raises(self, tmp_path: Path):
        # unwritable path should degrade, not raise
        locked = tmp_path / "root"
        locked.write_text("file", encoding="utf-8")  # file where dir expected
        brain = Brain(vault_path=locked / "sub")  # should not raise
        assert brain._brain_dir is not None

    def test_missing_vault_dir_is_created(self, tmp_path: Path):
        brain = Brain(vault_path=tmp_path / "deep" / "nested" / "vault")
        assert brain._brain_dir.exists()
