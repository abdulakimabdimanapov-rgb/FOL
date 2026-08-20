"""Canonical LLM routing — one abstraction for local / cloud / fallback models.

This module defines the single routing interface for LLM access in FOL
(``fol/modules/llm/``). All new code should depend on the ``LLMRouter``
interface and obtain an instance through ``get_llm_router()``.

Implemented routers
-------------------
- ``LiteLLMRouter`` — unified local/cloud/fallback routing through LiteLLM,
  configured with environment variables exactly like the legacy module:

      LLM_MODEL            primary model (e.g. ``gpt-4o``, ``claude-…``,
                           ``gemini/…``, ``ollama/…``, ``openrouter/…``)
      LLM_FALLBACK_MODELS  comma-separated fallback chain
      LLM_TIMEOUT          optional per-call timeout in seconds
      *_API_KEY            provider keys (ANTHROPIC_API_KEY, OPENAI_API_KEY,
                           GEMINI_API_KEY, OPENROUTER_API_KEY, …)

  Models whose provider key is missing are skipped automatically, so the
  assistant keeps working as long as at least one provider is configured.
  This mirrors the proven chain semantics of the legacy ``analyze/_llm*.py``
  implementation, which is now the documented *legacy adapter* kept for
  callers that have not been migrated yet (see docs/ARCHITECTURE.md →
  Legacy boundaries).

- ``EngineBackendRouter`` — adapter exposing the FOL native ``LLMEngine``
  (MLX / OpenAI / Anthropic / OpenRouter backends) through the same
  interface.

Interface
---------
``LLMRouter`` provides sync completion, async completion, streaming, model
chain inspection and connectivity testing — a single contract for both
local (``ollama/``, ``mlx``) and cloud (``openai/``, ``anthropic/``,
``gemini/``, ``openrouter/``) providers with automatic fallback.

Fallback recording
------------------
``LiteLLMRouter(on_fallback=callable)`` accepts a callback invoked on every
model failure with a dict ``{provider, model, reason, attempt_index, total}``
(``reason`` is scrubbed of API keys and truncated). This powers the
orchestrator's fallback log without ever storing secrets.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import os
import threading
from typing import Any, AsyncIterator, Callable

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Defaults (identical to the legacy analyze/_llm.py configuration).
_DEFAULT_MAX_TOKENS = 1500
_DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Provider key detection — ordered; prefix rules MUST be checked before
# substring rules (e.g. ``openrouter/anthropic/…`` is OpenRouter, not Anthropic).
_LOCAL_PREFIXES = ("ollama/", "local/", "vllm/", "lm-studio")

# POLICY: FOL does NOT use local LLMs (Ollama / MLX inference / local model
# files). Local models are skipped in every model chain unless this flag is
# explicitly set — FOL's hardware stays cool, reasoning goes through
# Freebuff / API providers only.
def _local_llms_enabled() -> bool:
    return os.environ.get("FOL_ENABLE_LOCAL_LLM", "").strip().lower() in ("1", "true", "yes")

# When a model emits a tool call as plain JSON text, we hold the text back
# from the token stream until we know what it is. Beyond this size we give up
# holding and treat it as prose (a normal answer that merely starts with '{').
_MAX_TEXT_TOOL_CALL_HOLD = 1024


def is_local_model(model: str) -> bool:
    """True when the model is served locally (Ollama, vLLM, LM Studio, MLX).

    Local LLMs are removed from FOL's runtime by policy; this predicate is
    kept for classification (logging, tests) and for the chain gate.
    """
    m = model.lower().strip()
    if m.startswith(_LOCAL_PREFIXES):
        return True
    # MLX model ids are either bare ("mlx") or HuggingFace repo ids
    # ("mlx-community/…"), always prefixed with mlx.
    return m.startswith("mlx")


def provider_kind(model: str) -> str:
    """Classify a model as ``"local"`` or ``"cloud"`` (for routing decisions)."""
    return "local" if is_local_model(model) else "cloud"


def _is_anthropic_model(model: str) -> bool:
    """True when the model speaks Anthropic's native content-block format."""
    m = model.lower()
    return m.startswith("claude") or "anthropic" in m


def _scrub_secrets(reason: Any, api_key: str | None) -> str:
    """Sanitize an exception message for logging: truncate + redact the key."""
    if not reason:
        return ""
    text = str(reason)
    if api_key and api_key not in ("", "local") and api_key in text:
        text = text.replace(api_key, "***")
    return text[:300]


class LLMRouter(abc.ABC):
    """Canonical LLM routing interface.

    Implementations must support, through a single abstraction:

    - **Local models**   (``ollama/…``, MLX) — no API key required
    - **Cloud models**   (OpenAI, Anthropic, Gemini, OpenRouter, …)
    - **Fallback chain** — a primary model plus an ordered list of
      fallbacks tried automatically when the primary fails.
    """

    name: str = "base_router"

    @abc.abstractmethod
    def model_chain(self) -> list[str]:
        """Ordered list of models that would be tried (primary first)."""

    @abc.abstractmethod
    def available_providers(self) -> list[str]:
        """Human-readable list of configured providers."""

    @abc.abstractmethod
    def complete_sync(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Blocking completion. Returns text, or ``""`` when all models fail."""

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

    @abc.abstractmethod
    async def astream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream completion. Yields event dicts:
        ``{"type": "token", "text"}``, ``{"type": "tool_use", "id", "name", "input"}``,
        ``{"type": "done", "stop_reason"}``, ``{"type": "error", "message"}``."""

    def test_connection(self) -> str:
        """Quick connectivity test — returns a status string, never raises."""
        chain = self.model_chain()
        if not chain:
            return "❌ No configured model with an available API key."
        try:
            text = self.complete_sync(
                [{"role": "user", "content": "Reply with just the word OK"}],
                max_tokens=10,
                temperature=0,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return f"❌ Connection test failed: {exc}"
        if text:
            return f"✅ {chain[0]} responds: {text.strip()[:40]}"
        return f"❌ All {len(chain)} model(s) failed to respond."


# ---------------------------------------------------------------------------
# Environment-based configuration (shared with the legacy LiteLLM layer)
# ---------------------------------------------------------------------------

def _read_config() -> dict[str, str]:
    """Read LLM config from the environment (LLM_MODEL / LLM_MAX_TOKENS / …)."""
    load_dotenv()
    model = os.environ.get("LLM_MODEL", "").strip() or _DEFAULT_MODEL
    return {
        "model": model,
        "max_tokens": os.environ.get("LLM_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS)),
        "temperature": os.environ.get("LLM_TEMPERATURE", "0"),
    }


def _read_timeout() -> float | None:
    """Optional per-call timeout from ``LLM_TIMEOUT`` (seconds)."""
    raw = os.environ.get("LLM_TIMEOUT", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


# OpenRouter key rotation — shared with analyze/_llm.py
_openrouter_key_index: int = 0
_openrouter_rotation_reset: float = 0


def _get_openrouter_key() -> str:
    """Return the current OpenRouter API key with rotation support."""
    global _openrouter_key_index, _openrouter_rotation_reset
    import time as _time
    now = _time.time()
    if _openrouter_key_index > 0 and now > _openrouter_rotation_reset:
        _openrouter_key_index = 0
    if _openrouter_key_index == 0:
        return os.environ.get("OPENROUTER_API_KEY", "") or ""
    return os.environ.get("OPENROUTER_API_KEY_2", "") or os.environ.get("OPENROUTER_API_KEY", "") or ""


def rotate_in_openrouter_key() -> None:
    """Switch to the next OpenRouter API key (called on rate limit)."""
    global _openrouter_key_index, _openrouter_rotation_reset
    import time as _time
    if os.environ.get("OPENROUTER_API_KEY_2", "") and _openrouter_key_index == 0:
        _openrouter_key_index = 1
        _openrouter_rotation_reset = _time.time() + 300


def api_key_for_model(model: str) -> str | None:
    """Return the API key (or ``"local"``) for a model name, or ``None``.

    Provider-specific prefixes are checked before generic substrings so that
    ``openrouter/anthropic/claude-…`` resolves to the OpenRouter key.
    """
    model_lower = model.lower()

    if model_lower.startswith("openrouter/"):
        return _get_openrouter_key()
    if any(model_lower.startswith(p) for p in _LOCAL_PREFIXES):
        return "local"
    if model_lower.startswith("gemini/"):
        return os.environ.get("GEMINI_API_KEY")
    if model_lower.startswith("claude") or "anthropic" in model_lower:
        return os.environ.get("ANTHROPIC_API_KEY")
    # Groq (check BEFORE OpenAI — groq/openai/gpt-oss-* must resolve to Groq)
    if model_lower.startswith("groq/") or ("groq" in model_lower and "/openai" not in model_lower):
        return os.environ.get("GROQ_API_KEY")
    if any(model_lower.startswith(p) for p in ("gpt", "o1", "o3")) or "openai" in model_lower:
        return os.environ.get("OPENAI_API_KEY")
    if "together" in model_lower:
        return os.environ.get("TOGETHER_API_KEY")
    if "deepseek" in model_lower:
        return os.environ.get("DEEPSEEK_API_KEY")
    if model_lower.startswith("xai/") or "grok" in model_lower:
        return os.environ.get("XAI_API_KEY")
    return os.environ.get("ANTHROPIC_API_KEY")


def build_model_chain(
    *,
    primary: str | None = None,
    fallbacks: str | None = None,
    key_resolver=None,
) -> list[str]:
    """Build the ordered model chain: primary + fallbacks, skipping models
    whose provider has no API key.

    POLICY: local models (``ollama/``, MLX, vLLM, LM Studio) are skipped
    unless ``FOL_ENABLE_LOCAL_LLM=1`` — FOL does not run local LLMs.
    """
    if key_resolver is None:
        key_resolver = api_key_for_model  # resolved at call time (patchable)
    config = _read_config()
    primary = primary or config["model"]
    fallbacks_raw = fallbacks if fallbacks is not None else os.environ.get("LLM_FALLBACK_MODELS", "")
    fallback_list = [m.strip() for m in fallbacks_raw.split(",") if m.strip()]

    chain: list[str] = []
    for model in [primary] + fallback_list:
        if model in chain:
            continue
        if is_local_model(model) and not _local_llms_enabled():
            logger.warning(
                "Skipping local model %s: local LLMs are disabled (FOL_ENABLE_LOCAL_LLM=1 to enable)",
                model,
            )
            continue
        if key_resolver(model) is None:
            logger.warning("Skipping model %s: no API key configured for its provider", model)
            continue
        chain.append(model)
    return chain


def _prepare_messages(
    messages: list[dict[str, Any]], system: str | None
) -> list[dict[str, Any]]:
    """Prepend the system message when provided."""
    if not system:
        return list(messages)
    return [{"role": "system", "content": system}] + list(messages)


def _finish_reason_to_stop_reason(finish_reason: str | None) -> str:
    """Map OpenAI-style finish reasons to FOL's canonical stop reasons."""
    if finish_reason in ("tool_calls", "function_call"):
        return "tool_use"
    if finish_reason == "stop":
        return "end_turn"
    if finish_reason == "length":
        return "max_tokens"
    return finish_reason or "end_turn"


def _tool_call_field(call: Any, key: str) -> Any:
    """Extract a field from a streaming tool-call's ``function`` payload.

    OpenAI-compatible SDKs expose ``function`` as an object (``.name``,
    ``.arguments``); raw dicts use key access. Handle both.
    """
    fn = getattr(call, "function", None)
    if isinstance(fn, dict):
        return fn.get(key, "")
    return getattr(fn, key, "") if fn is not None else ""


# ---------------------------------------------------------------------------
# Message / tool normalization for OpenAI-compatible providers
# ---------------------------------------------------------------------------

def _convert_tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Convert Anthropic-style tool definitions to OpenAI format if needed.

    Anthropic format: {"name": "...", "description": "...", "input_schema": {...}}
    OpenAI format:   {"function": {"name": "...", "description": "...", "parameters": {...}}}
    """
    if not tools:
        return tools

    converted = []
    for tool in tools:
        if "function" in tool:
            converted.append(tool)
            continue
        converted.append({
            "type": "function",
            "function": {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return converted


def _normalize_messages_for_openai(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Anthropic-style tool_use/tool_result blocks to OpenAI format.

    The orchestrator stores conversation history in Anthropic content-block
    format (text/tool_use/tool_result). OpenAI-compatible providers (Ollama,
    OpenAI, Groq, OpenRouter) require:

      assistant: {"role": "assistant", "content": "...", "tool_calls": [...]}
      tool:      {"role": "tool", "tool_call_id": "...", "content": "..."}

    Anthropic-native models keep their own format — callers should only invoke
    this for non-Anthropic models.
    """
    normalized: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if isinstance(content, str):
            normalized.append(msg)
            continue

        if role == "tool":
            normalized.append(msg)
            continue

        if not isinstance(content, list):
            normalized.append(msg)
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(str(block.get("text", "")))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": str(block.get("id", "")),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name", "")),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        },
                    })
            new_msg: dict[str, Any] = {"role": "assistant"}
            new_msg["content"] = "".join(text_parts) if text_parts else None
            if tool_calls:
                new_msg["tool_calls"] = tool_calls
            normalized.append(new_msg)

        elif role == "user":
            text_parts = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(str(block.get("text", "")))
                elif btype == "tool_result":
                    tool_use_id = str(block.get("tool_use_id", ""))
                    result = block.get("content", "")
                    if not isinstance(result, str):
                        result = json.dumps(result, ensure_ascii=False)
                    normalized.append({
                        "role": "tool",
                        "tool_call_id": tool_use_id,
                        "content": result,
                    })
            if text_parts:
                normalized.append({"role": "user", "content": "".join(text_parts)})
        else:
            normalized.append(msg)

    return normalized


def _could_be_text_tool_call(text: str) -> bool:
    """Could this (possibly partial) text become a JSON tool call?

    True when the text starts with a tool-call JSON indicator or a ```json
    fence. Used to avoid streaming raw tool-call JSON to the user.
    """
    stripped = text.strip().lstrip("`").strip()
    if stripped.startswith("```json"):
        return True
    if not stripped.startswith("{"):
        return False
    head = stripped[1:80].lower()
    return any(
        key in head
        for key in ('"type"', '"name"', '"function"', '"action"', '"thought"',
                    '"arguments"', '"parameters"', '"input"', '"params"')
    )


def _extract_text_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Try to parse a tool call that a model emitted as plain JSON text.

    Some providers/models (notably Ollama with small models) return tool
    calls as raw JSON in the content stream instead of structured
    ``tool_calls`` deltas.

    Supported shapes:
      {"name": "open_app", "arguments": {"name": "Safari"}}
      {"type": "function", "name": "...", "parameters": {...}}
      {"type": "tool_use", "name": "...", "input": {...}}

    Returns (name, arguments) or None if the text is not a tool call.
    """
    text = text.strip().lstrip("`").rstrip("`")

    start = text.find("{")
    if start == -1:
        return None
    stripped = text[start:]

    depth = 0
    in_string = False
    escape = False
    end = -1
    for i, ch in enumerate(stripped):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end <= 0:
        return None

    try:
        obj = json.loads(stripped[:end])
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(obj, dict):
        return None

    if "name" not in obj:
        return None
    name = str(obj["name"]).strip()
    if not name or not name.replace("_", "").isalnum():
        return None

    args = obj.get("arguments")
    if args is None:
        args = obj.get("parameters")
    if args is None:
        args = obj.get("input")
    if not isinstance(args, dict):
        return None

    return name, args


def _run_coro_sync(coro: Any) -> Any:
    """Run a coroutine to completion from a possibly-running event loop.

    ``asyncio.run`` raises ``RuntimeError`` when an event loop is already
    running (e.g. inside the FOL API server). In that case the coroutine is
    executed on a dedicated thread with its own event loop — standard library
    only, no new dependencies.
    """
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if not in_loop:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - defensive
            box["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ---------------------------------------------------------------------------
# LiteLLMRouter — canonical env-configured routing (local / cloud / fallback)
# ---------------------------------------------------------------------------

class LiteLLMRouter(LLMRouter):
    """Unified local/cloud/fallback routing through LiteLLM.

    Configured purely through environment variables (see module docstring).
    LiteLLM is imported lazily so the router itself never hard-fails on
    machines without it.

    ``on_fallback`` — optional callable invoked on every model failure with
    ``{"provider", "model", "reason", "attempt_index", "total"}`` (reason is
    scrubbed of API keys and truncated). Used for fallback accounting.
    """

    name = "litellm"

    def __init__(
        self,
        primary_model: str | None = None,
        fallback_models: str | None = None,
        on_fallback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._primary = primary_model
        self._fallbacks = fallback_models
        self._on_fallback = on_fallback

    # -- config ------------------------------------------------------------

    def model_chain(self) -> list[str]:
        return build_model_chain(primary=self._primary, fallbacks=self._fallbacks)

    def available_providers(self) -> list[str]:
        providers = []
        for model in self.model_chain():
            prefix = model.split("/", 1)[0]
            if prefix not in providers:
                providers.append(prefix)
        return providers

    # -- fallback accounting ------------------------------------------------

    def _notify_fallback(self, model: str, reason: Any, total: int, api_key: str | None = None, idx: int = 0) -> None:
        """Report a model failure to the on_fallback hook (if any)."""
        if self._on_fallback is None:
            return
        try:
            self._on_fallback({
                "provider": provider_kind(model),
                "model": model,
                "reason": _scrub_secrets(reason, api_key),
                "attempt_index": idx + 1,
                "total": total,
            })
        except Exception:  # pragma: no cover - defensive
            logger.debug("on_fallback hook raised", exc_info=True)

    # -- sync --------------------------------------------------------------

    def complete_sync(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        config = _read_config()
        max_tok = max_tokens or int(config["max_tokens"])
        temp = temperature if temperature is not None else float(config["temperature"])
        timeout = _read_timeout()
        openai_tools = _convert_tools_to_openai(tools) if tools else None
        chain = self.model_chain()

        for idx, model in enumerate(chain):
            api_key = api_key_for_model(model)
            full = _prepare_messages(messages, system)
            if not _is_anthropic_model(model):
                full = _normalize_messages_for_openai(full)
            try:
                import litellm

                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": full,
                    "max_tokens": max_tok,
                    "temperature": temp,
                }
                if openai_tools:
                    kwargs["tools"] = openai_tools
                if timeout is not None:
                    kwargs["timeout"] = timeout
                if api_key != "local":
                    kwargs["api_key"] = api_key
                response = litellm.completion(**kwargs)
                text = response.choices[0].message.content or ""
            except Exception as exc:
                logger.warning("complete_sync failed on %s: %s", model, exc)
                self._notify_fallback(model, exc, len(chain), api_key, idx)
                continue
            if text:
                return text
            logger.warning("complete_sync returned empty on %s — trying next model", model)
            self._notify_fallback(model, "empty response", len(chain), api_key, idx)

        logger.error("All %d model(s) failed", len(chain))
        return ""

    # -- async -------------------------------------------------------------

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        config = _read_config()
        max_tok = max_tokens or int(config["max_tokens"])
        temp = temperature if temperature is not None else float(config["temperature"])
        timeout = _read_timeout()
        openai_tools = _convert_tools_to_openai(tools) if tools else None
        chain = self.model_chain()

        for idx, model in enumerate(chain):
            api_key = api_key_for_model(model)
            full = _prepare_messages(messages, system)
            if not _is_anthropic_model(model):
                full = _normalize_messages_for_openai(full)
            try:
                import litellm

                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": full,
                    "max_tokens": max_tok,
                    "temperature": temp,
                }
                if openai_tools:
                    kwargs["tools"] = openai_tools
                if timeout is not None:
                    kwargs["timeout"] = timeout
                if api_key != "local":
                    kwargs["api_key"] = api_key
                response = await litellm.acompletion(**kwargs)
            except Exception as exc:
                logger.warning("acomplete failed on %s: %s", model, exc)
                self._notify_fallback(model, exc, len(chain), api_key, idx)
                continue

            parsed = _parse_openai_response(response)
            # Empty content with no tool calls counts as a failure — try the
            # next model in the chain rather than answering with nothing.
            if parsed["content"] or parsed["tool_calls"]:
                return parsed
            logger.warning("acomplete returned empty on %s — trying next model", model)
            self._notify_fallback(model, "empty response", len(chain), api_key, idx)

        return {"content": "", "tool_calls": [], "stop_reason": "error"}

    async def astream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        config = _read_config()
        max_tok = max_tokens or int(config["max_tokens"])
        temp = float(config["temperature"])
        timeout = _read_timeout()
        openai_tools = _convert_tools_to_openai(tools) if tools else None
        chain = self.model_chain()

        if not chain:
            yield {"type": "error", "message": "No configured model with an available API key."}
            return

        for idx, model in enumerate(chain):
            api_key = api_key_for_model(model)
            full = _prepare_messages(messages, system)
            if not _is_anthropic_model(model):
                full = _normalize_messages_for_openai(full)
            try:
                import litellm

                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": full,
                    "max_tokens": max_tok,
                    "temperature": temp,
                    "stream": True,
                }
                if openai_tools:
                    kwargs["tools"] = openai_tools
                if timeout is not None:
                    kwargs["timeout"] = timeout
                if api_key != "local":
                    kwargs["api_key"] = api_key
                stream = await litellm.acompletion(**kwargs)
            except Exception as exc:
                logger.warning("astream failed on %s: %s", model, exc)
                self._notify_fallback(model, exc, len(chain), api_key, idx)
                continue

            # A stream that yields nothing is treated as a failure → next model.
            consumed_any = False
            yielded_any = False
            saw_tool_use = False
            # Buffer for structured tool calls (OpenAI-format providers).
            tool_call_buffers: dict[int, dict[str, Any]] = {}
            # Buffer for tool calls emitted as plain JSON text (Ollama/small).
            text_buffer = ""
            try:
                async for chunk in stream:
                    consumed_any = True
                    try:
                        choice = chunk.choices[0]
                    except (IndexError, AttributeError):
                        continue
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue

                    content = getattr(delta, "content", None)
                    if content:
                        text_buffer += content
                        if _could_be_text_tool_call(text_buffer):
                            # Might be a tool call — don't stream it yet.
                            if len(text_buffer) > _MAX_TEXT_TOOL_CALL_HOLD:
                                # Too big to be a tool call → prose that merely
                                # starts with '{'; flush it as normal text.
                                yielded_any = True
                                yield {"type": "token", "text": text_buffer}
                                text_buffer = ""
                        else:
                            if text_buffer:
                                yielded_any = True
                                yield {"type": "token", "text": text_buffer}
                                text_buffer = ""

                    # Structured tool calls (streamed in chunks that need assembly).
                    for call in getattr(delta, "tool_calls", None) or []:
                        saw_tool_use = True
                        yielded_any = True
                        idx = getattr(call, "index", 0)
                        buf = tool_call_buffers.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if getattr(call, "id", None):
                            buf["id"] = call.id
                        name = _tool_call_field(call, "name")
                        if name:
                            buf["name"] = name
                        arguments = _tool_call_field(call, "arguments")
                        if arguments:
                            buf["arguments"] += arguments

                    finish_reason = getattr(choice, "finish_reason", None)
                    if finish_reason:
                        # 1) Structured tool calls
                        for _, buf in sorted(tool_call_buffers.items()):
                            try:
                                parsed_args = json.loads(buf["arguments"]) if buf["arguments"] else {}
                            except (json.JSONDecodeError, TypeError):
                                parsed_args = {}
                            yield {
                                "type": "tool_use",
                                "id": buf["id"],
                                "name": buf["name"],
                                "input": parsed_args,
                            }
                        tool_call_buffers.clear()

                        # 2) Tool call returned as plain JSON text (Ollama).
                        text_tool_call = _extract_text_tool_call(text_buffer)
                        if text_tool_call:
                            name, arguments = text_tool_call
                            saw_tool_use = True
                            yield {
                                "type": "tool_use",
                                "id": f"call_{abs(hash(name)):x}",
                                "name": name,
                                "input": arguments,
                            }
                            text_buffer = ""
                        elif text_buffer:
                            # Whatever we held never became a tool call — emit
                            # it so the user never loses text.
                            yielded_any = True
                            yield {"type": "token", "text": text_buffer}
                            text_buffer = ""
            except Exception as exc:
                logger.warning("astream stream error on %s: %s", model, exc)
                if yielded_any:
                    # Already emitted tokens — never restart with another model
                    # mid-stream (would duplicate/garble output).
                    yield {"type": "error", "message": f"Stream failed after partial output: {exc}"}
                    return
                self._notify_fallback(model, exc, len(chain), api_key, idx)
                continue

            if consumed_any:
                # If a tool call was recovered (structured or from text), the
                # turn is NOT finished — report tool_use so agent loops don't
                # short-circuit before executing.
                yield {"type": "done", "stop_reason": "tool_use" if saw_tool_use else "end_turn"}
                return
            logger.warning("astream produced no events on %s — trying next model", model)
            self._notify_fallback(model, "no events", len(chain), api_key, idx)

        yield {"type": "error", "message": "All models failed to stream a response."}


def _parse_openai_response(response: Any) -> dict[str, Any]:
    """Parse an OpenAI-format completion response into the canonical dict."""
    try:
        choice = response.choices[0]
    except (IndexError, AttributeError):
        return {"content": "", "tool_calls": [], "stop_reason": "error"}

    content = (choice.message.content or "") if getattr(choice, "message", None) else ""
    tool_calls = _convert_tool_calls(getattr(getattr(choice, "message", None), "tool_calls", None))
    stop_reason = _finish_reason_to_stop_reason(getattr(choice, "finish_reason", None))
    return {
        "content": content,
        "tool_calls": tool_calls,
        "stop_reason": stop_reason,
    }


def _convert_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    """Convert OpenAI-format tool calls to FOL's canonical tool-use dicts."""
    converted: list[dict[str, Any]] = []
    for call in raw_tool_calls or []:
        fn = getattr(call, "function", None)
        name = getattr(fn, "name", "") if fn else ""
        arguments = getattr(fn, "arguments", "") if fn else ""

        try:
            parsed_args = json.loads(arguments) if arguments else {}
        except (json.JSONDecodeError, TypeError):
            parsed_args = {}
        converted.append({
            "id": getattr(call, "id", "") or "",
            "name": name,
            "input": parsed_args,
        })
    return converted


# ---------------------------------------------------------------------------
# EngineBackendRouter — canonical interface over the FOL native LLMEngine
# ---------------------------------------------------------------------------

class EngineBackendRouter(LLMRouter):
    """Adapter exposing the FOL native ``LLMEngine`` (MLX / OpenAI /
    Anthropic / OpenRouter backends) through the canonical ``LLMRouter``
    interface.

    The engine currently exposes single-prompt generation, so multi-message
    conversations are flattened: the last user message becomes the prompt and
    earlier turns are passed as context.
    """

    name = "engine"

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def model_chain(self) -> list[str]:
        backends = getattr(self._engine, "available_backends", None)
        return list(backends) if backends else []

    def available_providers(self) -> list[str]:
        return self.model_chain()

    def _flatten(self, messages: list[dict[str, Any]]) -> tuple[str, str]:
        """Split messages into (prompt, context) for the engine."""
        prompt = ""
        context_parts = []
        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue
            if msg.get("role") == "user":
                prompt = content  # last user message wins
            elif msg.get("role") == "assistant":
                context_parts.append(f"FOL: {content}")
            else:
                context_parts.append(f"{msg.get('role', 'system').title()}: {content}")
        return prompt, "\n".join(context_parts)

    def complete_sync(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        prompt, context = self._flatten(messages)
        if not prompt:
            return ""
        try:
            result = self._engine.generate(
                prompt,
                context=context,
                system_prompt=system or "",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.error("EngineBackendRouter sync generation failed: %s", exc)
            return ""
        try:
            # ``generate`` is async on the native engine; run it safely even
            # when an event loop is already active (see ``_run_coro_sync``).
            return str(_run_coro_sync(result) or "")
        except Exception as exc:
            logger.error("EngineBackendRouter sync generation failed: %s", exc)
            return ""

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        prompt, context = self._flatten(messages)
        if not prompt:
            return {"content": "", "tool_calls": [], "stop_reason": "error"}
        try:
            text = await self._engine.generate(
                prompt,
                context=context,
                system_prompt=system or "",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.error("EngineBackendRouter async generation failed: %s", exc)
            return {"content": "", "tool_calls": [], "stop_reason": "error"}
        if not text or text.startswith("["):
            return {"content": "", "tool_calls": [], "stop_reason": "error"}
        return {"content": text, "tool_calls": [], "stop_reason": "end_turn"}

    async def astream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        result = await self.acomplete(
            messages, system=system, tools=tools, max_tokens=max_tokens
        )
        if result["content"]:
            yield {"type": "token", "text": result["content"]}
            yield {"type": "done", "stop_reason": result["stop_reason"]}
        else:
            yield {"type": "error", "message": "Engine backends unavailable."}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm_router(kind: str = "litellm", **kwargs: Any) -> LLMRouter:
    """Build a canonical router.

    - ``kind="litellm"`` → env-configured LiteLLMRouter (local/cloud/fallback).
    - ``kind="engine"``  → EngineBackendRouter; requires ``engine=<LLMEngine>``.
    """
    if kind == "engine":
        engine = kwargs.get("engine")
        if engine is None:
            raise ValueError("get_llm_router(kind='engine') requires engine=<LLMEngine>")
        return EngineBackendRouter(engine)
    return LiteLLMRouter(
        primary_model=kwargs.get("primary_model"),
        fallback_models=kwargs.get("fallback_models"),
        on_fallback=kwargs.get("on_fallback"),
    )


__all__ = [
    "LLMRouter",
    "LiteLLMRouter",
    "EngineBackendRouter",
    "get_llm_router",
    "build_model_chain",
    "api_key_for_model",
    "is_local_model",
    "provider_kind",
]
