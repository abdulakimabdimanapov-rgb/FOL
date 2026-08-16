"""Regression tests for the canonical LLM router (modules/llm/router.py).

Covers the single routing abstraction contract:
- model chain building (local/cloud/fallback, key skipping, dedupe)
- provider key detection (prefix vs substring ordering)
- LiteLLMRouter sync/async/stream fallback behaviour (hermetic)
- EngineBackendRouter adapter over the native engine
- get_llm_router factory
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.llm.router import (
    EngineBackendRouter,
    LiteLLMRouter,
    build_model_chain,
    api_key_for_model,
    get_llm_router,
    is_local_model,
    provider_kind,
)


# ===========================================================================
# build_model_chain
# ===========================================================================


class TestBuildModelChain:
    def test_primary_only(self):
        chain = build_model_chain(primary="gpt-4o", fallbacks="", key_resolver=lambda m: "sk")
        assert chain == ["gpt-4o"]

    def test_fallbacks_in_order(self):
        chain = build_model_chain(
            primary="gpt-4o",
            fallbacks="ollama/llama3.2:3b, claude-sonnet-4-20250514",
            key_resolver=lambda m: "local" if m.startswith("ollama") else "sk",
        )
        assert chain == ["gpt-4o", "ollama/llama3.2:3b", "claude-sonnet-4-20250514"]

    def test_skips_models_without_key(self):
        chain = build_model_chain(
            primary="gpt-4o",
            fallbacks="ollama/llama3.2:3b",
            key_resolver=lambda m: "sk" if m == "gpt-4o" else None,
        )
        assert chain == ["gpt-4o"]

    def test_local_models_never_skipped(self):
        chain = build_model_chain(
            primary="ollama/llama3.2:3b",
            fallbacks="",
            key_resolver=lambda m: "local",
        )
        assert chain == ["ollama/llama3.2:3b"]

    def test_deduplicates(self):
        chain = build_model_chain(
            primary="gpt-4o", fallbacks="gpt-4o", key_resolver=lambda m: "sk"
        )
        assert chain == ["gpt-4o"]


# ===========================================================================
# api_key_for_model — prefix ordering
# ===========================================================================


class TestApiKeyForModel:
    def test_openrouter_prefix_wins_over_anthropic_substring(self):
        with patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "or-key", "ANTHROPIC_API_KEY": "ant-key"}, clear=False
        ):
            assert api_key_for_model("openrouter/anthropic/claude-3.5-sonnet") == "or-key"

    def test_local_prefixes(self):
        assert api_key_for_model("ollama/llama3.2:3b") == "local"
        assert api_key_for_model("local/my-model") == "local"
        assert api_key_for_model("vllm/mistral") == "local"

    def test_gemini_prefix(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gem-key"}, clear=False):
            assert api_key_for_model("gemini/gemini-2.0-flash") == "gem-key"

    def test_anthropic(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant-key"}, clear=False):
            assert api_key_for_model("claude-sonnet-4-20250514") == "ant-key"

    def test_openai(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "oai-key"}, clear=False):
            assert api_key_for_model("gpt-4o") == "oai-key"

    def test_unknown_falls_back_to_anthropic(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ant-key"}, clear=False):
            assert api_key_for_model("unknown-model") == "ant-key"


# ===========================================================================
# LiteLLMRouter — sync completion fallback
# ===========================================================================


class _KeyPatch:
    """Shared key resolver used to keep router tests hermetic."""

    @staticmethod
    def resolve(model: str) -> str | None:
        return "local" if model.startswith("ollama") else "sk-test"


class TestLiteLLMRouterSync:
    def test_falls_back_when_primary_fails(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        ok = MagicMock()
        ok.choices[0].message.content = "sync fallback"

        fake = MagicMock()
        fake.completion.side_effect = [Exception("provider down"), ok]

        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            with patch.dict("sys.modules", {"litellm": fake}):
                router = LiteLLMRouter()
                result = router.complete_sync([{"role": "user", "content": "hi"}])

        assert result == "sync fallback"
        models = [c.kwargs["model"] for c in fake.completion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]

    def test_empty_when_all_models_fail(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        fake = MagicMock()
        fake.completion.side_effect = Exception("down")
        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            with patch.dict("sys.modules", {"litellm": fake}):
                router = LiteLLMRouter()
                assert router.complete_sync([{"role": "user", "content": "hi"}]) == ""

    def test_empty_when_chain_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        # No key for the only model → empty chain → ""
        with patch("modules.llm.router.api_key_for_model", return_value=None):
            router = LiteLLMRouter()
            assert router.complete_sync([{"role": "user", "content": "hi"}]) == ""

    def test_model_chain_and_providers_on_instance(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            router = LiteLLMRouter()
            assert router.model_chain() == ["gpt-4o", "ollama/llama3.2:3b"]
            assert router.available_providers() == ["gpt-4o", "ollama"]

    def test_test_connection_success(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        ok = MagicMock()
        ok.choices[0].message.content = "OK"
        fake = MagicMock()
        fake.completion.return_value = ok
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                status = LiteLLMRouter().test_connection()
        assert status.startswith("✅")

    def test_system_message_prepended(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        fake = MagicMock()
        fake.completion.return_value = MagicMock()
        fake.completion.return_value.choices[0].message.content = "ok"
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                router = LiteLLMRouter()
                router.complete_sync(
                    [{"role": "user", "content": "hi"}], system="Be polite."
                )
        sent_messages = fake.completion.call_args.kwargs["messages"]
        assert sent_messages[0] == {"role": "system", "content": "Be polite."}


# ===========================================================================
# LiteLLMRouter — async completion + streaming
# ===========================================================================


class _FakeDelta:
    def __init__(self, content: str | None = None):
        self.content = content


class _FakeChoice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(self, choices):
        self.choices = choices


class TestLiteLLMRouterAsync:
    async def test_acomplete_falls_back_on_failure(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        fake = MagicMock()

        async def _acompletion_impl(**kwargs: Any):
            if kwargs["model"] == "gpt-4o":
                raise Exception("provider down")
            resp = MagicMock()
            resp.choices[0].message.content = "fallback answer"
            resp.choices[0].finish_reason = "stop"
            resp.choices[0].message.tool_calls = None
            return resp

        fake.acompletion.side_effect = _acompletion_impl

        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            with patch.dict("sys.modules", {"litellm": fake}):
                router = LiteLLMRouter()
                result = await router.acomplete([{"role": "user", "content": "hi"}])

        assert result["content"] == "fallback answer"
        assert result["stop_reason"] == "end_turn"
        models = [c.kwargs["model"] for c in fake.acompletion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]

    async def test_acomplete_empty_content_tries_next(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        fake = MagicMock()

        def _make(content: str, reason: str = "stop"):
            resp = MagicMock()
            resp.choices[0].message.content = content
            resp.choices[0].finish_reason = reason
            resp.choices[0].message.tool_calls = None
            return resp

        async def _impl(**kwargs: Any):
            return _make("") if kwargs["model"] == "gpt-4o" else _make("second")

        fake.acompletion.side_effect = _impl
        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            with patch.dict("sys.modules", {"litellm": fake}):
                result = await LiteLLMRouter().acomplete([{"role": "user", "content": "hi"}])
        assert result["content"] == "second"

    async def test_acomplete_error_when_chain_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        with patch("modules.llm.router.api_key_for_model", return_value=None):
            result = await LiteLLMRouter().acomplete([{"role": "user", "content": "hi"}])
        assert result["stop_reason"] == "error"
        assert result["content"] == ""

    async def test_astream_token_and_done_events(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        async def _stream():
            yield _FakeChunk([_FakeChoice(_FakeDelta("hello "))])
            yield _FakeChunk([_FakeChoice(_FakeDelta("world"), finish_reason="stop")])

        async def _acompletion_impl(**kwargs: Any):
            return _stream()

        fake = MagicMock()
        fake.acompletion.side_effect = _acompletion_impl
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                events = [e async for e in LiteLLMRouter().astream([{"role": "user", "content": "hi"}])]

        tokens = [e["text"] for e in events if e["type"] == "token"]
        assert tokens == ["hello ", "world"]
        done = [e for e in events if e["type"] == "done"]
        assert done and done[0]["stop_reason"] == "end_turn"

    async def test_astream_error_when_all_models_fail(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        fake = MagicMock()

        async def _acompletion_impl(**kwargs: Any):
            raise Exception("all down")

        fake.acompletion.side_effect = _acompletion_impl
        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            with patch.dict("sys.modules", {"litellm": fake}):
                events = [e async for e in LiteLLMRouter().astream([{"role": "user", "content": "hi"}])]
        assert events[0]["type"] == "error"

    async def test_astream_error_when_chain_empty(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        with patch("modules.llm.router.api_key_for_model", return_value=None):
            events = [e async for e in LiteLLMRouter().astream([{"role": "user", "content": "hi"}])]
        assert events[0]["type"] == "error"


# ===========================================================================
# EngineBackendRouter — adapter over the native engine
# ===========================================================================


class TestEngineBackendRouter:
    async def test_model_chain_and_providers(self):
        engine = MagicMock()
        engine.available_backends = ["mlx", "openrouter"]
        router = EngineBackendRouter(engine)
        assert router.model_chain() == ["mlx", "openrouter"]
        assert router.available_providers() == ["mlx", "openrouter"]

    async def test_acomplete_delegates_to_engine(self):
        engine = AsyncMock()
        engine.generate = AsyncMock(return_value="hello from engine")
        router = EngineBackendRouter(engine)
        result = await router.acomplete([{"role": "user", "content": "hi"}])
        assert result == {"content": "hello from engine", "tool_calls": [], "stop_reason": "end_turn"}
        engine.generate.assert_awaited_once()

    def test_complete_sync_no_running_loop(self):
        engine = AsyncMock()
        engine.generate = AsyncMock(return_value="sync answer")
        router = EngineBackendRouter(engine)
        assert router.complete_sync([{"role": "user", "content": "hi"}]) == "sync answer"

    async def test_complete_sync_inside_running_loop(self):
        """complete_sync must not crash when an event loop is already running
        (e.g. inside the FOL API server) — it falls back to a worker thread."""
        engine = AsyncMock()
        engine.generate = AsyncMock(return_value="threaded answer")
        router = EngineBackendRouter(engine)
        # Called from a running loop: must NOT raise asyncio.run() RuntimeError.
        assert router.complete_sync([{"role": "user", "content": "hi"}]) == "threaded answer"

    def test_complete_sync_empty_prompt(self):
        router = EngineBackendRouter(AsyncMock())
        assert router.complete_sync([{"role": "assistant", "content": "no user msg"}]) == ""

    async def test_acomplete_error_when_engine_fails(self):
        engine = AsyncMock()
        engine.generate = AsyncMock(return_value="[MLX model not loaded]")
        router = EngineBackendRouter(engine)
        result = await router.acomplete([{"role": "user", "content": "hi"}])
        assert result["stop_reason"] == "error"

    async def test_astream_emits_single_token(self):
        engine = AsyncMock()
        engine.generate = AsyncMock(return_value="full text")
        events = [e async for e in EngineBackendRouter(engine).astream([{"role": "user", "content": "hi"}])]
        assert events[0] == {"type": "token", "text": "full text"}
        assert events[1]["type"] == "done"

    async def test_flatten_builds_context_from_history(self):
        engine = AsyncMock()
        engine.generate = AsyncMock(return_value="ok")
        router = EngineBackendRouter(engine)
        await router.acomplete(
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "earlier reply"},
                {"role": "user", "content": "now"},
            ]
        )
        args, kwargs = engine.generate.call_args
        assert args[0] == "now"
        assert kwargs["context"] == "FOL: earlier reply"


# ===========================================================================
# Factory
# ===========================================================================


class TestFactory:
    def test_default_is_litellm(self):
        router = get_llm_router()
        assert isinstance(router, LiteLLMRouter)

    def test_engine_kind_requires_engine(self):
        with pytest.raises(ValueError):
            get_llm_router(kind="engine")

    def test_engine_kind_with_engine(self):
        router = get_llm_router(kind="engine", engine=MagicMock())
        assert isinstance(router, EngineBackendRouter)

    def test_test_connection_never_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        with patch("modules.llm.router.api_key_for_model", return_value=None):
            status = LiteLLMRouter().test_connection()
        assert status.startswith("❌")


# ===========================================================================
# Local model selection (Phase 3 — local/cloud routing)
# ===========================================================================


class TestLocalModelSelection:
    def test_is_local_model_prefixes(self):
        assert is_local_model("ollama/llama3.2:3b")
        assert is_local_model("local/my-model")
        assert is_local_model("vllm/mistral")
        assert is_local_model("lm-studio/qwen")

    def test_is_local_model_mlx(self):
        assert is_local_model("mlx")
        assert is_local_model("mlx-community/Llama-3.2-3B-Instruct-4bit")

    def test_is_local_model_cloud_false(self):
        assert not is_local_model("gpt-4o")
        assert not is_local_model("claude-sonnet-4-20250514")
        assert not is_local_model("openrouter/anthropic/claude-3.5-sonnet")

    def test_provider_kind(self):
        assert provider_kind("ollama/llama3.2:3b") == "local"
        assert provider_kind("mlx") == "local"
        assert provider_kind("gpt-4o") == "cloud"

    def test_local_model_survives_when_no_keys_configured(self):
        # Only local models remain usable when every cloud provider lacks a key.
        chain = build_model_chain(
            primary="gpt-4o",
            fallbacks="ollama/llama3.2:3b, claude-sonnet-4-20250514",
            key_resolver=lambda m: "local" if m.startswith("ollama") else None,
        )
        assert chain == ["ollama/llama3.2:3b"]


# ===========================================================================
# Message normalization (Anthropic blocks → OpenAI shape for non-Anthropic)
# ===========================================================================


class _FakeStreamChunk:
    def __init__(self, choices):
        self.choices = choices


class TestMessageNormalization:
    def _anthropic_blocks(self):
        return [
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me check."},
                {"type": "tool_use", "id": "toolu_1", "name": "browser_goto",
                 "input": {"url": "https://example.com"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
            ]},
        ]

    async def test_astream_normalizes_for_openai_provider(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        captured: dict = {}

        async def _stream(**kwargs: Any):
            captured["messages"] = kwargs["messages"]

            async def _gen():
                yield _FakeStreamChunk([_FakeChoice(_FakeDelta("done"), finish_reason="stop")])

            return _gen()

        fake = MagicMock()
        fake.acompletion.side_effect = _stream
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                [e async for e in LiteLLMRouter().astream(
                    self._anthropic_blocks(), tools=[{"name": "browser_goto", "description": "go",
                                                      "input_schema": {"type": "object", "properties": {}}}]
                )]

        sent = captured["messages"]
        assert sent[0]["role"] == "assistant"
        assert "tool_calls" in sent[0]
        assert sent[0]["tool_calls"][0]["function"]["name"] == "browser_goto"
        # The user tool_result block becomes a separate role="tool" message.
        assert any(m["role"] == "tool" for m in sent)

    async def test_astream_keeps_blocks_for_anthropic_model(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "claude-sonnet-4-20250514")
        captured: dict = {}

        async def _stream(**kwargs: Any):
            captured["messages"] = kwargs["messages"]

            async def _gen():
                yield _FakeStreamChunk([_FakeChoice(_FakeDelta("done"), finish_reason="stop")])

            return _gen()

        fake = MagicMock()
        fake.acompletion.side_effect = _stream
        with patch("modules.llm.router.api_key_for_model", return_value="ant-key"):
            with patch.dict("sys.modules", {"litellm": fake}):
                [e async for e in LiteLLMRouter().astream(self._anthropic_blocks())]

        sent = captured["messages"]
        # Content blocks pass through untouched — no role="tool", no tool_calls.
        assert sent[0]["content"][0]["type"] == "text"
        assert not any(m.get("role") == "tool" for m in sent)

    async def test_acomplete_converts_tools_to_openai_format(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        captured: dict = {}

        async def _acompletion_impl(**kwargs: Any):
            captured["tools"] = kwargs.get("tools")
            resp = MagicMock()
            resp.choices[0].message.content = "ok"
            resp.choices[0].finish_reason = "stop"
            resp.choices[0].message.tool_calls = None
            return resp

        fake = MagicMock()
        fake.acompletion.side_effect = _acompletion_impl
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                await LiteLLMRouter().acomplete(
                    [{"role": "user", "content": "hi"}],
                    tools=[{"name": "open_app", "description": "open", "input_schema": {"type": "object"}}],
                )
        assert captured["tools"][0]["type"] == "function"
        assert captured["tools"][0]["function"]["name"] == "open_app"


# ===========================================================================
# Tool-call responses (acomplete + astream assembly + text tool calls)
# ===========================================================================


class _FakeFunction:
    def __init__(self, name: str = "", arguments: str = ""):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, index: int = 0, id: str = "", name: str = "", arguments: str = ""):
        self.index = index
        self.id = id
        self.function = _FakeFunction(name, arguments)


class _FakeToolDelta:
    def __init__(self, content: str | None = None, tool_calls: list | None = None):
        self.content = content
        self.tool_calls = tool_calls


class TestToolCallResponses:
    def _ok_response(self, content: str, tool_calls=None, finish: str = "stop"):
        resp = MagicMock()
        resp.choices[0].message.content = content
        resp.choices[0].message.tool_calls = tool_calls
        resp.choices[0].finish_reason = finish
        return resp

    async def test_acomplete_parses_tool_calls(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        tc = _FakeToolCall(id="call_1", name="browser_goto", arguments='{"url": "https://example.com"}')
        fake = MagicMock()

        async def _impl(**kwargs: Any):
            return self._ok_response("", [tc], finish="tool_calls")

        fake.acompletion.side_effect = _impl
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                result = await LiteLLMRouter().acomplete([{"role": "user", "content": "go"}])
        assert result["stop_reason"] == "tool_use"
        assert result["tool_calls"] == [{
            "id": "call_1", "name": "browser_goto", "input": {"url": "https://example.com"},
        }]

    async def test_acomplete_malformed_arguments(self, monkeypatch: pytest.MonkeyPatch):
        """Malformed provider response: unparseable arguments JSON → {}."""
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        tc = _FakeToolCall(id="call_1", name="open_app", arguments="not-json{")
        fake = MagicMock()

        async def _impl(**kwargs: Any):
            return self._ok_response("", [tc], finish="tool_calls")

        fake.acompletion.side_effect = _impl
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                result = await LiteLLMRouter().acomplete([{"role": "user", "content": "go"}])
        assert result["tool_calls"][0]["input"] == {}

    async def test_astream_assembles_streamed_tool_calls(self, monkeypatch: pytest.MonkeyPatch):
        """Structured tool-call deltas arrive split — must be assembled + parsed."""
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        async def _stream():
            # OpenAI semantics: the tool-call NAME arrives fully in the first
            # delta for an index and is empty afterwards; ARGUMENTS arrive split.
            yield _FakeStreamChunk([_FakeChoice(
                _FakeToolDelta(tool_calls=[_FakeToolCall(index=0, id="call_1", name="browser_goto", arguments='{"url": "https://')]),
            )])
            yield _FakeStreamChunk([_FakeChoice(
                _FakeToolDelta(tool_calls=[_FakeToolCall(index=0, id="", name="", arguments='example.com"}')]),
            )])
            yield _FakeStreamChunk([_FakeChoice(_FakeToolDelta(), finish_reason="tool_calls")])

        async def _acompletion_impl(**kwargs: Any):
            return _stream()

        fake = MagicMock()
        fake.acompletion.side_effect = _acompletion_impl
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                events = [e async for e in LiteLLMRouter().astream([{"role": "user", "content": "go"}])]

        tool_uses = [e for e in events if e["type"] == "tool_use"]
        assert tool_uses and tool_uses[0]["name"] == "browser_goto"
        assert tool_uses[0]["input"] == {"url": "https://example.com"}
        done = [e for e in events if e["type"] == "done"]
        assert done[0]["stop_reason"] == "tool_use"

    async def test_astream_recovers_text_tool_call(self, monkeypatch: pytest.MonkeyPatch):
        """Ollama-style: tool call emitted as plain JSON in the content stream."""
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        json_text = '{"name": "open_app", "arguments": {"name": "Safari"}}'

        async def _stream():
            # Split mid-JSON to prove accumulation across chunks.
            mid = len(json_text) // 2
            yield _FakeStreamChunk([_FakeChoice(_FakeDelta(json_text[:mid]))])
            yield _FakeStreamChunk([_FakeChoice(_FakeDelta(json_text[mid:]), finish_reason="stop")])

        async def _acompletion_impl(**kwargs: Any):
            return _stream()

        fake = MagicMock()
        fake.acompletion.side_effect = _acompletion_impl
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                events = [e async for e in LiteLLMRouter().astream([{"role": "user", "content": "open safari"}])]

        tool_uses = [e for e in events if e["type"] == "tool_use"]
        assert tool_uses and tool_uses[0]["name"] == "open_app"
        assert tool_uses[0]["input"] == {"name": "Safari"}
        # The raw JSON must never reach the user as a token.
        assert all(e["type"] != "token" for e in events)
        done = [e for e in events if e["type"] == "done"]
        assert done[0]["stop_reason"] == "tool_use"

    async def test_astream_malformed_text_tool_call_flushes_as_text(self, monkeypatch: pytest.MonkeyPatch):
        """A held JSON-looking buffer that never becomes a tool call is emitted."""
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")

        async def _stream():
            yield _FakeStreamChunk([_FakeChoice(_FakeDelta('{"type": "thought", "x": 1}'), finish_reason="stop")])

        async def _acompletion_impl(**kwargs: Any):
            return _stream()

        fake = MagicMock()
        fake.acompletion.side_effect = _acompletion_impl
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                events = [e async for e in LiteLLMRouter().astream([{"role": "user", "content": "hi"}])]

        tokens = [e for e in events if e["type"] == "token"]
        assert tokens and "thought" in tokens[0]["text"]


# ===========================================================================
# Timeout handling (LLM_TIMEOUT)
# ===========================================================================


class TestTimeout:
    def test_timeout_propagated_to_litellm(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_TIMEOUT", "30")
        ok = MagicMock()
        ok.choices[0].message.content = "ok"
        fake = MagicMock()
        fake.completion.return_value = ok
        with patch("modules.llm.router.api_key_for_model", return_value="sk-test"):
            with patch.dict("sys.modules", {"litellm": fake}):
                LiteLLMRouter().complete_sync([{"role": "user", "content": "hi"}])
        assert fake.completion.call_args.kwargs["timeout"] == 30

    async def test_timeout_triggers_fallback(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")

        async def _acompletion_impl(**kwargs: Any):
            if kwargs["model"] == "gpt-4o":
                raise TimeoutError("request timed out")
            resp = MagicMock()
            resp.choices[0].message.content = "fallback after timeout"
            resp.choices[0].finish_reason = "stop"
            resp.choices[0].message.tool_calls = None
            return resp

        fake = MagicMock()
        fake.acompletion.side_effect = _acompletion_impl
        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            with patch.dict("sys.modules", {"litellm": fake}):
                result = await LiteLLMRouter().acomplete([{"role": "user", "content": "hi"}])
        assert result["content"] == "fallback after timeout"


# ===========================================================================
# Fallback recorder (on_fallback hook)
# ===========================================================================


class TestFallbackRecorder:
    def test_records_fallback_attempts(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        events: list[dict] = []
        ok = MagicMock()
        ok.choices[0].message.content = "fallback ok"
        fake = MagicMock()
        fake.completion.side_effect = [Exception("provider down"), ok]
        with patch("modules.llm.router.api_key_for_model", side_effect=_KeyPatch.resolve):
            with patch.dict("sys.modules", {"litellm": fake}):
                router = LiteLLMRouter(on_fallback=events.append)
                assert router.complete_sync([{"role": "user", "content": "hi"}]) == "fallback ok"
        assert len(events) == 1
        assert events[0]["model"] == "gpt-4o"
        assert events[0]["provider"] == "cloud"
        assert events[0]["attempt_index"] == 1
        assert events[0]["total"] == 2
        assert "down" in events[0]["reason"]

    def test_reason_scrubs_api_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        events: list[dict] = []
        ok = MagicMock()
        ok.choices[0].message.content = "ok"
        fake = MagicMock()
        fake.completion.side_effect = [
            Exception("401 invalid key sk-or-v1-TOP-SECRET"),
            ok,
        ]
        with patch("modules.llm.router.api_key_for_model", return_value="sk-or-v1-TOP-SECRET"):
            with patch.dict("sys.modules", {"litellm": fake}):
                LiteLLMRouter(on_fallback=events.append).complete_sync([{"role": "user", "content": "hi"}])
        assert events
        assert "sk-or-v1-TOP-SECRET" not in events[0]["reason"]
        assert "***" in events[0]["reason"]
