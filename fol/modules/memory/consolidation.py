"""Memory Consolidation — LLM-based synthesis of daily work logs.

Runs as a background process (or on-demand) to analyze work-log entries
and extract structured knowledge: lessons learned, user preferences
discovered, project updates, and recurring patterns.

The consolidator reads Work-Log/YYYY-MM-DD.md files, sends them to the
LLM for analysis, and writes the results back to the Brain vault:

  Brain/
    Lessons.md              — reusable lessons (auto-updated)
    Daily-Consolidated/     — LLM-synthesized daily summaries
      YYYY-MM-DD.md         — structured analysis of the day

Architecture:
    MemoryConsolidator
     ├── reads Work-Log entries (from Brain)
     ├── LLM analysis (via llm_bridge or direct router)
     ├── writes Lessons.md (deduplicated, timestamped)
     ├── writes Daily-Consolidated/ (structured summary)
     └── updates User.md / Preferences.md (when new info found)

The consolidator NEVER raises — all writes are best-effort.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ConsolidationResult:
    """Result of consolidating a day's work logs."""
    date: str
    lessons: list[str] = field(default_factory=list)
    facts_learned: list[str] = field(default_factory=list)
    preferences_discovered: list[str] = field(default_factory=list)
    project_updates: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    summary: str = ""
    raw_llm_response: str = ""


# ---------------------------------------------------------------------------
# LLM prompt for consolidation
# ---------------------------------------------------------------------------

_CONSOLIDATION_PROMPT = """You are a memory consolidation engine for a personal AI assistant named FOL.

Analyze the following work-log entries from a single day and extract structured knowledge.

For each entry, identify:
1. **Lessons learned** — reusable insights, best practices, things to remember for next time
2. **Facts learned** — new information about the user, their projects, or their environment
3. **Preferences discovered** — how the user likes to work, communicate, or be addressed
4. **Project updates** — progress on ongoing projects, new projects started, milestones reached
5. **Patterns** — recurring behaviors, time-of-day habits, frequent requests

RULES:
- Be concise: each item should be ONE short sentence
- Only extract genuinely useful information (not trivial conversation)
- Lessons should be actionable ("Always check X before Y")
- Facts should be specific ("User prefers dark mode in VS Code")
- If nothing notable happened, return empty lists

OUTPUT FORMAT (JSON — use double braces {{}} for literal braces):
{{
  "lessons": ["lesson 1", "lesson 2"],
  "facts": ["fact 1", "fact 2"],
  "preferences": ["pref 1", "pref 2"],
  "projects": ["project update 1"],
  "patterns": ["pattern 1"],
  "summary": "One-paragraph summary of the day"
}}

Work-log entries:
---
{entries}
---

Analyze and return the JSON above. Return ONLY the JSON, no explanation."""


# ---------------------------------------------------------------------------
# MemoryConsolidator
# ---------------------------------------------------------------------------

class MemoryConsolidator:
    """LLM-based synthesis of daily work logs into structured memory.

    Usage:
        consolidator = MemoryConsolidator(brain=brain, llm_fn=my_llm_call)
        result = await consolidator.consolidate("2026-08-17")
        # result.lessons, result.facts_learned, etc. are populated
        # Brain/Lessons.md and Daily-Consolidated/ are updated
    """

    def __init__(
        self,
        brain: Any | None = None,
        llm_fn: Callable[[str, str], str] | None = None,
    ) -> None:
        """
        Args:
            brain: Brain instance (for reading work logs, writing lessons)
            llm_fn: Sync function (prompt, system) -> str. If None, uses
                    basic keyword extraction (no LLM).
        """
        self._brain = brain
        self._llm_fn = llm_fn
        self._consolidated_dir: Path | None = None
        if brain:
            self._consolidated_dir = brain._brain_dir / "Daily-Consolidated"
            self._consolidated_dir.mkdir(exist_ok=True)

    # -- Public API ----------------------------------------------------------

    async def consolidate(self, date: str | None = None) -> ConsolidationResult:
        """Consolidate a single day's work log.

        Reads Work-Log/YYYY-MM-DD.md, analyzes via LLM, writes results.
        Returns the ConsolidationResult. Best-effort — never raises.
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        result = ConsolidationResult(date=date)

        # 1. Read work log entries
        entries = self._read_entries(date)
        if not entries:
            logger.debug("No work-log entries for %s — skipping consolidation", date)
            return result

        # 2. Skip if already consolidated (idempotent)
        if self._is_already_consolidated(date):
            logger.debug("Already consolidated %s — skipping", date)
            return result

        # 3. LLM analysis
        if self._llm_fn:
            parsed = await self._analyze_with_llm(entries)
        else:
            parsed = self._analyze_without_llm(entries)

        result.lessons = parsed.get("lessons", [])
        result.facts_learned = parsed.get("facts", [])
        result.preferences_discovered = parsed.get("preferences", [])
        result.project_updates = parsed.get("projects", [])
        result.patterns = parsed.get("patterns", [])
        result.summary = parsed.get("summary", "")
        result.raw_llm_response = parsed.get("_raw", "")

        # 4. Write results
        self._write_lessons(result.lessons, date)
        self._write_consolidated_summary(date, result)
        self._update_user_profile(result.facts_learned)
        self._update_preferences(result.preferences_discovered)

        logger.info(
            "Consolidated %s: %d lessons, %d facts, %d prefs, %d projects, %d patterns",
            date,
            len(result.lessons),
            len(result.facts_learned),
            len(result.preferences_discovered),
            len(result.project_updates),
            len(result.patterns),
        )
        return result

    async def consolidate_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[ConsolidationResult]:
        """Consolidate a range of days."""
        results = []
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        current = start
        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            result = await self.consolidate(date_str)
            if result.lessons or result.facts_learned:
                results.append(result)
            current += timedelta(days=1)
        return results

    async def consolidate_yesterday(self) -> ConsolidationResult:
        """Consolidate yesterday's work log (convenience method)."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        return await self.consolidate(yesterday)

    def get_lessons(self, limit: int = 20) -> list[str]:
        """Read the most recent lessons from Brain/Lessons.md."""
        if not self._brain:
            return []
        content = self._brain._read("Lessons.md")
        lines = [
            l.strip().lstrip("- ")
            for l in content.splitlines()
            if l.strip().startswith("-")
        ]
        return lines[-limit:]

    def get_relevant_lessons(self, task: str, limit: int = 5) -> list[str]:
        """Retrieve lessons relevant to a task (simple keyword matching)."""
        all_lessons = self.get_lessons(limit=100)
        if not all_lessons or not task:
            return []

        task_words = set(task.lower().split())
        scored: list[tuple[float, str]] = []
        for lesson in all_lessons:
            lesson_words = set(lesson.lower().split())
            overlap = len(task_words & lesson_words)
            scored.append((overlap, lesson))

        scored.sort(key=lambda x: -x[0])
        return [lesson for _, lesson in scored[:limit] if scored[0][0] > 0]

    # -- Private: LLM analysis ----------------------------------------------

    async def _analyze_with_llm(self, entries: list[str]) -> dict:
        """Send entries to LLM for structured analysis."""
        entries_text = "\n".join(f"- {e}" for e in entries[:60])  # cap at 60 entries
        prompt = _CONSOLIDATION_PROMPT.format(entries=entries_text)

        try:
            raw = self._llm_fn(prompt, "You are a memory consolidation engine.")
            return self._parse_llm_response(raw)
        except Exception as exc:
            logger.warning("LLM consolidation failed: %s — falling back to keyword analysis", exc)
            return self._analyze_without_llm(entries)

    def _parse_llm_response(self, raw: str) -> dict:
        """Parse LLM JSON response into structured dict."""
        import json

        # Try to extract JSON from the response
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        # Find first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]

        try:
            parsed = json.loads(text)
            parsed["_raw"] = raw
            return parsed
        except (json.JSONDecodeError, ValueError):
            logger.debug("Failed to parse LLM response as JSON: %.200s", raw)
            return {"_raw": raw}

    # -- Private: keyword analysis (no LLM) ---------------------------------

    def _analyze_without_llm(self, entries: list[str]) -> dict:
        """Basic keyword extraction when LLM is unavailable."""
        lessons = []
        facts = []
        patterns = []

        for entry in entries:
            lower = entry.lower()
            # Lessons: look for "always", "never", "remember", "lesson"
            if any(w in lower for w in ("always", "never", "remember", "lesson", "tip")):
                lessons.append(entry[:150])
            # Facts: look for "is a", "uses", "prefers", "works at"
            if any(w in lower for w in ("is a", "uses", "prefers", "works at", "name is")):
                facts.append(entry[:150])
            # Patterns: look for "usually", "often", "every time"
            if any(w in lower for w in ("usually", "often", "every time", "always does")):
                patterns.append(entry[:150])

        summary = f"Analyzed {len(entries)} entries. Found {len(lessons)} lessons, {len(facts)} facts."

        return {
            "lessons": lessons[:10],
            "facts": facts[:10],
            "preferences": [],
            "projects": [],
            "patterns": patterns[:10],
            "summary": summary,
        }

    # -- Private: reading entries --------------------------------------------

    def _read_entries(self, date: str) -> list[str]:
        """Read parsed entries from Brain/Work-Log/YYYY-MM-DD.md."""
        if not self._brain:
            return []
        return self._brain._work_log_entries(date)

    def _is_already_consolidated(self, date: str) -> bool:
        """Check if this date was already consolidated."""
        if not self._consolidated_dir:
            return False
        marker = self._consolidated_dir / f"{date}.md"
        return marker.exists()

    # -- Private: writing results --------------------------------------------

    def _write_lessons(self, lessons: list[str], date: str) -> None:
        """Append new lessons to Brain/Lessons.md (deduplicated)."""
        if not lessons or not self._brain:
            return

        content = self._brain._read("Lessons.md")
        # Extract existing lesson text (strip date prefix and bullet)
        existing_lower = set()
        for l in content.splitlines():
            if l.strip().startswith("-"):
                # Strip "- " prefix and optional "**date** " prefix
                text = l.strip().lstrip("- ")
                text = re.sub(r"^\*\*\d{4}-\d{2}-\d{2}\*\*\s*", "", text)
                existing_lower.add(text.strip().lower())

        new_lines = []
        for lesson in lessons:
            normalized = lesson.strip().lower()
            if normalized not in existing_lower:
                new_lines.append(f"- **{date}** {lesson.strip()}")
                existing_lower.add(normalized)

        if new_lines:
            content = content.rstrip() + "\n" + "\n".join(new_lines) + "\n"
            self._brain._write("Lessons.md", content)
            logger.info("Added %d new lessons to Brain/Lessons.md", len(new_lines))

    def _write_consolidated_summary(self, date: str, result: ConsolidationResult) -> None:
        """Write the full consolidated summary to Daily-Consolidated/YYYY-MM-DD.md."""
        if not self._consolidated_dir:
            return

        sections = [f"# Consolidated Memory — {date}\n"]

        if result.summary:
            sections.append(f"## Summary\n\n{result.summary}\n")

        if result.lessons:
            sections.append("## 🎓 Lessons Learned\n")
            for l in result.lessons:
                sections.append(f"- {l}")
            sections.append("")

        if result.facts_learned:
            sections.append("## 📚 Facts Learned\n")
            for f in result.facts_learned:
                sections.append(f"- {f}")
            sections.append("")

        if result.preferences_discovered:
            sections.append("## ⚙️ Preferences Discovered\n")
            for p in result.preferences_discovered:
                sections.append(f"- {p}")
            sections.append("")

        if result.project_updates:
            sections.append("## 📋 Project Updates\n")
            for p in result.project_updates:
                sections.append(f"- {p}")
            sections.append("")

        if result.patterns:
            sections.append("## 🔄 Patterns\n")
            for p in result.patterns:
                sections.append(f"- {p}")
            sections.append("")

        path = self._consolidated_dir / f"{date}.md"
        try:
            path.write_text("\n".join(sections), encoding="utf-8")
        except Exception as exc:
            logger.debug("Failed to write consolidated summary: %s", exc)

    def _update_user_profile(self, facts: list[str]) -> None:
        """Update Brain/User.md with new facts about the user."""
        if not facts or not self._brain:
            return

        content = self._brain._read("User.md")
        existing_lower = content.lower()

        new_facts = []
        for fact in facts:
            # Only add if not already present (simple dedup)
            fact_lower = fact.strip().lower()
            if fact_lower not in existing_lower and len(fact_lower) > 10:
                new_facts.append(fact.strip())

        if new_facts:
            # Add under ## Discovered section
            if "## Discovered" in content:
                lines = content.split("\n")
                idx = lines.index("## Discovered") + 1
                for f in new_facts:
                    lines.insert(idx, f"- {f}")
                    idx += 1
                content = "\n".join(lines)
            else:
                content = content.rstrip() + "\n\n## Discovered\n"
                for f in new_facts:
                    content += f"- {f}\n"
            self._brain._write("User.md", content)
            logger.info("Added %d facts to Brain/User.md", len(new_facts))

    def _update_preferences(self, prefs: list[str]) -> None:
        """Update Brain/Preferences.md with new preferences."""
        if not prefs or not self._brain:
            return

        content = self._brain._read("Preferences.md")
        existing_lower = content.lower()

        new_prefs = []
        for pref in prefs:
            pref_lower = pref.strip().lower()
            if pref_lower not in existing_lower and len(pref_lower) > 5:
                new_prefs.append(pref.strip())

        if new_prefs:
            content = content.rstrip() + "\n"
            for p in new_prefs:
                content += f"- {p}\n"
            self._brain._write("Preferences.md", content)
            logger.info("Added %d preferences to Brain/Preferences.md", len(new_prefs))


__all__ = ["MemoryConsolidator", "ConsolidationResult"]
