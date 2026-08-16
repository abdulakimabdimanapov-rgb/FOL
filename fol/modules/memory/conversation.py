"""Conversation history — stores and retrieves dialog turns."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from config.constants import FOL_DIR

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """A single conversation turn."""

    id: UUID = field(default_factory=uuid4)
    user_input: str = ""
    assistant_response: str = ""
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_input": self.user_input,
            "assistant_response": self.assistant_response,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationTurn:
        return cls(
            id=UUID(data["id"]) if "id" in data else uuid4(),
            user_input=data.get("user_input", ""),
            assistant_response=data.get("assistant_response", ""),
            timestamp=data.get("timestamp", 0.0),
            metadata=data.get("metadata", {}),
        )


class ConversationHistory:
    """Manages conversation history persistence."""

    def __init__(self, history_path: Path | None = None, max_turns: int = 1000) -> None:
        self._path = history_path or (FOL_DIR / "conversation_history.jsonl")
        self._max_turns = max_turns
        self._turns: list[ConversationTurn] = []

    async def initialize(self) -> None:
        """Load existing history from disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                content = self._path.read_text(encoding="utf-8")
                for line in content.strip().split("\n"):
                    if line.strip():
                        self._turns.append(ConversationTurn.from_dict(json.loads(line)))
                logger.info("Conversation history loaded", turns=len(self._turns))
            except Exception as exc:
                logger.error("Failed to load history", error=str(exc))

    async def shutdown(self) -> None:
        """Save history to disk."""
        await self.save()

    async def add_turn(self, user_input: str, assistant_response: str, metadata: dict[str, Any] | None = None) -> ConversationTurn:
        """Add a conversation turn."""
        turn = ConversationTurn(
            user_input=user_input,
            assistant_response=assistant_response,
            metadata=metadata or {},
        )
        self._turns.append(turn)

        # Trim if too many
        if len(self._turns) > self._max_turns:
            self._turns = self._turns[-self._max_turns:]

        # Append to file
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn.to_dict()) + "\n")
        except Exception as exc:
            logger.error("Failed to append turn", error=str(exc))

        return turn

    async def get_recent(self, n: int = 20) -> list[ConversationTurn]:
        """Get recent conversation turns."""
        return self._turns[-n:]

    async def search(self, query: str, limit: int = 10) -> list[ConversationTurn]:
        """Search turns by content."""
        query_lower = query.lower()
        results = []
        for turn in reversed(self._turns):
            if query_lower in turn.user_input.lower() or query_lower in turn.assistant_response.lower():
                results.append(turn)
                if len(results) >= limit:
                    break
        return results

    async def save(self) -> None:
        """Save all turns to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                for turn in self._turns:
                    f.write(json.dumps(turn.to_dict()) + "\n")
            logger.debug("History saved", turns=len(self._turns))
        except Exception as exc:
            logger.error("Failed to save history", error=str(exc))

    async def clear(self) -> None:
        """Clear all history."""
        self._turns.clear()
        if self._path.exists():
            self._path.unlink()

    @property
    def turn_count(self) -> int:
        return len(self._turns)
