"""Behavioral learner — learns user patterns, preferences, and adapts behavior."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.constants import FOL_DIR

logger = logging.getLogger(__name__)


@dataclass
class UserPattern:
    """A learned pattern from user behavior."""

    pattern_type: str = ""   # "command_freq", "time_preference", "topic_interest", "workflow", "language"
    key: str = ""
    value: Any = None
    count: int = 1
    confidence: float = 0.5
    last_seen: float = 0.0
    avg_time_of_day: float = -1.0  # Hour of day when this pattern typically occurs

    def __post_init__(self) -> None:
        if self.last_seen == 0.0:
            self.last_seen = time.time()


class BehavioralLearner:
    """Learns user patterns and provides behavioral context."""

    def __init__(self, data_path: Path | None = None) -> None:
        self._path = data_path or (FOL_DIR / "behavior_patterns.json")
        self._patterns: dict[str, UserPattern] = {}
        self._session_commands: list[str] = []
        self._session_topics: dict[str, int] = {}
        self._session_start: float = time.time()
        self._interaction_count: int = 0
        self._preferred_language: str = "en"
        self._language_votes: dict[str, int] = {}

    async def initialize(self) -> None:
        """Load patterns from disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for key, pdata in data.items():
                    self._patterns[key] = UserPattern(
                        pattern_type=pdata.get("pattern_type", ""),
                        key=pdata.get("key", key),
                        value=pdata.get("value"),
                        count=pdata.get("count", 1),
                        confidence=pdata.get("confidence", 0.5),
                        last_seen=pdata.get("last_seen", 0.0),
                        avg_time_of_day=pdata.get("avg_time_of_day", -1.0),
                    )
                self._interaction_count = data.get("_meta", {}).get("interaction_count", 0)
                self._preferred_language = data.get("_meta", {}).get("preferred_language", "en")
                logger.info("Behavioral patterns loaded", count=len(self._patterns))
            except Exception as exc:
                logger.error("Failed to load patterns: %s", exc)

    async def shutdown(self) -> None:
        """Save patterns to disk."""
        try:
            data = {"_meta": {
                "interaction_count": self._interaction_count,
                "preferred_language": self._preferred_language,
            }}
            for key, p in self._patterns.items():
                data[key] = {
                    "pattern_type": p.pattern_type,
                    "key": p.key,
                    "value": p.value,
                    "count": p.count,
                    "confidence": p.confidence,
                    "last_seen": p.last_seen,
                    "avg_time_of_day": p.avg_time_of_day,
                }
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save patterns: %s", exc)

    async def observe_command(self, command: str) -> None:
        """Observe a user command and learn from it."""
        self._session_commands.append(command)
        self._interaction_count += 1
        lower = command.lower().strip()
        now = time.time()
        hour = (now % 86400) / 3600  # Current hour of day

        # Detect language
        has_cyrillic = any(ord(c) >= 0x400 and ord(c) <= 0x4FF for c in command)
        lang = "ru" if has_cyrillic else "en"
        self._language_votes[lang] = self._language_votes.get(lang, 0) + 1
        if sum(self._language_votes.values()) >= 3:
            self._preferred_language = max(self._language_votes, key=self._language_votes.get)

        # Track command frequency with time awareness
        freq_key = f"cmd_freq:{lower}"
        if freq_key in self._patterns:
            p = self._patterns[freq_key]
            p.count += 1
            p.confidence = min(0.95, 0.5 + p.count * 0.05)
            p.last_seen = now
            # Update average time of day
            if p.avg_time_of_day < 0:
                p.avg_time_of_day = hour
            else:
                p.avg_time_of_day = (p.avg_time_of_day + hour) / 2
        else:
            self._patterns[freq_key] = UserPattern(
                pattern_type="command_freq",
                key=lower,
                count=1,
                avg_time_of_day=hour,
            )

        # Track topic interests
        words = lower.split()
        for word in words:
            if len(word) > 3 and word.isalpha():
                topic_key = f"topic:{word}"
                if topic_key in self._patterns:
                    self._patterns[topic_key].count += 1
                else:
                    self._patterns[topic_key] = UserPattern(
                        pattern_type="topic_interest",
                        key=word,
                        count=1,
                    )
                self._session_topics[word] = self._session_topics.get(word, 0) + 1

        # Detect workflow patterns (sequences of commands)
        if len(self._session_commands) >= 2:
            prev = self._session_commands[-2].lower().strip()
            workflow_key = f"workflow:{prev}→{lower}"
            if workflow_key in self._patterns:
                self._patterns[workflow_key].count += 1
            else:
                self._patterns[workflow_key] = UserPattern(
                    pattern_type="workflow",
                    key=workflow_key,
                    count=1,
                )

        # Detect time-of-day preferences
        time_bucket = self._get_time_bucket(hour)
        time_key = f"time_pref:{time_bucket}:{lower}"
        if time_key not in self._patterns:
            self._patterns[time_key] = UserPattern(
                pattern_type="time_preference",
                key=time_key,
                value={"hour": hour, "command": lower},
                count=1,
            )
        else:
            self._patterns[time_key].count += 1

    def _get_time_bucket(self, hour: float) -> str:
        """Get a human-readable time bucket."""
        if 5 <= hour < 9:
            return "morning"
        elif 9 <= hour < 12:
            return "late_morning"
        elif 12 <= hour < 14:
            return "midday"
        elif 14 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 22:
            return "evening"
        else:
            return "night"

    async def get_context(self) -> str:
        """Get behavioral context for LLM."""
        lines = []

        # Most frequent commands
        freq_patterns = [
            p for p in self._patterns.values()
            if p.pattern_type == "command_freq" and p.count > 1
        ]
        if freq_patterns:
            freq_patterns.sort(key=lambda p: p.count, reverse=True)
            top_cmds = [f"'{p.key}' ({p.count}x)" for p in freq_patterns[:5]]
            lines.append("Frequent commands: " + ", ".join(top_cmds))

        # Top topics
        if self._session_topics:
            top_topics = sorted(self._session_topics.items(), key=lambda x: x[1], reverse=True)[:5]
            lines.append("Session topics: " + ", ".join(f"{t}({c})" for t, c in top_topics))

        # Workflow patterns
        workflows = [
            p for p in self._patterns.values()
            if p.pattern_type == "workflow" and p.count > 1
        ]
        if workflows:
            workflows.sort(key=lambda p: p.count, reverse=True)
            top_wf = [p.key for p in workflows[:3]]
            lines.append("Common workflows: " + " → ".join(top_wf))

        # Time preferences
        now_hour = (time.time() % 86400) / 3600
        current_bucket = self._get_time_bucket(now_hour)
        time_prefs = [
            p for p in self._patterns.values()
            if p.pattern_type == "time_preference"
            and current_bucket in p.key
            and p.count > 1
        ]
        if time_prefs:
            time_prefs.sort(key=lambda p: p.count, reverse=True)
            cmds = [p.value.get("command", "") for p in time_prefs[:3] if p.value]
            lines.append(f"Typical at this time ({current_bucket}): " + ", ".join(cmds))

        # Language preference
        lines.append(f"Preferred language: {self._preferred_language}")

        # Session stats
        session_min = (time.time() - self._session_start) / 60
        lines.append(f"Session: {len(self._session_commands)} commands, {session_min:.0f} min")

        return "\n".join(lines) if lines else ""

    async def get_frequent_commands(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get the most frequent commands."""
        freq_patterns = [
            p for p in self._patterns.values()
            if p.pattern_type == "command_freq"
        ]
        freq_patterns.sort(key=lambda p: p.count, reverse=True)
        return [(p.key, p.count) for p in freq_patterns[:limit]]

    async def get_interesting_topics(self, limit: int = 10) -> list[tuple[str, int]]:
        """Get most interesting topics."""
        topic_patterns = [
            p for p in self._patterns.values()
            if p.pattern_type == "topic_interest"
        ]
        topic_patterns.sort(key=lambda p: p.count, reverse=True)
        return [(p.key, p.count) for p in topic_patterns[:limit]]

    @property
    def total_patterns(self) -> int:
        return len(self._patterns)

    @property
    def session_commands(self) -> list[str]:
        return self._session_commands.copy()

    @property
    def preferred_language(self) -> str:
        return self._preferred_language
