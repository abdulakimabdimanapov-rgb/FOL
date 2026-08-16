"""Episodic memory — stores what happened when."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from config.constants import FOL_DIR

logger = logging.getLogger(__name__)


@dataclass
class Episode:
    """A single episodic memory."""

    id: UUID = field(default_factory=uuid4)
    event: str = ""
    context: str = ""
    timestamp: float = 0.0
    importance: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "event": self.event,
            "context": self.context,
            "timestamp": self.timestamp,
            "importance": self.importance,
            "metadata": self.metadata,
        }


class EpisodicMemory:
    """Stores episodic memories — what happened and when."""

    def __init__(self, memory_path: Path | None = None, max_episodes: int = 5000) -> None:
        self._path = memory_path or (FOL_DIR / "episodic_memory.jsonl")
        self._max = max_episodes
        self._episodes: list[Episode] = []

    async def initialize(self) -> None:
        """Load episodes from disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                content = self._path.read_text(encoding="utf-8")
                for line in content.strip().split("\n"):
                    if line.strip():
                        data = json.loads(line)
                        self._episodes.append(Episode(
                            id=UUID(data["id"]),
                            event=data["event"],
                            context=data.get("context", ""),
                            timestamp=data["timestamp"],
                            importance=data.get("importance", 1.0),
                            metadata=data.get("metadata", {}),
                        ))
                logger.info("Episodic memory loaded", episodes=len(self._episodes))
            except Exception as exc:
                logger.error("Failed to load episodic memory", error=str(exc))

    async def shutdown(self) -> None:
        """Save episodes to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                for ep in self._episodes:
                    f.write(json.dumps(ep.to_dict()) + "\n")
        except Exception as exc:
            logger.error("Failed to save episodic memory", error=str(exc))

    async def record(self, event: str, context: str = "", importance: float = 1.0, metadata: dict[str, Any] | None = None) -> Episode:
        """Record a new episode."""
        episode = Episode(
            event=event,
            context=context,
            importance=importance,
            metadata=metadata or {},
        )
        self._episodes.append(episode)

        if len(self._episodes) > self._max:
            self._episodes = self._episodes[-self._max:]

        return episode

    async def search(self, query: str, limit: int = 10) -> list[Episode]:
        """Search episodes by content."""
        query_lower = query.lower()
        results = []
        for ep in reversed(self._episodes):
            if query_lower in ep.event.lower() or query_lower in ep.context.lower():
                results.append(ep)
                if len(results) >= limit:
                    break
        return results

    async def get_recent(self, n: int = 20) -> list[Episode]:
        """Get recent episodes."""
        return self._episodes[-n:]

    async def get_by_time_range(self, start: float, end: float) -> list[Episode]:
        """Get episodes within a time range."""
        return [ep for ep in self._episodes if start <= ep.timestamp <= end]

    @property
    def episode_count(self) -> int:
        return len(self._episodes)
