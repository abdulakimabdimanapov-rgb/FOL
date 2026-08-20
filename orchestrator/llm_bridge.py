"""Compatibility bridge — orchestrator ↔ BrainInterface ↔ canonical router.

Phase 3: the orchestrator previously called the legacy ``analyze/_llm_async``
module directly (``llm_astream`` / ``llm_acompletion`` /
``llm_completion_sync``). This bridge keeps those exact names and event
contracts while delegating to the canonical brain — ``BrainInterface`` via
``CurrentLLMAdapter`` (``fol/modules/llm/brain.py``) — which in turn
forwards to the canonical ``LiteLLMRouter`` from ``fol/modules/llm/router.py``
(the single LLM routing abstraction: local / cloud / fallback through one
contract). The bridge is the compatibility layer that lets every existing
consumer (``orchestrator/server.py``, ``suggestion_engine``, ``analyze/*``,
``obsidian/*``, ``src/synthesis/profile.py``) sit on the ONE canonical
internal abstraction without changing their call sites.

Contract parity (identical to ``analyze/_llm_async``):
  - ``llm_astream(...)``     → async generator yielding
    ``{"type": "token"|"tool_use"|"done"|"error", ...}`` dicts
  - ``llm_acompletion(...)`` → ``{"content", "tool_calls", "stop_reason"}`` dict
  - ``llm_completion_sync(...)`` → ``str`` (empty on total failure)
  - ``_get_model_chain()`` / ``_get_api_key_for_model()`` / ``test_connection()``

Fallback accounting:
  The canonical router records every model failure (provider / model / reason /
  attempt) through ``fallback_log()`` — never including secrets.

Resilience:
  If the canonical router cannot be imported (e.g. ``fol/`` missing), the
  bridge transparently falls back to the legacy ``analyze/_llm_async`` module
  so the orchestrator never hard-fails.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Make the FOL flat import root importable (same pattern as fol/run_api_server.py).
_FOL_DIR = Path(__file__).resolve().parent.parent / "fol"
if str(_FOL_DIR) not in sys.path:
    sys.path.insert(0, str(_FOL_DIR))

# Load the project .env explicitly (same file server.py loads) so the chain
# resolves regardless of the process working directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=True)


class FallbackRecorder:
    """In-memory fallback accounting. Records (provider, model, reason,
    attempt) tuples — never secrets."""

    def __init__(self, max_entries: int = 100) -> None:
        self._entries: list[dict[str, Any]] = []
        self._max = max_entries
        self._last_error: str = ""

    def record(self, entry: dict[str, Any]) -> None:
        self._entries.append(dict(entry))
        if len(self._entries) > self._max:
            self._entries.pop(0)
        self._last_error = str(entry.get("reason", ""))

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._entries)

    def last_error(self) -> str:
        return self._last_error


_recorder = FallbackRecorder()
_canonical: Any = None  # cached canonical router instance
_canonical_error: str = ""


def _canonical_router() -> Any:
    """Build (once) the canonical LiteLLMRouter with the recorder hooked.

    Returns None when the canonical module is unavailable, in which case the
    bridge falls back to the legacy adapter.
    """
    global _canonical, _canonical_error
    if _canonical is not None or _canonical_error:
        return _canonical
    try:
        from modules.llm.router import LiteLLMRouter

        _canonical = LiteLLMRouter(on_fallback=_recorder.record)
    except Exception as exc:  # pragma: no cover - defensive
        _canonical_error = str(exc)
        logger.warning(
            "Canonical LLMRouter unavailable (%s) — using legacy analyze/_llm_async", exc
        )
        _canonical = None
    return _canonical


def _legacy() -> Any:
    """Lazily import the legacy adapter (kept as compatibility fallback)."""
    import analyze._llm_async as _llm_async

    return _llm_async


def _brain() -> Any:
    """The canonical brain backend, chosen via ``get_brain()`` so that
    ``FOL_BRAIN`` (current / freebuff) reaches the bridge. Returns ``None``
    when the canonical router is unavailable, in which case the bridge falls
    back to the legacy adapter.

    ``BrainConfigurationError`` (e.g. ``FOL_BRAIN=freebuff`` while Freebuff
    has no programmatic interface) is re-raised: an explicit backend choice
    must fail loudly, never silently fall back.
    """
    router = _canonical_router()
    if router is None:
        return None
    try:
        from modules.llm.brain import BrainConfigurationError, get_brain

        return get_brain(router=router)
    except BrainConfigurationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "BrainInterface unavailable (%s) — using legacy analyze/_llm_async", exc
        )
        return None


# ---------------------------------------------------------------------------
# Streaming — same event contract as analyze/_llm_async.llm_astream
# ---------------------------------------------------------------------------

async def llm_astream(
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream tokens and tool calls from any LLM via the canonical router.

    Yields dicts:
        {"type": "token", "text": "..."}
        {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
        {"type": "done", "stop_reason": "end_turn" | "tool_use"}
        {"type": "error", "message": "..."}
    """
    brain = _brain()
    if brain is None:
        async for event in _legacy().llm_astream(
            messages, system=system, tools=tools, max_tokens=max_tokens
        ):
            yield event
        return
    async for event in brain.chat_stream(
        messages, system=system, tools=tools, max_tokens=max_tokens
    ):
        yield event


# ---------------------------------------------------------------------------
# Async completion — same contract as analyze/_llm_async.llm_acompletion
# ---------------------------------------------------------------------------

async def llm_acompletion(
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """Async LLM completion via the canonical router.

    Returns ``{"content", "tool_calls", "stop_reason"}`` (never raises).
    ``stream=True`` requests are routed to the legacy adapter, which returns
    the raw LiteLLM stream (the canonical router exposes streaming through
    ``astream`` instead).
    """
    brain = _brain()
    if brain is None or stream:
        return await _legacy().llm_acompletion(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
        )
    return await brain.acomplete(
        messages, system=system, tools=tools, max_tokens=max_tokens, temperature=temperature
    )


# ---------------------------------------------------------------------------
# Sync completion — same contract as analyze/_llm_async.llm_completion_sync
# ---------------------------------------------------------------------------

def llm_completion_sync(
    messages: list[dict[str, Any]],
    system: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Synchronous LLM completion. Returns text string or empty on failure."""
    brain = _brain()
    if brain is None:
        return _legacy().llm_completion_sync(messages, system=system, max_tokens=max_tokens)
    from modules.llm.brain import BrainError

    try:
        return brain.chat(messages, system=system, max_tokens=max_tokens)
    except BrainError:
        # Legacy contract: empty string on total failure (no raise).
        return ""


# ---------------------------------------------------------------------------
# Introspection helpers (same names the orchestrator's startup uses)
# ---------------------------------------------------------------------------

def _get_model_chain() -> list[str]:
    """Ordered list of models that would be tried (primary first)."""
    brain = _brain()
    if brain is not None:
        return brain.model_chain()
    return _legacy()._get_model_chain()


def _get_api_key_for_model(model: str) -> str | None:
    """Return the API key (or ``"local"``) for a model, or None."""
    if _canonical is not None or not _canonical_error:
        try:
            from modules.llm.router import api_key_for_model as _canonical_key

            return _canonical_key(model)
        except Exception:  # pragma: no cover - defensive
            pass
    return _legacy()._get_api_key_for_model(model)


def available_providers() -> list[str]:
    """Human-readable list of configured providers."""
    brain = _brain()
    if brain is not None:
        return brain.available_providers()
    return sorted({m.split("/", 1)[0] for m in _get_model_chain()})


def fallback_log() -> list[dict[str, Any]]:
    """Fallback attempts recorded this session (no secrets)."""
    return _recorder.snapshot()


def last_fallback_error() -> str:
    """Last recorded failure reason (empty if none)."""
    return _recorder.last_error()


def test_connection() -> str:
    """Quick connectivity test — returns a status string, never raises."""
    brain = _brain()
    if brain is not None:
        return brain.test_connection()
    return _legacy().test_connection()


# ---------------------------------------------------------------------------
# JSON mode — same contract as analyze/_llm.llm_call_json
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` fences around a code block."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def llm_call_json(
    prompt: str,
    text_block: str,
    max_tokens: int | None = None,
) -> dict:
    """JSON-mode completion — parse a dict from the model output.

    Same contract as ``analyze/_llm.llm_call_json`` (system prompt + text
    block → parsed JSON dict, ``{}`` on failure), but the LLM call itself is
    delegated to the canonical router through ``llm_completion_sync`` when
    available, so the JSON path shares the single routing abstraction. The
    markdown-fence handling and one retry-on-invalid-JSON are local (they are
    presentation, not routing).
    """
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": text_block},
    ]
    last_error = ""
    for attempt in (0, 1):  # one retry on invalid JSON
        raw = llm_completion_sync(messages, max_tokens=max_tokens)
        if not raw:
            continue
        cleaned = _strip_markdown_fences(raw)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"data": parsed}
            last_error = f"Response is {type(parsed).__name__}, not dict"
            logger.warning("LLM returned non-dict JSON (%s): %.200s", last_error, cleaned)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            if attempt == 0:
                logger.warning("LLM returned non-JSON, retrying. Raw: %.200s", raw)
    if last_error:
        logger.warning("llm_call_json failed: %s", last_error)
    return {}


__all__ = [
    "llm_astream",
    "llm_acompletion",
    "llm_completion_sync",
    "_get_model_chain",
    "_get_api_key_for_model",
    "available_providers",
    "fallback_log",
    "last_fallback_error",
    "test_connection",
    "llm_call_json",
]
