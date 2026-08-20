"""Tests for MemoryConsolidator and ConsolidationScheduler."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from modules.memory.consolidation import ConsolidationResult, MemoryConsolidator


# ---------------------------------------------------------------------------
# Mock Brain
# ---------------------------------------------------------------------------

class MockBrain:
    """Minimal Brain-like object for testing consolidation."""

    def __init__(self, work_dir: Path) -> None:
        self._brain_dir = work_dir
        self._work_dir = work_dir / "Work-Log"
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, str] = {}

    def _read(self, name: str) -> str:
        path = self._brain_dir / name
        if path.exists():
            return path.read_text(encoding="utf-8")
        return self._files.get(name, "")

    def _write(self, name: str, content: str) -> bool:
        path = self._brain_dir / name
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self._files[name] = content
            return True
        except Exception:
            return False

    def _work_log_entries(self, date: str) -> list[str]:
        log_path = self._work_dir / f"{date}.md"
        if not log_path.exists():
            return []
        text = log_path.read_text(encoding="utf-8")
        entries = []
        current = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("-"):
                if current:
                    entries.append(" ".join(current))
                current = [line.lstrip("- ")]
            elif current:
                current.append(line)
        if current:
            entries.append(" ".join(current))
        return entries


# ---------------------------------------------------------------------------
# MemoryConsolidator Tests
# ---------------------------------------------------------------------------

class TestMemoryConsolidator:
    def test_consolidate_empty_log(self):
        """No entries → no consolidation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            consolidator = MemoryConsolidator(brain=brain)
            result = _run_sync(consolidator.consolidate("2026-01-01"))
            assert result.lessons == []
            assert result.facts_learned == []

    def test_consolidate_with_entries_no_llm(self):
        """Basic keyword extraction when LLM is unavailable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            # Write work log
            log_path = brain._work_dir / "2026-08-17.md"
            log_path.write_text(
                "# Work Log — 2026-08-17\n\n"
                "- **10:00** [fol] **User:** привет\n"
                "  **FOL:** Привет! Чем займёмся?\n"
                "- **10:05** [fol] **User:** always check tests before commit\n"
                "  **FOL:** Got it. Will always run tests first.\n"
                "- **10:10** [fol] **User:** user prefers dark mode\n"
                "  **FOL:** Noted. Dark mode it is.\n",
                encoding="utf-8",
            )
            consolidator = MemoryConsolidator(brain=brain)
            result = _run_sync(consolidator.consolidate("2026-08-17"))
            # Should extract some lessons/facts via keyword matching
            assert isinstance(result, ConsolidationResult)
            assert result.date == "2026-08-17"

    def test_consolidate_with_llm(self):
        """LLM-based analysis returns structured data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            log_path = brain._work_dir / "2026-08-17.md"
            log_path.write_text(
                "# Work Log — 2026-08-17\n\n"
                "- **10:00** [fol] **User:** напиши код\n"
                "  **FOL:** Код написан.\n",
                encoding="utf-8",
            )

            def mock_llm(prompt: str, system: str) -> str:
                return json.dumps({
                    "lessons": ["Always write tests first"],
                    "facts": ["User speaks Russian"],
                    "preferences": [],
                    "projects": ["FOL project active"],
                    "patterns": [],
                    "summary": "Short coding session.",
                })

            consolidator = MemoryConsolidator(brain=brain, llm_fn=mock_llm)
            result = _run_sync(consolidator.consolidate("2026-08-17"))
            assert result.lessons == ["Always write tests first"]
            assert result.facts_learned == ["User speaks Russian"]
            assert result.project_updates == ["FOL project active"]
            assert result.summary == "Short coding session."

    def test_consolidate_idempotent(self):
        """Second consolidation of same date is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            log_path = brain._work_dir / "2026-08-17.md"
            log_path.write_text("- **10:00** test entry\n", encoding="utf-8")

            consolidator = MemoryConsolidator(brain=brain)
            result1 = _run_sync(consolidator.consolidate("2026-08-17"))
            # Create the marker file (simulating first consolidation)
            consolidated_dir = brain._brain_dir / "Daily-Consolidated"
            consolidated_dir.mkdir(exist_ok=True)
            (consolidated_dir / "2026-08-17.md").write_text("already done")

            result2 = _run_sync(consolidator.consolidate("2026-08-17"))
            # Second call should be skipped (no new lessons)
            assert result2.lessons == []

    def test_write_lessons_dedup(self):
        """Lessons are deduplicated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            # Write existing lesson
            brain._write("Lessons.md", "# Lessons\n\n- **2026-08-16** Always check tests\n")

            consolidator = MemoryConsolidator(brain=brain)
            # Write duplicate + new lesson
            consolidator._write_lessons(
                ["Always check tests", "New lesson learned"],
                "2026-08-17",
            )
            content = brain._read("Lessons.md")
            assert content.count("Always check tests") == 1  # deduped
            assert "New lesson learned" in content

    def test_get_lessons(self):
        """Read lessons from Brain/Lessons.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            brain._write(
                "Lessons.md",
                "# Lessons\n\n"
                "- **2026-08-16** Lesson one\n"
                "- **2026-08-16** Lesson two\n"
                "- **2026-08-17** Lesson three\n",
            )
            consolidator = MemoryConsolidator(brain=brain)
            lessons = consolidator.get_lessons(limit=2)
            assert len(lessons) == 2
            assert "Lesson three" in lessons[-1]

    def test_get_relevant_lessons(self):
        """Relevant lessons matched by keyword overlap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            brain._write(
                "Lessons.md",
                "# Lessons\n\n"
                "- Always run tests before commit\n"
                "- User prefers dark mode in editor\n"
                "- Check browser cookies before navigation\n",
            )
            consolidator = MemoryConsolidator(brain=brain)
            relevant = consolidator.get_relevant_lessons("run tests before push")
            assert len(relevant) > 0
            assert "tests" in relevant[0].lower() or "tests" in relevant[-1].lower()

    def test_no_brain(self):
        """Consolidator works without Brain (graceful degradation)."""
        consolidator = MemoryConsolidator(brain=None)
        result = _run_sync(consolidator.consolidate("2026-08-17"))
        assert result.lessons == []
        assert consolidator.get_lessons() == []


# ---------------------------------------------------------------------------
# ConsolidationScheduler Tests
# ---------------------------------------------------------------------------

class TestConsolidationScheduler:
    def test_status(self):
        """Status returns correct dict."""
        from modules.memory.scheduler import ConsolidationScheduler

        consolidator = MemoryConsolidator(brain=None)
        scheduler = ConsolidationScheduler(consolidator=consolidator, enabled=False)
        status = scheduler.status()
        assert status["enabled"] is False
        assert status["running"] is False
        assert status["turn_count"] == 0

    def test_record_turn(self):
        """Turn counting works."""
        from modules.memory.scheduler import ConsolidationScheduler

        consolidator = MemoryConsolidator(brain=None)
        scheduler = ConsolidationScheduler(
            consolidator=consolidator,
            turns_before_auto=5,
            enabled=False,
        )
        for _ in range(4):
            scheduler.record_turn()
        assert scheduler._turn_count == 4
        scheduler.record_turn()
        assert scheduler._turn_count == 0  # reset after threshold

    def test_consolidate_now(self):
        """Manual consolidation triggers correctly."""
        from modules.memory.scheduler import ConsolidationScheduler

        with tempfile.TemporaryDirectory() as tmpdir:
            brain = MockBrain(Path(tmpdir))
            # Write yesterday's log
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            log_path = brain._work_dir / f"{yesterday}.md"
            log_path.write_text(f"- **10:00** test entry for {yesterday}\n", encoding="utf-8")

            consolidator = MemoryConsolidator(brain=brain)
            scheduler = ConsolidationScheduler(consolidator=consolidator, enabled=False)
            result = _run_sync(scheduler.consolidate_now())
            assert isinstance(result, ConsolidationResult)
            assert result.date == yesterday


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_sync(coro):
    """Run an async function synchronously."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # We're inside an async context — use a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)
