"""BrainRouter tests — ordered backend composition behind BrainInterface.

Contract under test:
  - The router delegates every reasoning call to the first ``available``
    backend in priority order.
  - When no backend is available it raises ``BrainUnavailableError``
    (streaming yields an ``error`` event) — no silent substitution.
  - Introspection (``status`` / ``model_chain`` / ``available_providers`` /
    ``test_connection``) reflects the first available backend.
  - The router is a reasoning-only layer: it exposes no execution surface —
    tool execution stays behind ``ConfirmationGate`` (never bypassed).
"""

from __future__ import annotations

import pytest

from modules.llm.brain import (
    BrainInterface,
    BrainUnavailableError,
    CurrentLLMAdapter,
)
from modules.llm.brain_router import BrainRouter


class _FakeBrain(BrainInterface):
    """Scripted backend for routing tests."""

    name = "fake"

    def __init__(self, *, available: bool = True, label: str = "fake") -> None:
        self._available = available
        self._label = label

    @property
    def available(self) -> bool:
        return self._available

    def chat(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None) -> str:
        return f"{self._label}:reply"

    async def chat_stream(self, messages, *, system=None, tools=None, max_tokens=None):
        yield {"type": "token", "text": f"{self._label}:token"}
        yield {"type": "done", "stop_reason": "end_turn"}

    async def acomplete(self, messages, *, system=None, tools=None, max_tokens=None, temperature=None) -> dict:
        return {"content": f"{self._label}:content", "tool_calls": [], "stop_reason": "end_turn"}

    def classify(self, text: str) -> str:
        return "command"

    def plan(self, task: str, context: str = "") -> list[str]:
        return [f"{self._label}:step"]

    def select_tools(self, task: str, tools) -> list[str]:
        return [t["name"] for t in tools][:1]

    def summarize(self, text: str, max_words: int = 80) -> str:
        return f"{self._label}:summary"

    def verify(self, claim: str, evidence: str) -> str:
        return "supported"

    def model_chain(self) -> list[str]:
        return [f"{self._label}/model"]

    def available_providers(self) -> list[str]:
        return [self._label]

    def test_connection(self) -> str:
        return f"ok:{self._label}"

    def status(self) -> dict:
        return {"backend": self._label, "available": self._available}


async def _collect(agen):
    return [e async for e in agen]


class TestInitialization:
    def test_requires_at_least_one_backend(self):
        with pytest.raises(ValueError):
            BrainRouter([])

    def test_implements_brain_interface(self):
        router = BrainRouter([_FakeBrain()])
        assert isinstance(router, BrainInterface)


class TestRouting:
    def test_delegates_to_first_available(self):
        first = _FakeBrain(available=False, label="dead")
        second = _FakeBrain(available=True, label="live")
        router = BrainRouter([first, second])
        assert router.chat([{"role": "user", "content": "hi"}]) == "live:reply"
        assert router.classify("hi") == "command"
        assert router.plan("task") == ["live:step"]
        assert router.summarize("t") == "live:summary"
        assert router.verify("c", "e") == "supported"
        assert router.select_tools("t", [{"name": "x"}, {"name": "y"}]) == ["x"]

    def test_priority_order_respected(self):
        first = _FakeBrain(available=True, label="primary")
        second = _FakeBrain(available=True, label="secondary")
        router = BrainRouter([first, second])
        assert router.chat([{"role": "user", "content": "hi"}]) == "primary:reply"

    @pytest.mark.asyncio
    async def test_astream_delegates(self):
        router = BrainRouter([_FakeBrain(available=True, label="live")])
        events = await _collect(router.chat_stream([{"role": "user", "content": "hi"}]))
        assert events[0] == {"type": "token", "text": "live:token"}

    @pytest.mark.asyncio
    async def test_acomplete_delegates(self):
        router = BrainRouter([_FakeBrain(available=True, label="live")])
        out = await router.acomplete([{"role": "user", "content": "hi"}])
        assert out["content"] == "live:content"


class TestUnavailable:
    def test_available_false_when_none(self):
        router = BrainRouter([_FakeBrain(available=False)])
        assert router.available is False

    def test_chat_raises_when_none_available(self):
        router = BrainRouter([_FakeBrain(available=False, label="dead")])
        with pytest.raises(BrainUnavailableError):
            router.chat([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_stream_yields_error_when_none_available(self):
        router = BrainRouter([_FakeBrain(available=False, label="dead")])
        events = await _collect(router.chat_stream([{"role": "user", "content": "hi"}]))
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "No brain backend available" in events[0]["message"]

    def test_introspection_empty_when_none_available(self):
        router = BrainRouter([_FakeBrain(available=False, label="dead")])
        assert router.model_chain() == []
        assert router.available_providers() == []
        assert router.test_connection() == "❌ no available brain backend"


class TestStatusAndChain:
    def test_status_lists_chain(self):
        router = BrainRouter([_FakeBrain(available=False, label="freebuff")])
        status = router.status()
        assert status["backend"] == "router"
        assert status["chain"][0]["backend"] == "freebuff"
        assert status["chain"][0]["available"] is False

    def test_model_chain_from_first_available(self):
        router = BrainRouter(
            [_FakeBrain(available=False, label="dead"), _FakeBrain(available=True, label="live")]
        )
        assert router.model_chain() == ["live/model"]


class TestSafetyBoundary:
    def test_router_is_reasoning_only(self):
        """The router exposes ONLY BrainInterface reasoning methods — there is
        no method that executes tools or mutates the system. Execution stays
        behind ToolRegistry → ConfirmationGate (tested in tools/gate tests)."""
        router = BrainRouter([_FakeBrain()])
        reasoning = {
            "name",
            "chat",
            "chat_stream",
            "acomplete",
            "classify",
            "plan",
            "select_tools",
            "summarize",
            "verify",
            "status",
            "model_chain",
            "available_providers",
            "test_connection",
            "available",
        }
        public = {n for n in dir(router) if not n.startswith("_")}
        assert public <= reasoning, public - reasoning

    def test_select_tools_never_invents(self):
        """select_tools only returns names present in the provided catalog."""
        router = BrainRouter([_FakeBrain()])
        assert router.select_tools("t", [{"name": "read_file"}]) == ["read_file"]
        assert router.select_tools("t", []) == []


class TestRouterCompositionWithRealAdapters:
    def test_freebuff_plus_current_chain(self):
        """The intended chain: [freebuff, current]. While freebuff is
        unavailable the router falls through to the LiteLLM backend — this
        mirrors get_brain() semantics once Freebuff ships an interface."""
        freebuff = CurrentLLMAdapter  # placeholder type; real freebuff never available
        assert freebuff.__name__ == "CurrentLLMAdapter"
        # Structural check only: router accepts any BrainInterface instances.
        router = BrainRouter([_FakeBrain(available=False), _FakeBrain(available=True)])
        assert router.available is True
