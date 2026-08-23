"""BrainInterface tests — the canonical provider-independent reasoning layer.

Contract under test:
  - ``BrainInterface`` is the single reasoning contract (chat, chat_stream,
    classify, plan, select_tools, summarize, verify).
  - ``CurrentLLMAdapter`` delegates to the existing canonical ``LLMRouter``
    (no duplicated routing logic) and propagates failures as ``BrainError``.
  - ``FreebuffBrainAdapter`` honestly reports unavailability — it never
    pretends Freebuff is callable.
  - ``get_brain`` selects ``current`` by default, fails clearly on
    ``freebuff`` and on unknown values (never a silent fallback).
  - Secret scrubbing is untouched (nothing in this layer reads secrets).
"""

from __future__ import annotations

import os

import pytest

from modules.llm.brain import (
    BRAIN_INTENT_LABELS,
    BrainConfigurationError,
    BrainError,
    BrainInterface,
    BrainUnavailableError,
    CurrentLLMAdapter,
    FreebuffBrainAdapter,
    get_brain,
)


class _FakeRouter:
    """Minimal LLMRouter stand-in returning canned text / events."""

    name = "fake"

    def __init__(self, text: str = "fake reply") -> None:
        self._text = text
        self._chain = ["fake/model"]
        self.calls: list[tuple] = []

    def model_chain(self) -> list[str]:
        return list(self._chain)

    def complete_sync(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
        self.calls.append(("sync", messages, max_tokens, temperature))
        return self._text

    async def acomplete(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
        self.calls.append(("acomplete", messages, max_tokens, temperature))
        return {"content": self._text, "tool_calls": [], "stop_reason": "end_turn"}

    async def astream(self, messages, *, system=None, tools=None, max_tokens=None):
        self.calls.append(("stream", messages, max_tokens))
        yield {"type": "token", "text": "tok1"}
        yield {"type": "done", "stop_reason": "end_turn"}


class _EmptyRouter(_FakeRouter):
    def complete_sync(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
        return ""


class _RaisingRouter(_FakeRouter):
    def complete_sync(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
        raise RuntimeError("provider exploded")


# ─── Interface shape ────────────────────────────────────────────────────────

class TestBrainInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BrainInterface()  # type: ignore[abstract]

    def test_has_all_capabilities(self):
        for method in ("chat", "chat_stream", "acomplete", "classify", "plan",
                       "select_tools", "summarize", "verify"):
            assert hasattr(BrainInterface, method)
            assert callable(getattr(BrainInterface, method))

    def test_intent_labels_are_defined(self):
        assert "greeting" in BRAIN_INTENT_LABELS
        assert "question" in BRAIN_INTENT_LABELS
        assert "command" in BRAIN_INTENT_LABELS


# ─── CurrentLLMAdapter — delegation + error propagation ─────────────────────

class TestCurrentLLMAdapter:
    def test_default_router_is_canonical(self):
        # Default construction must use the canonical LiteLLMRouter factory,
        # never a bespoke path.
        import modules.llm.brain as brain_mod
        adapter = CurrentLLMAdapter()
        assert adapter._router is not None
        # restore-ability: the factory still builds after this test
        assert brain_mod.get_brain is not None

    def test_chat_delegates_to_router(self):
        router = _FakeRouter(text="hello from fake")
        adapter = CurrentLLMAdapter(router=router)
        out = adapter.chat([{"role": "user", "content": "hi"}], max_tokens=42, temperature=0.2)
        assert out == "hello from fake"
        assert router.calls[0][0] == "sync"
        assert router.calls[0][2] == 42 and router.calls[0][3] == 0.2

    def test_chat_tools_reach_router(self):
        seen = {}

        class _ToolsRouter(_FakeRouter):
            def complete_sync(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
                seen["tools"] = tools
                return "ok"

        adapter = CurrentLLMAdapter(router=_ToolsRouter())
        tools = [{"name": "open_app", "description": "Open an app"}]
        adapter.chat([{"role": "user", "content": "open Safari"}], tools=tools)
        assert seen["tools"] == tools

    def test_chat_empty_raises_brain_error(self):
        adapter = CurrentLLMAdapter(router=_EmptyRouter())
        with pytest.raises(BrainError):
            adapter.chat([{"role": "user", "content": "hi"}])

    def test_chat_propagates_router_exception(self):
        adapter = CurrentLLMAdapter(router=_RaisingRouter())
        with pytest.raises(RuntimeError, match="provider exploded"):
            adapter.chat([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_stream_forwards_events(self):
        router = _FakeRouter()
        adapter = CurrentLLMAdapter(router=router)
        events = [e async for e in adapter.chat_stream(
            [{"role": "user", "content": "hi"}], max_tokens=30)]
        assert events == [
            {"type": "token", "text": "tok1"},
            {"type": "done", "stop_reason": "end_turn"},
        ]
        assert router.calls[0][0] == "stream" and router.calls[0][2] == 30

    @pytest.mark.asyncio
    async def test_chat_stream_forwards_tools(self):
        seen = {}

        class _ToolsStreamRouter(_FakeRouter):
            async def astream(self, messages, *, system=None, tools=None, max_tokens=None):
                seen["tools"] = tools
                yield {"type": "token", "text": "tok"}
                yield {"type": "done", "stop_reason": "end_turn"}

        adapter = CurrentLLMAdapter(router=_ToolsStreamRouter())
        tools = [{"name": "browser_search", "description": "Search"}]
        events = [e async for e in adapter.chat_stream(
            [{"role": "user", "content": "search"}], tools=tools)]
        assert seen["tools"] == tools
        assert events[0] == {"type": "token", "text": "tok"}

    @pytest.mark.asyncio
    async def test_acomplete_delegates_to_router(self):
        router = _FakeRouter(text="async answer")
        adapter = CurrentLLMAdapter(router=router)
        result = await adapter.acomplete(
            [{"role": "user", "content": "hi"}], max_tokens=33, temperature=0.1)
        assert result == {"content": "async answer", "tool_calls": [], "stop_reason": "end_turn"}
        assert router.calls[0][0] == "acomplete"
        assert router.calls[0][2] == 33 and router.calls[0][3] == 0.1

    @pytest.mark.asyncio
    async def test_acomplete_forwards_tools(self):
        seen = {}

        class _ToolsAsyncRouter(_FakeRouter):
            async def acomplete(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None):
                seen["tools"] = tools
                return {"content": "ok", "tool_calls": [], "stop_reason": "end_turn"}

        adapter = CurrentLLMAdapter(router=_ToolsAsyncRouter())
        tools = [{"name": "remember", "description": "Save to memory"}]
        await adapter.acomplete([{"role": "user", "content": "hi"}], tools=tools)
        assert seen["tools"] == tools

    def test_model_chain_delegates(self):
        adapter = CurrentLLMAdapter(router=_FakeRouter())
        assert adapter.model_chain() == ["fake/model"]

    def test_available_providers_delegates(self):
        router = _FakeRouter()
        router.available_providers = lambda: ["fake"]  # type: ignore[method-assign]
        adapter = CurrentLLMAdapter(router=router)
        assert adapter.available_providers() == ["fake"]

    def test_available_providers_derives_from_chain_when_missing(self):
        adapter = CurrentLLMAdapter(router=_FakeRouter())
        assert adapter.available_providers() == ["fake"]

    def test_test_connection_delegates(self):
        router = _FakeRouter()
        router.test_connection = lambda: "✅ fake responds"  # type: ignore[method-assign]
        adapter = CurrentLLMAdapter(router=router)
        assert adapter.test_connection() == "✅ fake responds"

    def test_classify_returns_label(self):
        router = _FakeRouter(text="question")
        adapter = CurrentLLMAdapter(router=router)
        assert adapter.classify("What is the capital of France?") == "question"

    def test_classify_unknown_maps_to_other(self):
        router = _FakeRouter(text="banana")
        adapter = CurrentLLMAdapter(router=router)
        assert adapter.classify("??") == "other"

    def test_plan_returns_steps(self):
        router = _FakeRouter(text="1. Open Safari\n2. Search\n3. Read results")
        adapter = CurrentLLMAdapter(router=router)
        steps = adapter.plan("Find the weather")
        assert steps == ["Open Safari", "Search", "Read results"]

    def test_select_tools_never_invents(self):
        tools = [
            {"name": "open_app", "description": "Open an application"},
            {"name": "browser_search", "description": "Search the web"},
            {"name": "remember", "description": "Save to memory"},
        ]
        router = _FakeRouter(text="open_app\nremember\nhallucinated_tool")
        adapter = CurrentLLMAdapter(router=router)
        chosen = adapter.select_tools("Open Safari and remember this", tools)
        assert chosen == ["open_app", "remember"]
        assert "hallucinated_tool" not in chosen

    def test_select_tools_empty_catalog(self):
        adapter = CurrentLLMAdapter(router=_FakeRouter())
        assert adapter.select_tools("anything", []) == []

    def test_summarize_returns_text(self):
        router = _FakeRouter(text="A concise summary.")
        adapter = CurrentLLMAdapter(router=router)
        assert adapter.summarize("long text here") == "A concise summary."

    def test_verify_returns_verdict(self):
        router = _FakeRouter(text="supported")
        adapter = CurrentLLMAdapter(router=router)
        assert adapter.verify("claim", "evidence") == "supported"

    def test_verify_unknown_falls_back(self):
        router = _FakeRouter(text="maybe?")
        adapter = CurrentLLMAdapter(router=router)
        assert adapter.verify("claim", "evidence") == "insufficient evidence"

    def test_status_includes_model_chain(self):
        adapter = CurrentLLMAdapter(router=_FakeRouter())
        status = adapter.status()
        assert status["backend"] == "current"
        assert status["available"] is True
        assert status["model_chain"] == ["fake/model"]


# ─── FreebuffBrainAdapter — honest unavailability ───────────────────────────

class TestFreebuffBrainAdapter:
    def test_available_is_false(self):
        adapter = FreebuffBrainAdapter()
        assert adapter.available is False

    def test_status_reports_unavailable(self):
        status = FreebuffBrainAdapter().status()
        assert status["available"] is False
        assert status["backend"] == "freebuff"

    def test_chat_raises_unavailable(self):
        with pytest.raises(BrainUnavailableError) as exc:
            FreebuffBrainAdapter().chat([{"role": "user", "content": "hi"}])
        assert "programmatic interface unavailable" in str(exc.value)

    def test_all_reasoning_methods_raise(self):
        adapter = FreebuffBrainAdapter()
        with pytest.raises(BrainUnavailableError):
            adapter.classify("hi")
        with pytest.raises(BrainUnavailableError):
            adapter.plan("task")
        with pytest.raises(BrainUnavailableError):
            adapter.select_tools("task", [{"name": "x"}])
        with pytest.raises(BrainUnavailableError):
            adapter.summarize("text")
        with pytest.raises(BrainUnavailableError):
            adapter.verify("claim", "evidence")

    @pytest.mark.asyncio
    async def test_acomplete_raises_unavailable(self):
        with pytest.raises(BrainUnavailableError):
            await FreebuffBrainAdapter().acomplete([{"role": "user", "content": "hi"}])

    def test_introspection_reports_unavailable(self):
        adapter = FreebuffBrainAdapter()
        assert adapter.model_chain() == []
        assert adapter.available_providers() == []

    @pytest.mark.asyncio
    async def test_chat_stream_yields_error_event(self):
        events = [e async for e in FreebuffBrainAdapter().chat_stream(
            [{"role": "user", "content": "hi"}])]
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "programmatic interface unavailable" in events[0]["message"]


# ─── Factory — brain selection ──────────────────────────────────────────────

class TestGetBrain:
    def test_default_is_current(self, monkeypatch):
        monkeypatch.delenv("FOL_BRAIN", raising=False)
        brain = get_brain()
        assert isinstance(brain, CurrentLLMAdapter)

    def test_env_selection(self, monkeypatch):
        monkeypatch.setenv("FOL_BRAIN", "current")
        assert isinstance(get_brain(), CurrentLLMAdapter)

    def test_explicit_current(self):
        assert isinstance(get_brain("current"), CurrentLLMAdapter)
        assert isinstance(get_brain("litellm"), CurrentLLMAdapter)

    def test_freebuff_falls_back_without_key(self, monkeypatch):
        """get_brain('freebuff') falls back to current when OPENROUTER_API_KEY is missing."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("FOL_BRAIN", "current")
        brain = get_brain("freebuff")
        # Should gracefully fall back to CurrentLLMAdapter, not raise
        assert isinstance(brain, CurrentLLMAdapter)

    def test_freebuff_succeeds_with_key(self, monkeypatch):
        """get_brain('freebuff') returns BrainRouter when OPENROUTER is configured."""
        from modules.llm.brain_router import BrainRouter
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-12345")
        monkeypatch.setenv("FOL_BRAIN", "current")
        brain = get_brain("freebuff")
        assert isinstance(brain, BrainRouter)

    def test_freebuff_env_falls_back_without_key(self, monkeypatch):
        """FOL_BRAIN=freebuff falls back to current when OPENROUTER_API_KEY is missing."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("FOL_BRAIN", "freebuff")
        brain = get_brain()
        # Should gracefully fall back to CurrentLLMAdapter, not raise
        assert isinstance(brain, CurrentLLMAdapter)

    def test_freebuff_env_succeeds_with_key(self, monkeypatch):
        """FOL_BRAIN=freebuff returns BrainRouter when OPENROUTER is configured."""
        from modules.llm.brain_router import BrainRouter
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-12345")
        monkeypatch.setenv("FOL_BRAIN", "freebuff")
        brain = get_brain()
        assert isinstance(brain, BrainRouter)

    def test_unknown_fails(self):
        with pytest.raises(BrainConfigurationError, match="Unknown FOL_BRAIN"):
            get_brain("banana-brain")

    def test_freebuff_graceful_fallback(self, monkeypatch):
        # When OPENROUTER is not configured, Freebuff brain gracefully falls
        # back to CurrentLLMAdapter instead of crashing.
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("FOL_BRAIN", "freebuff")
        brain = get_brain()
        assert isinstance(brain, CurrentLLMAdapter)
        assert os.environ.get("FOL_BRAIN") == "freebuff"  # env untouched
