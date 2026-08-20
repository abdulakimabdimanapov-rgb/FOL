"""Unit tests for analyze/_llm_async.py — model fallback chain."""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import analyze._llm_async as llm_async


@pytest.fixture(autouse=True)
def _enable_local_for_legacy_fallback_tests(monkeypatch):
    """These pre-policy tests exercise fallback mechanics with ollama models;
    explicitly re-enable local LLMs so the mechanics stay covered (the policy
    itself is enforced in fol/modules/llm/router.py and its tests)."""
    monkeypatch.setenv("FOL_ENABLE_LOCAL_LLM", "1")
    yield


def _run(coro) -> Any:
    """Run an async function to completion in a fresh event loop."""
    return asyncio.run(coro)


async def _collect(agen) -> list[dict]:
    """Collect all events from an async generator."""
    return [event async for event in agen]


# ===========================================================================
# _get_model_chain
# ===========================================================================


class TestGetModelChain:
    """_get_model_chain() builds the primary + fallback priority list."""

    def test_primary_only_when_no_fallbacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", return_value="sk-test"):
                assert llm_async._get_model_chain() == ["gpt-4o"]

    def test_appends_fallbacks_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b, claude-sonnet-4-20250514")
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", return_value="sk-test"):
                assert llm_async._get_model_chain() == ["gpt-4o", "ollama/llama3.2:3b", "claude-sonnet-4-20250514"]

    def test_skips_models_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            def _fake_key(model: str) -> str | None:
                return "sk-test" if model == "gpt-4o" else None
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=_fake_key):
                assert llm_async._get_model_chain() == ["gpt-4o"]

    def test_deduplicates_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "gpt-4o")
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", return_value="sk-test"):
                assert llm_async._get_model_chain() == ["gpt-4o"]

    def test_empty_chain_when_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", return_value=None):
                assert llm_async._get_model_chain() == []


# ===========================================================================
# _get_api_key_for_model — prefix ordering
# ===========================================================================


class TestGetApiKeyForModel:
    def test_openrouter_prefix_wins_over_anthropic_substring(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-key", "ANTHROPIC_API_KEY": "ant-key"}, clear=False):
            assert llm_async._get_api_key_for_model("openrouter/anthropic/claude-3.5-sonnet") == "or-key"

    def test_ollama_returns_local(self) -> None:
        assert llm_async._get_api_key_for_model("ollama/llama3.2:3b") == "local"


# ===========================================================================
# llm_acompletion fallback
# ===========================================================================


class TestLlmAcompletionFallback:
    """llm_acompletion() falls back to the next model when the primary fails."""

    def test_falls_back_when_primary_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        fake_litellm = MagicMock()

        async def _acompletion_impl(**kwargs: Any):
            if kwargs["model"] == "gpt-4o":
                raise Exception("provider down")
            return MagicMock()

        fake_litellm.acompletion.side_effect = _acompletion_impl

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.object(llm_async, "_parse_openai_response", return_value={"content": "ok", "tool_calls": [], "stop_reason": "end_turn"}):
                    with patch.dict("sys.modules", {"litellm": fake_litellm}):
                        result = _run(llm_async.llm_acompletion(
                            messages=[{"role": "user", "content": "hi"}],
                        ))

        assert result == {"content": "ok", "tool_calls": [], "stop_reason": "end_turn"}
        models = [c.kwargs["model"] for c in fake_litellm.acompletion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]

    def test_error_dict_when_all_models_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        fake_litellm = MagicMock()

        async def _acompletion_impl(**kwargs: Any):
            raise Exception("all providers down")

        fake_litellm.acompletion.side_effect = _acompletion_impl

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": fake_litellm}):
                    result = _run(llm_async.llm_acompletion(
                        messages=[{"role": "user", "content": "hi"}],
                    ))

        assert result["stop_reason"] == "error"
        assert result["content"] == ""

    def test_error_dict_when_chain_empty(self) -> None:
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", return_value=None):
                result = _run(llm_async.llm_acompletion(
                    messages=[{"role": "user", "content": "hi"}],
                ))
        assert result["stop_reason"] == "error"

    def test_falls_back_when_primary_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty response (no content, no tool calls) must NOT short-circuit
        the chain — try the next model (stress-test finding)."""
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        fake_litellm = MagicMock()

        async def _acompletion_impl(**kwargs: Any):
            return MagicMock()

        fake_litellm.acompletion.side_effect = _acompletion_impl

        empty = {"content": "", "tool_calls": [], "stop_reason": "end_turn"}
        ok = {"content": "fallback answer", "tool_calls": [], "stop_reason": "end_turn"}

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.object(llm_async, "_parse_openai_response", side_effect=[empty, ok]):
                    with patch.dict("sys.modules", {"litellm": fake_litellm}):
                        result = _run(llm_async.llm_acompletion(
                            messages=[{"role": "user", "content": "hi"}],
                        ))

        assert result == ok
        models = [c.kwargs["model"] for c in fake_litellm.acompletion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]

    def test_error_dict_when_all_models_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        fake_litellm = MagicMock()

        async def _acompletion_impl(**kwargs: Any):
            return MagicMock()

        fake_litellm.acompletion.side_effect = _acompletion_impl
        empty = {"content": "", "tool_calls": [], "stop_reason": "end_turn"}

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.object(llm_async, "_parse_openai_response", return_value=empty):
                    with patch.dict("sys.modules", {"litellm": fake_litellm}):
                        result = _run(llm_async.llm_acompletion(
                            messages=[{"role": "user", "content": "hi"}],
                        ))
        assert result["stop_reason"] == "error"
        assert result["content"] == ""


# ===========================================================================
# llm_astream fallback
# ===========================================================================


class _FakeDelta:
    def __init__(self, content: str | None = None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, choices):
        self.choices = choices


class TestLlmAstreamFallback:
    """llm_astream() falls back to the next model when the primary fails."""

    def test_falls_back_when_primary_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        fake_litellm = MagicMock()

        async def _stream_gen():
            yield _FakeChunk([_FakeChoice(_FakeDelta("hello from fallback"), finish_reason="stop")])

        async def _acompletion_impl(**kwargs: Any):
            if kwargs["model"] == "gpt-4o":
                raise Exception("provider down")
            return _stream_gen()

        fake_litellm.acompletion.side_effect = _acompletion_impl

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": fake_litellm}):
                    events = _run(_collect(llm_async.llm_astream(
                        messages=[{"role": "user", "content": "hi"}],
                    )))

        assert [e["text"] for e in events if e["type"] == "token"] == ["hello from fallback"]
        assert not any(e["type"] == "error" for e in events)
        done = [e for e in events if e["type"] == "done"]
        assert done and done[0]["stop_reason"] == "end_turn"

    def test_error_event_when_all_models_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        fake_litellm = MagicMock()

        async def _acompletion_impl(**kwargs: Any):
            raise Exception("all providers down")

        fake_litellm.acompletion.side_effect = _acompletion_impl

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": fake_litellm}):
                    events = _run(_collect(llm_async.llm_astream(
                        messages=[{"role": "user", "content": "hi"}],
                    )))

        assert events[0]["type"] == "error"
        assert "failed" in events[0]["message"]

    def test_error_event_when_chain_empty(self) -> None:
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", return_value=None):
                events = _run(_collect(llm_async.llm_astream(
                    messages=[{"role": "user", "content": "hi"}],
                )))
        assert events[0]["type"] == "error"


# ===========================================================================
# llm_completion_sync fallback
# ===========================================================================


class TestLlmCompletionSyncFallback:
    """llm_completion_sync() falls back to the next model when the primary fails."""

    def test_falls_back_when_primary_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "sync fallback"

        fake_litellm = MagicMock()
        fake_litellm.completion.side_effect = [Exception("provider down"), mock_response]

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": fake_litellm}):
                    result = llm_async.llm_completion_sync(
                        messages=[{"role": "user", "content": "hi"}],
                    )

        assert result == "sync fallback"
        models = [c.kwargs["model"] for c in fake_litellm.completion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]

    def test_returns_empty_when_chain_empty(self) -> None:
        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", return_value=None):
                result = llm_async.llm_completion_sync(
                    messages=[{"role": "user", "content": "hi"}],
                )
        assert result == ""

    def test_falls_back_when_primary_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty primary must NOT short-circuit — try the next model."""
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        empty_resp = MagicMock()
        empty_resp.choices[0].message.content = ""
        ok_resp = MagicMock()
        ok_resp.choices[0].message.content = "sync fallback"

        fake_litellm = MagicMock()
        fake_litellm.completion.side_effect = [empty_resp, ok_resp]

        with patch.object(llm_async, "_get_config", return_value={"model": "gpt-4o", "max_tokens": 4096, "temperature": 0}):
            with patch.object(llm_async, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": fake_litellm}):
                    result = llm_async.llm_completion_sync(
                        messages=[{"role": "user", "content": "hi"}],
                    )

        assert result == "sync fallback"
        models = [c.kwargs["model"] for c in fake_litellm.completion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]
