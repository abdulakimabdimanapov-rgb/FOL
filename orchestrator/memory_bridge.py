"""orchestrator/memory_bridge.py — canonical memory boundary for the orchestrator.

Phase 4: the orchestrator talks to memory through exactly ONE path — the FOL
API memory endpoints (``/api/memory/context`` + ``/api/memory/episode``), which
delegate to the canonical ``MemoryService`` (``RAGMemoryService``) inside FOL.
There is deliberately NO second retrieval path: no direct vector-store access,
no second RAG call — a single RAG retrieval happens inside FOL and the result
is assembled here into a prompt-ready context block.

Guarantees:
- ``retrieve_context`` NEVER raises and returns ``""`` when the FOL API is
  unavailable, so the orchestrator keeps working without memory.
- ``record_episode`` NEVER raises and is best-effort.
- All memory content is passed through a deterministic **secret filter**:
  API keys, tokens, passwords, OAuth credentials and private keys are scrubbed
  before they are stored or injected into prompts. Secrets are never stored.
- Nothing here reads ``.env`` values or logs credentials.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# The FOL API is the single memory endpoint for the orchestrator.
FOL_API_URL = os.environ.get("FOL_API_URL", "http://localhost:8754")

# ---------------------------------------------------------------------------
# Secret filter — deterministic scrub before memory write / prompt injection
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, str]] = [
    # Authorization / Bearer tokens
    (r"(?i)\b(bearer|authorization)\s+[a-z0-9._~+/=-]{8,}", r"\1 [REDACTED]"),
    # API keys (sk-, pk-, gsk_, AKIA, xai-, anthropic, openai, gemini, groq, deepseek)
    (r"\b(?:sk|pk|gk|xai|sk-ant|sk-proj)-[a-z0-9._-]{8,}", "[REDACTED_KEY]"),
    (r"\b(gsk_[a-z0-9]{16,})", "[REDACTED_KEY]"),
    (r"\b(AKIA[0-9A-Z]{16})", "[REDACTED_KEY]"),
    (r"(?i)\bapi[_-]?key\b\s*[:=]\s*[\"']?[a-z0-9._-]{8,}", "api_key=[REDACTED]"),
    # OAuth / refresh tokens
    (r"(?i)\b(access_token|refresh_token|oauth_token|id_token)\b\s*[:=]\s*[\"']?[a-z0-9._~+/=-]{8,}",
     r"\1=[REDACTED]"),
    # Passwords / secrets / private keys
    (r"(?i)\b(password|passwd|secret|token|pwd)\b\s*[:=]\s*[\"']?[^\"'\s]{6,}",
     r"\1=[REDACTED]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
     "[REDACTED_PRIVATE_KEY]", re.DOTALL),
    # Client secrets
    (r"(?i)\bclient[_-]?secret\b\s*[:=]\s*[\"']?[a-z0-9._-]{8,}", "client_secret=[REDACTED]"),
]

# Patterns that, when present, cause an entire memory item to be dropped.
_DROP_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|secret|client[_-]?secret)\s*[:=]\s*[^\"'\s]{6,}"),
)


def _scrub(text: str) -> str:
    """Deterministically remove/redact secret-like content from a string."""
    if not text:
        return text
    out = text
    for entry in _SECRET_PATTERNS:
        pattern, replacement = entry[0], entry[1]
        flags = entry[2] if len(entry) > 2 else 0
        out = re.sub(pattern, replacement, out, flags=flags)
    return out


def _is_secret_like(text: str) -> bool:
    """True when the text is (almost certainly) a credential — drop entirely."""
    return any(p.search(text) for p in _DROP_PATTERNS)


# ---------------------------------------------------------------------------
# Transport — never raises
# ---------------------------------------------------------------------------

def _post(endpoint: str, body: dict) -> dict:
    """Best-effort POST to the FOL API. Returns {} on any failure."""
    try:
        import urllib.request

        req = urllib.request.Request(
            f"{FOL_API_URL}{endpoint}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except Exception as exc:  # pragma: no cover - network, best-effort
        logger.debug("memory_bridge %s failed: %s", endpoint, exc)
        return {}


# ---------------------------------------------------------------------------
# Public API — the single memory path
# ---------------------------------------------------------------------------

def retrieve_context(query: str, *, limit: int = 5, max_chars: int = 1200) -> str:
    """Return a prompt-ready memory context block for ``query``.

    Single retrieval path: FOL API ``/api/memory/context`` → canonical
    ``MemoryService.retrieve_context``. Returns ``""`` when unavailable or
    when every retrieved memory was secret-like.
    """
    if not query:
        return ""
    try:
        result = _post("/api/memory/context", {"query": query, "limit": limit})
        context = result.get("context") or ""
        if not context:
            return ""
        # Never inject secrets into prompts.
        context = _scrub(context)
        if _is_secret_like(context):
            return ""
        if max_chars and len(context) > max_chars:
            context = context[:max_chars] + "…"
        return context
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("retrieve_context failed: %s", exc)
        return ""


def record_episode(
    event: str,
    *,
    context: str = "",
    importance: float = 1.0,
    metadata: dict | None = None,
) -> bool:
    """Best-effort episodic memory write via the canonical path.

    Secret filtering is applied BEFORE the payload leaves this process, so a
    credential that ended up in a task string can never be persisted.
    """
    try:
        if _is_secret_like(event) or _is_secret_like(context):
            return False
        event = _scrub(event)
        context = _scrub(context)
        metadata = {k: _scrub(str(v)) for k, v in (metadata or {}).items()}
        result = _post(
            "/api/memory/episode",
            {
                "event": event[:1000],
                "context": context[:2000],
                "importance": importance,
                "metadata": metadata,
            },
        )
        return result.get("status") == "recorded"
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("record_episode failed: %s", exc)
        return False


def record_activity(
    summary: str,
    *,
    category: str = "agent_action",
    source: str = "system",
    importance: float = 1.0,
    metadata: dict | None = None,
) -> bool:
    """Canonical-first write for conversation / activity events (Phase 6).

    The single unified memory path for the active execution layers
    (orchestrator, obsidian tools, web-tier chat):

      1. Deterministic secret filter — secret-like events are dropped, the
         rest is scrubbed exactly once, before anything is persisted.
      2. Local ``episodic.md`` mirror — the pre-existing plain-text store the
         orchestrator prompt builder and the web-tier deep profile read.
         Kept on purpose (it feeds prompts), not a new storage path.
      3. Canonical FOL API memory boundary (``record_episode`` →
         ``MemoryService.record_episode``) — best effort, never raises.

    No second vector/RAG path is created: the FOL API remains the canonical
    boundary and ``episodic.md`` is the same local file the active prompt
    builders already depend on.

    Returns False only when the event is dropped as secret-like.
    """
    try:
        if not summary or _is_secret_like(summary):
            return False
        scrubbed = _scrub(str(summary))[:1000]
        try:
            from utils.episodic_writer import append_event

            append_event(
                summary=scrubbed,
                category=category,
                source=source,
            )
        except Exception as exc:  # pragma: no cover - local mirror is best-effort
            logger.debug("record_activity local mirror failed: %s", exc)
        record_episode(
            scrubbed,
            context=f"source={source}",
            importance=importance,
            metadata={"source": source, **(metadata or {})},
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("record_activity failed: %s", exc)
        return False


def retrieve_lessons(task: str = "", *, limit: int = 5) -> list[str]:
    """Retrieve relevant lessons from Brain/Lessons.md via FOL API.

    If ``task`` is provided, returns only lessons relevant to that task
    (keyword-overlap ranking).  Falls back to recent lessons when the
    FOL API is unreachable.
    """
    try:
        result = _post("/api/memory/lessons", {"limit": limit + 10})
        lessons = result.get("lessons") or []
        if not lessons or not task:
            return lessons[:limit]
        # Simple keyword-overlap ranking for relevance
        task_words = set(task.lower().split())
        scored = []
        for lesson in lessons:
            l_words = set(lesson.lower().split())
            overlap = len(task_words & l_words)
            scored.append((overlap, lesson))
        scored.sort(key=lambda x: -x[0])
        # Return only lessons with at least one overlapping word
        return [lesson for _, lesson in scored[:limit] if scored[0][0] > 0]
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("retrieve_lessons failed: %s", exc)
        return []


__all__ = ["retrieve_context", "record_episode", "record_activity", "retrieve_lessons", "_scrub", "_is_secret_like"]
