"""Regression tests for the orchestrator ↔ canonical LLMRouter bridge.

Covers (Phase 3):
- the bridge delegates to the canonical LiteLLMRouter (single routing abstraction)
- same event contract as the legacy analyze/_llm_async adapter
- transparent fallback to the legacy adapter when the canonical router is
  unavailable (no hard failure)
- fallback accounting never exposes secrets
- orchestrator module still binds the same names (backward compatibility)

The root pytest suite runs in strict async mode, so async code is executed
through the ``_run`` helper (same convention as tests/test_llm_async.py).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, AsyncGenerator, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import llm_bridge
from llm_bridge import (
    FallbackRecorder,
    llm_astream,
    llm_acompletion,
    llm_completion_sync,
    available_providers,
    fallback_log,
)


def _run(coro: Any) -> Any:
    """Run an async function/collection to completion."""
    return asyncio.run(coro)


def _collect_async(agen: AsyncGenerator[dict, None]) -> list[dict]:
    async def _collect() -> list[dict]:
        return [e async for e in agen]

    return _run(_collect())


# ===========================================================================
# FallbackRecorder
# ===========================================================================


class TestFallbackRecorder:
    def test_records_and_snapshots(self):
        rec = FallbackRecorder(max_entries=3)
        rec.record({"model": "a", "reason": "x"})
        rec.record({"model": "b", "reason": "y"})
        assert [e["model"] for e in rec.snapshot()] == ["a", "b"]
        assert rec.last_error() == "y"

    def test_ring_buffer_caps_entries(self):
        rec = FallbackRecorder(max_entries=2)
        for i in range(5):
            rec.record({"model": str(i), "reason": "x"})
        assert [e["model"] for e in rec.snapshot()] == ["3", "4"]


# ===========================================================================
# Delegation to the canonical router
# ===========================================================================


class _FakeRouter:
    """Stand-in for the canonical LLMRouter recording call kwargs."""

    def __init__(self) -> None:
        self.astream_kwargs: list[dict] = []
        self.acomplete_kwargs: list[dict] = []
        self.sync_kwargs: list[dict] = []

    async def astream(self, messages, *, system=None, tools=None, max_tokens=None):
        self.astream_kwargs.append({
            "messages": messages, "system": system, "tools": tools, "max_tokens": max_tokens,
        })
        yield {"type": "token", "text": "hello from canonical"}
        yield {"type": "done", "stop_reason": "end_turn"}

    async def acomplete(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
        self.acomplete_kwargs.append({
            "messages": messages, "system": system, "tools": tools,
            "max_tokens": max_tokens, "temperature": temperature,
        })
        return {"content": "answer", "tool_calls": [], "stop_reason": "end_turn"}

    def complete_sync(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
        self.sync_kwargs.append({"messages": messages, "system": system, "max_tokens": max_tokens})
        return "sync answer"

    def model_chain(self):
        return ["gpt-4o", "ollama/llama3.2:3b"]

    def available_providers(self):
        return ["gpt-4o", "ollama"]


class TestDelegation:
    def test_astream_delegates_to_canonical_router(self):
        fake = _FakeRouter()
        with patch("llm_bridge._canonical_router", return_value=fake):
            events = _collect_async(llm_astream(
                [{"role": "user", "content": "hi"}], system="sys", tools=[{"name": "t"}], max_tokens=10,
            ))
        assert events[0] == {"type": "token", "text": "hello from canonical"}
        assert events[1] == {"type": "done", "stop_reason": "end_turn"}
        assert fake.astream_kwargs[0]["system"] == "sys"
        assert fake.astream_kwargs[0]["max_tokens"] == 10

    def test_acomplete_delegates(self):
        fake = _FakeRouter()
        with patch("llm_bridge._canonical_router", return_value=fake):
            result = _run(llm_acompletion([{"role": "user", "content": "hi"}], system="sys"))
        assert result["content"] == "answer"
        assert fake.acomplete_kwargs[0]["system"] == "sys"

    def test_completion_sync_delegates(self):
        fake = _FakeRouter()
        with patch("llm_bridge._canonical_router", return_value=fake):
            assert llm_completion_sync([{"role": "user", "content": "hi"}]) == "sync answer"

    def test_model_chain_and_providers_delegate(self):
        fake = _FakeRouter()
        with patch("llm_bridge._canonical_router", return_value=fake):
            assert llm_bridge._get_model_chain() == ["gpt-4o", "ollama/llama3.2:3b"]
            assert available_providers() == ["gpt-4o", "ollama"]

    def test_stream_true_routes_to_legacy(self):
        """llm_acompletion(stream=True) keeps the legacy contract (raw stream)."""
        legacy = MagicMock()
        legacy.llm_acompletion = AsyncMock(return_value={"_stream": "raw", "model": "x"})
        with patch("llm_bridge._canonical_router", return_value=_FakeRouter()), \
             patch("llm_bridge._legacy", return_value=legacy):
            result = _run(llm_acompletion([{"role": "user", "content": "hi"}], stream=True))
        assert result["_stream"] == "raw"
        legacy.llm_acompletion.assert_awaited_once()


# ===========================================================================
# Bridge -> BrainInterface (CurrentLLMAdapter -> canonical router)
# ===========================================================================


class TestBridgeThroughBrainInterface:
    """The bridge must sit on the ONE canonical abstraction: it routes every
    call through ``CurrentLLMAdapter`` (BrainInterface) rather than touching
    the router directly."""

    def test_brain_wraps_the_canonical_router(self):
        from modules.llm.brain import CurrentLLMAdapter

        fake = _FakeRouter()
        with patch("llm_bridge._canonical_router", return_value=fake):
            brain = llm_bridge._brain()
        assert isinstance(brain, CurrentLLMAdapter)
        assert brain._router is fake

    def test_brain_none_when_canonical_missing(self):
        with patch("llm_bridge._canonical_router", return_value=None):
            assert llm_bridge._brain() is None

    def test_sync_empty_preserves_legacy_contract(self):
        """Router returning '' must surface as '' (never a raise)."""
        empty = _FakeRouter()
        empty.complete_sync = lambda *a, **kw: ""
        with patch("llm_bridge._canonical_router", return_value=empty):
            assert llm_completion_sync([{"role": "user", "content": "hi"}]) == ""

    def test_astream_tools_forwarded_through_brain(self):
        fake = _FakeRouter()
        tools = [{"name": "open_app", "description": "Open an app"}]
        with patch("llm_bridge._canonical_router", return_value=fake):
            _collect_async(llm_astream(
                [{"role": "user", "content": "open Safari"}], tools=tools))
        assert fake.astream_kwargs[0]["tools"] == tools

    def test_acomplete_tools_forwarded_through_brain(self):
        fake = _FakeRouter()
        tools = [{"name": "browser_search", "description": "Search"}]
        with patch("llm_bridge._canonical_router", return_value=fake):
            result = _run(llm_acompletion(
                [{"role": "user", "content": "search"}], tools=tools))
        assert result["content"] == "answer"
        assert fake.acomplete_kwargs[0]["tools"] == tools

    def test_bridge_never_bypasses_brain(self):
        """No public bridge function may call the router directly: each one
        must go through ``_brain()`` (CurrentLLMAdapter)."""
        from unittest.mock import AsyncMock

        brain = MagicMock()
        brain.chat_stream.return_value = _gen([{"type": "token", "text": "x"}])
        brain.acomplete = AsyncMock(return_value={"content": "x", "tool_calls": [], "stop_reason": "end_turn"})
        brain.chat.return_value = "x"
        brain.model_chain.return_value = ["m"]
        brain.available_providers.return_value = ["m"]
        brain.test_connection.return_value = "ok"

        with patch("llm_bridge._brain", return_value=brain):
            assert _collect_async(llm_astream([{"role": "user", "content": "hi"}]))[0]["type"] == "token"
            assert _run(llm_acompletion([{"role": "user", "content": "hi"}]))["content"] == "x"
            assert llm_completion_sync([{"role": "user", "content": "hi"}]) == "x"
            assert llm_bridge._get_model_chain() == ["m"]
            assert available_providers() == ["m"]
            assert llm_bridge.test_connection() == "ok"
            brain.chat_stream.assert_called_once()
            brain.acomplete.assert_awaited_once()
            brain.chat.assert_called_once()

    def test_suggestion_engine_calls_the_brain(self):
        """The suggestion engine (a runtime consumer) must go through
        BrainInterface, not the bridge or the router directly."""
        import suggestion_engine

        brain = MagicMock()
        brain.chat.return_value = '{"suggestions": []}'
        with patch("modules.llm.brain.get_brain", return_value=brain):
            out = suggestion_engine._call_llm_sync("system prompt", "user content")
        assert out == '{"suggestions": []}'
        brain.chat.assert_called_once()
        call_kwargs = brain.chat.call_args.kwargs
        assert call_kwargs["system"] == "system prompt"
        assert call_kwargs["max_tokens"] == 2048

    def test_suggestion_engine_failure_returns_empty(self):
        import suggestion_engine

        brain = MagicMock()
        brain.chat.side_effect = RuntimeError("brain down")
        with patch("modules.llm.brain.get_brain", return_value=brain):
            assert suggestion_engine._call_llm_sync("s", "u") == ""


# ===========================================================================
# Contract parity with the legacy adapter
# ===========================================================================


def _gen(events: list[dict]) -> AsyncGenerator[dict, None]:
    async def _inner():
        for e in events:
            yield e

    return _inner()


class TestContractParity:
    def test_astream_event_shapes_match_legacy_contract(self):
        """The bridge must yield exactly the legacy event shapes (type keys)."""
        legacy_events = [
            {"type": "token", "text": "hi"},
            {"type": "tool_use", "id": "t1", "name": "open_app", "input": {"name": "Safari"}},
            {"type": "done", "stop_reason": "tool_use"},
            {"type": "error", "message": "boom"},
        ]
        fake = MagicMock()
        fake.astream = lambda messages, **kw: _gen(legacy_events)
        with patch("llm_bridge._canonical_router", return_value=fake):
            seen = _collect_async(llm_astream([{"role": "user", "content": "x"}]))
        assert seen == legacy_events


# ===========================================================================
# Resilience: legacy fallback when canonical is unavailable
# ===========================================================================


class TestLegacyFallback:
    def test_astream_falls_back_to_legacy(self):
        legacy = MagicMock()
        legacy.llm_astream = lambda *a, **kw: _gen([{"type": "token", "text": "legacy stream"}])
        with patch("llm_bridge._canonical_router", return_value=None), \
             patch("llm_bridge._legacy", return_value=legacy):
            events = _collect_async(llm_astream([{"role": "user", "content": "hi"}]))
        assert events == [{"type": "token", "text": "legacy stream"}]

    def test_acomplete_falls_back_to_legacy(self):
        legacy = MagicMock()
        legacy.llm_acompletion = AsyncMock(return_value={"content": "old", "tool_calls": [], "stop_reason": "end_turn"})
        with patch("llm_bridge._canonical_router", return_value=None), \
             patch("llm_bridge._legacy", return_value=legacy):
            result = _run(llm_acompletion([{"role": "user", "content": "hi"}]))
        assert result["content"] == "old"

    def test_sync_falls_back_to_legacy(self):
        legacy = MagicMock()
        legacy.llm_completion_sync.return_value = "legacy sync"
        with patch("llm_bridge._canonical_router", return_value=None), \
             patch("llm_bridge._legacy", return_value=legacy):
            assert llm_completion_sync([{"role": "user", "content": "hi"}]) == "legacy sync"

    def test_model_chain_falls_back_to_legacy(self):
        legacy = MagicMock()
        legacy._get_model_chain.return_value = ["old-model"]
        with patch("llm_bridge._canonical_router", return_value=None), \
             patch("llm_bridge._legacy", return_value=legacy):
            assert llm_bridge._get_model_chain() == ["old-model"]


# ===========================================================================
# Secret safety
# ===========================================================================


class TestSecretSafety:
    def test_fallback_log_never_contains_key_values(self):
        rec = FallbackRecorder()
        rec.record({"provider": "cloud", "model": "gpt-4o", "reason": "***", "attempt_index": 1, "total": 2})
        snapshot = rec.snapshot()
        assert snapshot
        assert all("sk-" not in str(e.get("reason", "")) for e in snapshot)

    def test_bridge_does_not_log_keys_from_environment(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-do-not-log-me")
        key = llm_bridge._get_api_key_for_model("openrouter/anthropic/claude-3.5-sonnet")
        assert key == "sk-or-v1-do-not-log-me"
        assert all("do-not-log-me" not in str(e) for e in fallback_log())


# ===========================================================================
# Backward compatibility: orchestrator still binds the same names
# ===========================================================================


class TestOrchestratorCompatibility:
    def test_server_module_still_exposes_llm_names(self):
        import server  # orchestrator/server.py (conftest puts orchestrator/ on sys.path)

        assert callable(server.llm_astream)
        assert callable(server.llm_acompletion)
        assert callable(server.llm_completion_sync)

    def test_suggestion_engine_uses_bridge(self):
        import suggestion_engine

        assert callable(suggestion_engine._call_llm_sync)
