"""Chat history — simplified for local mode (no Firestore)."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("second-self")

# In-memory chat history (local mode — no Firestore persistence)
_history: dict[str, list[dict[str, Any]]] = {}


def get_messages(uid: str, session_id: str) -> list[dict[str, Any]]:
    """Load chat messages for a session from in-memory store."""
    key = f"{uid}:{session_id}"
    return _history.get(key, [])


def save_messages(uid: str, session_id: str, messages: list[dict[str, Any]]) -> None:
    """Save messages to in-memory store."""
    from copy import deepcopy
    key = f"{uid}:{session_id}"
    _history[key] = deepcopy(messages)
    log.debug("Saved %d messages in memory (session=%s)", len(messages), session_id[:8])


def append_message(uid: str, session_id: str, role: str, content: Any) -> None:
    """Append a single message to the in-memory store."""
    key = f"{uid}:{session_id}"
    if key not in _history:
        _history[key] = []
    _history[key].append({"role": role, "content": content})
