"""Tokenizer utility for LLM token counting."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TokenCounter:
    """Simple token counter for LLM messages."""

    def __init__(self, chars_per_token: float = 4.0) -> None:
        """Initialize token counter.

        Args:
            chars_per_token: Approximate characters per token (default ~4 for English).
        """
        self._chars_per_token = chars_per_token

    def count(self, text: str) -> int:
        """Estimate token count for text."""
        return max(1, int(len(text) / self._chars_per_token))

    def count_messages(self, messages: list[dict[str, str]]) -> int:
        """Estimate total token count for a list of messages."""
        total = 0
        for msg in messages:
            # Add overhead for role formatting
            total += 4  # role formatting overhead
            total += self.count(msg.get("content", ""))
        return total

    def truncate_messages(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4000,
    ) -> list[dict[str, str]]:
        """Truncate messages to fit within token budget.

        Keeps the system message and the most recent messages.
        """
        if not messages:
            return []

        system_msgs = [m for m in messages if m.get("role") == "system"]
        other_msgs = [m for m in messages if m.get("role") != "system"]

        system_tokens = sum(self.count(m.get("content", "")) for m in system_msgs)
        budget = max_tokens - system_tokens - len(system_msgs) * 4

        if budget <= 0:
            return system_msgs

        # Keep most recent messages first
        kept = []
        used = 0
        for msg in reversed(other_msgs):
            msg_tokens = self.count(msg.get("content", "")) + 4
            if used + msg_tokens > budget:
                break
            kept.insert(0, msg)
            used += msg_tokens

        return system_msgs + kept


def estimate_tokens(text: str) -> int:
    """Quick token estimation for a string."""
    return max(1, len(text) // 4)
