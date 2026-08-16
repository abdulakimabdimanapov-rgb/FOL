"""Phase 6 regression tests — legacy LLM adapter migration.

Verifies that the remaining runtime consumers (deep-profile analyzers,
Obsidian linker/tools, web-tier profile synthesis) now call the LLM through
the canonical bridge (``orchestrator.llm_bridge`` → canonical LLMRouter),
and that the bridge preserves the legacy event/JSON contracts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


def _module_of(obj) -> str:
    return getattr(obj, "__module__", "")


def test_deep_profile_analyzers_use_canonical_bridge():
    """analyze/* consumers bind llm_call_json from the canonical bridge."""
    from analyze import tavily_synthesizer, topic_extractor, voice_analyzer

    for mod in (voice_analyzer, topic_extractor, tavily_synthesizer):
        assert _module_of(mod.llm_call_json) == "orchestrator.llm_bridge", mod.__name__


def test_web_profile_synthesis_uses_canonical_bridge():
    from src.synthesis.profile import llm_acompletion

    assert _module_of(llm_acompletion) == "orchestrator.llm_bridge"


def test_obsidian_tools_use_canonical_bridge():
    """obsidian/tools.py now imports llm_completion_sync from the bridge."""
    import inspect

    import obsidian.tools as tools_mod

    source = inspect.getsource(tools_mod)
    assert "from analyze._llm" not in source
    assert "orchestrator.llm_bridge" in source


def test_obsidian_linker_uses_canonical_bridge():
    """obsidian/linker.py resolves llm_call_json from the bridge at call time."""
    from obsidian.linker import auto_link_note

    with patch("orchestrator.llm_bridge.llm_call_json") as mock_llm, \
         patch("obsidian.linker.search", return_value=[]):
        mock_llm.side_effect = [["concept"], []]
        assert auto_link_note("X/note", "content about something") == []


def test_legacy_adapter_still_importable_and_intact():
    """The legacy adapter is preserved (its own tests + scripts still use it)."""
    import analyze._llm  # noqa: F401
    import analyze._llm_async  # noqa: F401

    from analyze._llm import llm_call_json as legacy_json

    assert callable(legacy_json)


def test_bridge_llm_call_json_contract_parity():
    """The bridge's JSON helper keeps the legacy contract: parses fences and
    returns {} on total failure (never raises)."""
    from orchestrator.llm_bridge import llm_call_json

    with patch("orchestrator.llm_bridge.llm_completion_sync",
               return_value='```json\n{"name": "John"}\n```'):
        assert llm_call_json("prompt", "text") == {"name": "John"}

    with patch("orchestrator.llm_bridge.llm_completion_sync", return_value="not json"):
        assert llm_call_json("prompt", "text") == {}

    with patch("orchestrator.llm_bridge.llm_completion_sync", return_value=""):
        assert llm_call_json("prompt", "text") == {}


def test_bridge_llm_call_json_list_wrapping_matches_legacy():
    """Array responses are wrapped as {"data": [...]} — IDENTICAL to the
    legacy analyze/_llm.llm_call_json behavior (which also wraps lists).
    Locks in parity so the migrated obsidian linker / deep-profile consumers
    see exactly the same shapes as before."""
    from orchestrator.llm_bridge import llm_call_json

    with patch("orchestrator.llm_bridge.llm_completion_sync",
               return_value='["a", "b"]'):
        assert llm_call_json("prompt", "text") == {"data": ["a", "b"]}

    # And the legacy adapter agrees (same wrapping).
    from analyze._llm import llm_call_json as legacy_json

    with patch("analyze._llm.llm_call", return_value='["a", "b"]'):
        assert legacy_json("prompt", "text") == {"data": ["a", "b"]}


def test_migrated_consumers_keep_legacy_fallback_semantics():
    """Even with the canonical router unavailable, migrated modules do not
    hard-fail — the bridge falls back to the legacy adapter (same JSON
    contract)."""
    from unittest.mock import MagicMock

    legacy = MagicMock()
    legacy.llm_completion_sync.return_value = '{"legacy": true}'
    with patch("orchestrator.llm_bridge._canonical_router", return_value=None), \
         patch("orchestrator.llm_bridge._legacy", return_value=legacy):
        from analyze.topic_extractor import llm_call_json

        assert llm_call_json("p", "t") == {"legacy": True}
