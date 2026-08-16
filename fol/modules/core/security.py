"""Security utilities — command validation, input sanitization."""

from __future__ import annotations

import logging
import re
from typing import Final

logger = logging.getLogger(__name__)

BLOCKED_COMMANDS: Final[set[str]] = {
    "sudo", "rm -rf /", "dd", "mkfs", "chmod 777",
    "passwd", "kill -9", ":(){ :|:& };:", "shutdown",
    "halt", "init 0", "init 6",
}

BLOCKED_PATTERNS: Final[list[str]] = [
    r"rm\s+(-rf|/\s)",
    r">\s+/dev/(sda|sdb)",
    r"(wget|curl)\s+.*\|.*sh",
    r"python\s*-c\s*.*import\s+os.*system",
    r"eval\s*\(",
    r"exec\s*\(",
]

SENSITIVE_PATTERNS: Final[list[str]] = [
    r"(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+",
    r"sk-[a-zA-Z0-9]+",
    r"ghp_[a-zA-Z0-9]+",
]


class SecurityValidator:
    """Validates commands and inputs for security."""

    @classmethod
    def validate_command(cls, command: str) -> tuple[bool, str]:
        """Validate a shell command. Returns (is_safe, reason)."""
        cmd_lower = command.strip().lower()

        # Check blocked commands
        for blocked in BLOCKED_COMMANDS:
            if cmd_lower.startswith(blocked):
                return False, f"Blocked command: {blocked}"

        # Check blocked patterns
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command):
                return False, f"Blocked pattern: {pattern}"

        return True, "OK"

    @classmethod
    def sanitize_input(cls, text: str) -> str:
        """Sanitize user input."""
        # Remove potential injection characters
        text = text.replace("\x00", "")
        # Limit length
        if len(text) > 10000:
            text = text[:10000]
        return text.strip()

    @classmethod
    def contains_secrets(cls, text: str) -> bool:
        """Check if text contains potential secrets."""
        for pattern in SENSITIVE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    @classmethod
    def mask_secrets(cls, text: str) -> str:
        """Mask potential secrets in text."""
        for pattern in SENSITIVE_PATTERNS:
            text = re.sub(pattern, "[REDACTED]", text, flags=re.IGNORECASE)
        return text
