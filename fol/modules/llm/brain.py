"""Brain Interface — canonical provider-independent reasoning abstraction.

Architecture goal (additive — nothing existing is replaced yet):

    FOL
     ↓
    BrainInterface          (this module)
     ↓
    CurrentLLMAdapter  OR  FreebuffBrainAdapter (future, disabled)
     ↓
    LiteLLMRouter          (current runtime backend — unchanged)
     ↓
    ToolRegistry → ConfirmationGate → Execution → ObsidianMemory

``BrainInterface`` is the ONE internal reasoning contract. Every higher-level
capability (chat, streaming, classification, planning, tool selection,
summarization, verification) goes through it. The concrete backend behind it
is chosen by :func:`get_brain` from the ``FOL_BRAIN`` environment variable.

Backends
--------
- ``current`` (default) — :class:`CurrentLLMAdapter`, a thin delegate over the
  existing canonical ``LLMRouter`` (LiteLLM: OpenRouter/Ollama/MLX/…). It
  duplicates NO LLM logic — routing, fallback chains and backends stay exactly
  where they are today.
- ``freebuff_tmux`` — :class:`FreebuffTmuxBridge`, Freebuff CLI running inside
  a persistent tmux session. Uses ``tmux capture-pane`` for reliable TUI output
  parsing. Fallback to ``current`` on failure.
- ``freebuff`` — Freebuff models accessed via OpenRouter.
- ``freebuff_cli`` — DEPRECATED: PTY-based, fundamentally broken for React TUIs.

Memory is deliberately OUT of this interface: the brain reasons, the
``MemoryService`` (Obsidian) stores. Secret scrubbing in memory is preserved
unchanged.
"""

from __future__ import annotations

import abc
import logging
import os
from typing import Any, AsyncIterator

from modules.llm.freebuff import FREEBUFF_REQUIREMENTS, freebuff_config
from modules.llm.router import LLMRouter, get_llm_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BrainError(RuntimeError):
    """A brain operation failed (all backends returned nothing / raised)."""


class BrainConfigurationError(BrainError):
    """Invalid or unavailable brain backend selection (e.g. FOL_BRAIN=freebuff)."""


class BrainUnavailableError(BrainError):
    """The selected backend cannot be called at all (Freebuff placeholder)."""


# ---------------------------------------------------------------------------
# Canonical intent labels (used by BrainInterface.classify)
# ---------------------------------------------------------------------------

BRAIN_INTENT_LABELS = (
    "greeting",
    "question",
    "command",
    "memory",
    "search",
    "email_calendar",
    "casual",
    "other",
)


# ---------------------------------------------------------------------------
# BrainInterface
# ---------------------------------------------------------------------------


class BrainInterface(abc.ABC):
    """Canonical reasoning abstraction.

    Implementations are interchangeable backends behind one contract. The
    contract is deliberately small: reasoning only, never memory, never tools.

    - ``chat`` / ``chat_stream`` / ``acomplete`` — conversational completion.
    - ``classify``               — intent label (see BRAIN_INTENT_LABELS).
    - ``plan``                   — step-by-step plan for a task.
    - ``select_tools``           — pick tool names from a provided list.
    - ``summarize``              — concise summary of text.
    - ``verify``                 — verdict on a claim against evidence.
    """

    name: str = "base"

    @property
    def available(self) -> bool:
        """True when this backend can actually be called right now."""
        return True

    def status(self) -> dict[str, Any]:
        """Human-readable backend status (never contains secrets)."""
        return {"backend": self.name, "available": self.available}

    # -- introspection (non-abstract; backends override when meaningful) -----

    def model_chain(self) -> list[str]:
        """Ordered models this backend would try (empty when unavailable)."""
        return []

    def available_providers(self) -> list[str]:
        """Human-readable provider list (empty when unavailable)."""
        return []

    def test_connection(self) -> str:
        """Quick connectivity probe — never raises."""
        return f"❌ Brain backend '{self.name}' is not callable."

    # -- conversational -----------------------------------------------------

    @abc.abstractmethod
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Complete a conversation. Returns text; raises BrainError on failure."""

    @abc.abstractmethod
    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream completion. Yields the router event contract:
        ``{"type": "token", "text"}`` / ``{"type": "tool_use", ...}`` /
        ``{"type": "done", "stop_reason"}`` / ``{"type": "error", "message"}``."""

    @abc.abstractmethod
    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Async completion. Returns ``{"content", "tool_calls", "stop_reason"}``."""

    # -- reasoning capabilities --------------------------------------------

    @abc.abstractmethod
    def classify(self, text: str) -> str:
        """Return an intent label from BRAIN_INTENT_LABELS."""

    @abc.abstractmethod
    def plan(self, task: str, context: str = "") -> list[str]:
        """Return an ordered list of steps for ``task``."""

    @abc.abstractmethod
    def select_tools(
        self, task: str, tools: list[dict[str, Any]]
    ) -> list[str]:
        """Return the names of the tools (from ``tools``) needed for ``task``.
        Never invents tools: only names present in ``tools`` are returned."""

    @abc.abstractmethod
    def summarize(self, text: str, max_words: int = 80) -> str:
        """Return a concise summary of ``text``."""

    @abc.abstractmethod
    def verify(self, claim: str, evidence: str) -> str:
        """Return a verdict: one of ``supported``, ``partially supported``,
        ``unsupported``, ``insufficient evidence``."""


# ---------------------------------------------------------------------------
# Current runtime backend — thin delegate over the canonical LLMRouter
# ---------------------------------------------------------------------------


class CurrentLLMAdapter(BrainInterface):
    """The working brain: delegates every call to the existing canonical
    ``LLMRouter`` (LiteLLM chain). Adds zero routing/fallback logic — that
    all stays in ``modules.llm.router`` / the backends."""

    name = "current"

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router: LLMRouter = router if router is not None else get_llm_router("litellm")

    @property
    def available(self) -> bool:
        return bool(self._router.model_chain())

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.available,
            "model_chain": self.model_chain(),
        }

    # -- introspection ------------------------------------------------------

    def model_chain(self) -> list[str]:
        return self._router.model_chain()

    def available_providers(self) -> list[str]:
        fn = getattr(self._router, "available_providers", None)
        if callable(fn):
            return fn()
        return sorted({m.split("/", 1)[0] for m in self.model_chain() if m})

    def test_connection(self) -> str:
        fn = getattr(self._router, "test_connection", None)
        if callable(fn):
            return fn()
        return "✅ configured" if self.model_chain() else "❌ no configured model"

    # -- conversational -----------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        text = self._router.complete_sync(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not text:
            raise BrainError(
                "All configured LLM backends failed to produce a response."
            )
        return text

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self._router.astream(
            messages, system=system, tools=tools, max_tokens=max_tokens
        ):
            yield event

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        return await self._router.acomplete(
            messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    # -- reasoning capabilities (thin prompt wrappers over the same router) --

    def classify(self, text: str) -> str:
        labels = ", ".join(BRAIN_INTENT_LABELS)
        out = self.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"Classify the user request into exactly one label: "
                        f"{labels}.\nRequest: {text}\nAnswer with one label only."
                    ),
                }
            ],
            max_tokens=10,
            temperature=0,
        )
        label = out.strip().strip(".").strip().lower()
        for candidate in BRAIN_INTENT_LABELS:
            if candidate in label:
                return candidate
        return "other"

    def plan(self, task: str, context: str = "") -> list[str]:
        ctx = f"\nContext:\n{context}" if context else ""
        out = self.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"Plan how to accomplish the task. Return a concise "
                        f"numbered list of steps (one step per line). Do not "
                        f"invent capabilities.\nTask: {task}{ctx}"
                    ),
                }
            ],
            max_tokens=200,
        )
        steps = [
            line.strip().lstrip("0123456789.)-").strip()
            for line in out.splitlines()
            if line.strip()
        ]
        return [s for s in steps if s]

    def select_tools(
        self, task: str, tools: list[dict[str, Any]]
    ) -> list[str]:
        known = {str(t.get("name", "")).strip() for t in tools if t.get("name")}
        if not known:
            return []
        catalog = "\n".join(
            f"- {t.get('name')}: {t.get('description', '')}"
            for t in tools
            if t.get("name")
        )
        out = self.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"Choose the tools needed for this task. Reply with "
                        f"only the tool names, one per line.\nTask: {task}\n"
                        f"Available tools:\n{catalog}"
                    ),
                }
            ],
            max_tokens=60,
            temperature=0,
        )
        # Never invent tools: only names that actually exist are returned.
        return [
            name
            for line in out.splitlines()
            if (name := line.strip().strip("*`").strip()) in known
        ]

    def summarize(self, text: str, max_words: int = 80) -> str:
        out = self.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"Summarize the following in at most {max_words} words, "
                        f"in the same language as the text. Keep key facts.\n\n{text}"
                    ),
                }
            ],
            max_tokens=max_words * 2,
        )
        return out.strip()

    def verify(self, claim: str, evidence: str) -> str:
        out = self.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"Verdict on whether the evidence supports the claim. "
                        f"Reply with exactly one of: supported, partially "
                        f"supported, unsupported, insufficient evidence.\n"
                        f"Claim: {claim}\nEvidence: {evidence}"
                    ),
                }
            ],
            max_tokens=10,
            temperature=0,
        )
        low = out.strip().strip(".").strip().lower()
        for verdict in (
            "partially supported",
            "insufficient evidence",
            "supported",
            "unsupported",
        ):
            if verdict in low:
                return verdict
        return "insufficient evidence"


# ---------------------------------------------------------------------------
# Freebuff — future backend, honestly unavailable today
# ---------------------------------------------------------------------------


class FreebuffBrainAdapter(BrainInterface):
    """Honest Freebuff backend behind :class:`BrainInterface`.

    Audited 2026-08-17: Freebuff has no supported programmatic interface
    (CLI is an interactive TUI; no public HTTP API / server / socket).
    This adapter therefore MUST NOT pretend Freebuff is callable: every
    reasoning method raises :class:`BrainUnavailableError` (streaming yields
    an ``error`` event), and it never contacts invented endpoints or touches
    undocumented auth tokens.

    Configuration (``FREEBUFF_API_URL`` / ``FREEBUFF_API_TOKEN`` /
    ``FREEBUFF_TIMEOUT``) is read from the environment at the adapter
    boundary — never passed through FOL Core — and is reported in
    ``status()``. It is documentation until an official interface ships.
    """

    name = "freebuff"

    def __init__(self, *, config: dict[str, str] | None = None) -> None:
        self._config: dict[str, str] = dict(config or freebuff_config())

    @property
    def available(self) -> bool:
        return False

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": False,
            "reason": "No supported programmatic interface (audited 2026-08-17).",
            "configured": bool(self._config.get("api_url"))
            or bool(self._config.get("api_token")),
        }

    def _unavailable(self) -> None:
        raise BrainUnavailableError(FREEBUFF_REQUIREMENTS)

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        self._unavailable()

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "error", "message": FREEBUFF_REQUIREMENTS}

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        self._unavailable()

    def classify(self, text: str) -> str:
        self._unavailable()

    def plan(self, task: str, context: str = "") -> list[str]:
        self._unavailable()

    def select_tools(
        self, task: str, tools: list[dict[str, Any]]
    ) -> list[str]:
        self._unavailable()

    def summarize(self, text: str, max_words: int = 80) -> str:
        self._unavailable()

    def verify(self, claim: str, evidence: str) -> str:
        self._unavailable()


# ---------------------------------------------------------------------------
# Factory — one canonical brain selection
# ---------------------------------------------------------------------------


def get_brain(name: str | None = None, *, router: LLMRouter | None = None) -> BrainInterface:
    """Select the canonical brain.

    Resolution order: explicit ``name`` → ``FOL_BRAIN`` env → ``current``.

    - ``current`` / ``local`` / ``litellm`` → :class:`CurrentLLMAdapter`.
    - ``freebuff`` → raises :class:`BrainConfigurationError` (the user
      explicitly asked for a backend that does not exist yet — never silently
      fall back to another brain).
    - anything else → :class:`BrainConfigurationError`.
    """
    cfg = (name or os.environ.get("FOL_BRAIN", "") or "current").strip().lower()

    if cfg in ("current", "local", "litellm", "llm"):
        return CurrentLLMAdapter(router=router)

    if cfg in ("freebuff", "freebuff_adapter", "freebuffbrain"):
        # Freebuff via OpenRouter — models accessed through OpenRouter API.
        # Uses key pool for automatic rotation across multiple API keys.
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter
        from modules.llm.brain_router import BrainRouter

        adapter = FreebuffBrainAdapter()
        if adapter.available:
            # Freebuff primary, LiteLLM fallback
            return BrainRouter([adapter, CurrentLLMAdapter(router=router)])
        # Freebuff unavailable — fall back to current brain instead of crashing
        logger.warning(
            "Freebuff brain unavailable (no OPENROUTER_API_KEY). "
            "Falling back to current brain."
        )
        return CurrentLLMAdapter(router=router)

    if cfg in ("freebuff_auto", "freebuff-auto", "freebuffautostart"):
        # Freebuff auto-start — launches Freebuff CLI in background.
        # Falls back to current LLM on failure.
        from modules.brain.freebuff_autostart import FreebuffAutoStartBridge
        from modules.llm.brain_router import BrainRouter

        bridge = FreebuffAutoStartBridge()
        if bridge.available:
            return BrainRouter([bridge, CurrentLLMAdapter(router=router)])
        # Freebuff binary not found — fall back to current brain
        logger.warning(
            "Freebuff auto-start unavailable (binary not found). "
            "Falling back to current brain."
        )
        return CurrentLLMAdapter(router=router)

    if cfg in ("freebuff_cli", "freebuff-pty", "freebuffpty"):
        # Freebuff CLI via PTY — DEPRECATED: TUI parsing is fundamentally
        # broken for React-based TUIs. Use freebuff_tmux instead.
        import warnings
        warnings.warn(
            "FOL_BRAIN=freebuff_cli is deprecated and unreliable. "
            "Use FOL_BRAIN=freebuff_tmux instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from modules.llm.brain_router import BrainRouter
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI

        bridge = FreebuffBridgeCLI()
        if not bridge.available:
            raise BrainConfigurationError(
                "Freebuff CLI unavailable. "
                "Install: npm install -g freebuff\n"
                "Or set FREEBUFF_BINARY to the correct path."
            )
        return BrainRouter([bridge, CurrentLLMAdapter(router=router)])

    if cfg in ("freebuff_tmux", "freebuff-tmux", "freebufftmux"):
        # Freebuff CLI via tmux — the PRIMARY brain backed by Freebuff
        # running inside a persistent tmux session. Uses tmux capture-pane
        # for reliable TUI output parsing.
        from modules.llm.brain_router import BrainRouter
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge

        bridge = FreebuffTmuxBridge()
        if not bridge.available:
            raise BrainConfigurationError(
                "Freebuff tmux bridge unavailable. "
                "Requirements:\n"
                "  1. tmux installed (brew install tmux)\n"
                "  2. freebuff binary on PATH\n"
                "Or set FREEBUFF_BINARY to the correct path."
            )
        # Freebuff tmux primary, LiteLLM fallback
        return BrainRouter([bridge, CurrentLLMAdapter(router=router)])

    raise BrainConfigurationError(
        f"Unknown FOL_BRAIN={cfg!r}. Valid values: "
        f"'current' (default), 'freebuff' (Freebuff via OpenRouter), "
        f"'freebuff_auto' (Freebuff CLI auto-start + fallback), "
        f"'freebuff_tmux' (Freebuff CLI via tmux), "
        f"'freebuff_cli' (deprecated PTY)."
    )


__all__ = [
    "BrainInterface",
    "CurrentLLMAdapter",
    "FreebuffBrainAdapter",
    "get_brain",
    "BRAIN_INTENT_LABELS",
    "BrainError",
    "BrainConfigurationError",
    "BrainUnavailableError",
]
