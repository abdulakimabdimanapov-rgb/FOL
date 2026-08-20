"""
Compatibility wrapper — orchestrator proactive suggestions → canonical engine.

Phase: UNIFIED PROACTIVE ENGINE. The canonical LLM-based suggestion behavior
now lives in ``fol/modules/llm/proactive.py`` (:class:`ProactiveLLMEngine`),
which also hosts the deterministic rules engine and the unified runtime
(:class:`ProactiveEngine`) — ONE proactive system.

This module keeps the exact public names the orchestrator and its tests rely
on (``profile_trigger`` / ``pattern_trigger`` / ``ambient_tick`` /
``_parse_suggestions`` / ``_call_llm_sync`` / ``load_rewards`` /
``CONFIDENCE_THRESHOLD``) and delegates every call to a module-level
``ProactiveLLMEngine``. ``_call_llm_sync`` stays defined HERE so tests that
patch ``suggestion_engine._call_llm_sync`` keep working — the engine receives
it as its injectable ``llm_fn``.
"""
from __future__ import annotations

import json
import pathlib
import time
import uuid

# Importing the bridge also bootstraps fol/ onto sys.path; the actual LLM
# calls go through the canonical BrainInterface (via ProactiveLLMEngine →
# get_brain() → CurrentLLMAdapter → LiteLLMRouter, or → Freebuff once an
# official interface ships).
from llm_bridge import llm_completion_sync  # noqa: F401  (path bootstrap)

from modules.llm.proactive import ProactiveLLMEngine

CONFIDENCE_THRESHOLD = ProactiveLLMEngine.CONFIDENCE_THRESHOLD
MAX_SUGGESTIONS_PER_MINUTE = 3
REWARDS_PATH = pathlib.Path.home() / ".secondself" / "rewards.jsonl"


def _call_llm_sync(system_prompt: str, user_content) -> str:
    """Synchronous LLM call for suggestion generation. Returns raw text."""
    try:
        from modules.llm.brain import get_brain

        messages = [{"role": "user", "content": user_content}] if isinstance(user_content, str) else [{"role": "user", "content": str(user_content)}]
        return get_brain().chat(messages=messages, system=system_prompt, max_tokens=2048)
    except Exception as e:
        print(f"[suggestion_engine] LLM API error: {e}")
        return ""


# The canonical engine, wired to the patchable local LLM caller and the same
# rewards path the orchestrator's /suggestion/respond endpoint writes to.
# The lambda (not a direct function reference) resolves ``_call_llm_sync`` at
# call time, so tests that patch ``suggestion_engine._call_llm_sync`` keep
# intercepting every LLM call.
_engine = ProactiveLLMEngine(
    llm_fn=lambda sp, uc: _call_llm_sync(sp, uc),
    rewards_path=REWARDS_PATH,
)


def _parse_suggestions(text: str | None) -> list[dict]:
    """Parse Claude text response into a list of suggestion dicts."""
    return _engine.parse_suggestions(text)


def profile_trigger(profile: dict | None) -> list[dict]:
    """Layer 1: Generate suggestions based on Tavily profile data."""
    return _engine.profile_trigger(profile)


def pattern_trigger(conversation_history: list[dict], profile: dict | None = None) -> list[dict]:
    """Layer 2: Detect patterns in conversation history."""
    return _engine.pattern_trigger(conversation_history, profile)


def ambient_tick(
    conversation_history: list[dict],
    profile: dict | None = None,
) -> list[dict]:
    """Layer 3: Ambient awareness tick (screenshot + history + rewards)."""
    return _engine.ambient_tick(conversation_history, profile)


def load_rewards() -> list[dict]:
    """Load reward history from disk."""
    return _engine.load_rewards()
