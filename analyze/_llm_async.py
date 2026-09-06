"""
Async LLM calling module — supports any provider via LiteLLM with streaming + tool calls.

Usage:
    from analyze._llm_async import llm_acompletion, llm_astream

    # Simple async completion
    response = await llm_acompletion(
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=1024,
    )

    # With tool calls
    response = await llm_acompletion(
        messages=[{"role": "user", "content": "Send an email"}],
        tools=TOOL_DEFINITIONS,
    )

    # Streaming
    async for chunk in llm_astream(messages=[...]):
        if chunk["type"] == "token":
            print(chunk["text"])
        elif chunk["type"] == "tool_use":
            print(chunk["name"])
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncGenerator

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_MODEL = "claude-sonnet-4-20250514"

# OpenRouter key rotation — when key 1 hits rate limit, switch to key 2
# OpenRouter key rotation — delegated to centralized key pool
from modules.llm.key_pool import get_key_pool as _get_key_pool

_openrouter_key_index: int = 0
_openrouter_rotation_reset: float = 0


def _get_openrouter_key() -> str:
    """Return the current OpenRouter API key via the centralized pool."""
    return _get_key_pool().get_key()


def rotate_in_openrouter_key() -> None:
    """Switch to the next OpenRouter API key via the centralized pool."""
    pool = _get_key_pool()
    current = pool.get_key()
    pool.mark_rate_limited(current)
    logger.warning("OpenRouter: rate limited — rotated to next key (pool=%d keys)", pool.pool_size)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_config() -> dict[str, Any]:
    """Read LLM config from environment."""
    load_dotenv()
    model = os.environ.get("LLM_MODEL", "").strip() or _DEFAULT_MODEL
    return {
        "model": model,
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS))),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0")),
    }


def _get_api_key_for_model(model: str) -> str | None:
    """Return the appropriate API key for a given model name.

    Order matters: provider-specific prefixes (openrouter/, ollama/) must be
    checked BEFORE generic substring matches ("anthropic", "openai") to avoid
    false positives like 'openrouter/anthropic/claude' matching Anthropic.
    """
    model_lower = model.lower()

    # --- Prefix-based matches (check FIRST to avoid false positives) ---
    if model_lower.startswith("openrouter/") or model_lower.startswith("openrouter:"):
        return _get_openrouter_key()
    if any(model_lower.startswith(p) for p in ("ollama/", "local/", "vllm/")):
        return "local"  # No API key needed

    # --- Substring-based matches ---
    if model_lower.startswith("claude") or "anthropic" in model_lower:
        return os.environ.get("ANTHROPIC_API_KEY")
    # Groq (check BEFORE OpenAI — groq/openai/gpt-oss-* must resolve to Groq)
    if model_lower.startswith("groq/") or ("groq" in model_lower and "/openai" not in model_lower):
        return os.environ.get("GROQ_API_KEY")
    if any(model_lower.startswith(p) for p in ("gpt", "o1", "o3")) or "openai" in model_lower:
        return os.environ.get("OPENAI_API_KEY")
    if "gemini" in model_lower:
        return os.environ.get("GEMINI_API_KEY")
    if "deepseek" in model_lower:
        return os.environ.get("DEEPSEEK_API_KEY")
    if model_lower.startswith("xai/") or "grok" in model_lower:
        return os.environ.get("XAI_API_KEY")

    return os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")


def _get_model_chain() -> list[str]:
    """Build the ordered list of models to try: primary + fallbacks.

    Primary model comes from ``LLM_MODEL`` (see ``_get_config``); additional
    fallback models come from ``LLM_FALLBACK_MODELS`` (comma-separated list,
    tried in order). Models whose provider API key is not configured are
    skipped, so the assistant keeps working as long as at least one provider
    is available.

    Returns:
        List of model names in priority order (may be empty).
    """
    config = _get_config()
    primary = config["model"]
    fallbacks_raw = os.environ.get("LLM_FALLBACK_MODELS", "").strip()
    fallbacks = [m.strip() for m in fallbacks_raw.split(",") if m.strip()]

    # POLICY: local LLMs (Ollama / MLX / vLLM / LM Studio) are removed from
    # FOL — skipped unless explicitly re-enabled with FOL_ENABLE_LOCAL_LLM=1.
    local_enabled = os.environ.get("FOL_ENABLE_LOCAL_LLM", "").strip().lower() in ("1", "true", "yes")
    local_prefixes = ("ollama/", "local/", "vllm/", "lm-studio")

    chain: list[str] = []
    for model in [primary] + fallbacks:
        if model in chain:
            continue
        if not local_enabled and model.lower().startswith(local_prefixes):
            logger.warning(
                "Skipping local model %s: local LLMs are disabled (FOL_ENABLE_LOCAL_LLM=1 to enable)",
                model,
            )
            continue
        if _get_api_key_for_model(model) is None:
            logger.warning(
                "Skipping model %s: no API key configured for its provider",
                model,
            )
            continue
        chain.append(model)
    return chain


# ---------------------------------------------------------------------------
# Tool format conversion
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
        # Check if already in OpenAI format
        if "function" in tool:
            converted.append(tool)
            continue

        # Convert from Anthropic to OpenAI format
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
    """Convert Anthropic-style tool_use/tool_result message blocks to OpenAI format.

    The orchestrator stores conversation history in Anthropic content-block
    format (text/tool_use/tool_result). OpenAI-compatible providers (Ollama,
    OpenAI, Groq, OpenRouter) require:

      assistant: {"role": "assistant", "content": "...", "tool_calls": [{id, type: "function", function: {name, arguments}}]}
      tool:      {"role": "tool", "tool_call_id": "...", "content": "..."}

    Anthropic-native models keep their own format — this function only
    rewrites when the model is not Anthropic.
    """
    normalized: list[dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        # Already a plain OpenAI-format message (string content)
        if isinstance(content, str):
            normalized.append(msg)
            continue

        # role="tool" already — pass through
        if role == "tool":
            normalized.append(msg)
            continue

        # content is a list of Anthropic-style blocks
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
                    tc_id = str(block.get("id", ""))
                    tc_name = str(block.get("name", ""))
                    tc_input = block.get("input", {})
                    tool_calls.append({
                        "id": tc_id,
                        "type": "function",
                        "function": {
                            "name": tc_name,
                            "arguments": json.dumps(tc_input, ensure_ascii=False),
                        },
                    })
            new_msg: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                new_msg["content"] = "".join(text_parts)
            else:
                new_msg["content"] = None
            if tool_calls:
                new_msg["tool_calls"] = tool_calls
            normalized.append(new_msg)

        elif role == "user":
            # tool_result blocks become separate role="tool" messages
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


def _convert_tool_calls_from_openai(
    tool_calls: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool_calls back to a simpler format.

    OpenAI format:  {"id": "...", "function": {"name": "...", "arguments": "..."}}
    Output format:  {"id": "...", "name": "...", "input": {...}}
    """
    if not tool_calls:
        return []

    results = []
    for tc in tool_calls:
        try:
            arguments = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, KeyError):
            arguments = {}
        results.append({
            "id": tc.get("id", ""),
            "name": tc["function"]["name"],
            "input": arguments,
        })
    return results


def _extract_text_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Try to parse a tool call that a model emitted as plain JSON text.

    Some providers/models (notably Ollama with small models) return tool
    calls as raw JSON in the content stream instead of structured
    ``tool_calls`` deltas. This helper extracts the first JSON object that
    looks like a tool call.

    Supported shapes:
      {"name": "open_app", "arguments": {"name": "Safari"}}
      {"type": "function", "name": "...", "parameters": {...}}
      {"type": "tool_use", "name": "...", "input": {...}}

    Returns (name, arguments) or None if the text is not a tool call.
    """
    text = text.strip().lstrip("`").rstrip("`")

    # Find the first '{' — the model may pad the JSON with prose ("Sure!")
    start = text.find("{")
    if start == -1:
        return None
    stripped = text[start:]

    # Find the first balanced JSON object in the text
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

    # Reject clearly non-tool JSON (e.g. a plain text answer object)
    if "name" not in obj:
        return None
    name = str(obj["name"]).strip()
    if not name or not name.replace("_", "").isalnum():
        return None

    # Extract arguments from the various shapes
    args = obj.get("arguments")
    if args is None:
        args = obj.get("parameters")
    if args is None:
        args = obj.get("input")
    if not isinstance(args, dict):
        return None

    return name, args


# ---------------------------------------------------------------------------
# Async completion (supports tool calls)
# ---------------------------------------------------------------------------

async def llm_acompletion(
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    stream: bool = False,
) -> dict[str, Any]:
    """Async LLM completion via LiteLLM.

    Args:
        messages: List of message dicts with "role" and "content".
        system: Optional system prompt (inserted as system message).
        tools: Optional list of tool definitions (Anthropic or OpenAI format).
        max_tokens: Max tokens for response.
        temperature: Override default temperature.
        stream: Whether to return a stream or full response.

    Returns:
        Dict with keys:
            - "content": Combined text content (str)
            - "tool_calls": List of {id, name, input} dicts (list)
            - "stop_reason": "end_turn" | "tool_use" | "length" | "stop"
            - "raw": Raw LiteLLM response object

    Never raises — returns {"content": "", "tool_calls": [], "stop_reason": "error"}
    on failure with a logged error.
    """
    config = _get_config()
    max_tok = max_tokens or config["max_tokens"]
    temp = temperature if temperature is not None else config["temperature"]

    openai_tools = _convert_tools_to_openai(tools) if tools else None

    chain = _get_model_chain()
    if not chain:
        logger.error(
            "No usable LLM models: set LLM_MODEL (and optionally "
            "LLM_FALLBACK_MODELS) with a valid API key for at least one provider."
        )
        return {"content": "", "tool_calls": [], "stop_reason": "error"}

    last_error = ""
    for model in chain:
        # Build messages with system prompt
        full_messages = list(messages)
        if system:
            full_messages.insert(0, {"role": "system", "content": system})

        # Anthropic-native models keep their own content-block format; other
        # providers (Ollama, OpenAI, Groq, OpenRouter) need OpenAI message shape.
        if not model.lower().startswith("claude") and not "anthropic" in model.lower():
            full_messages = _normalize_messages_for_openai(full_messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tok,
            "temperature": temp,
            "stream": stream,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        try:
            import litellm
            response = await litellm.acompletion(**kwargs)

            if stream:
                # Return the raw streaming response for the caller to iterate
                return {"_stream": response, "model": model}

            parsed = _parse_openai_response(response)
            # An empty response (no content AND no tool calls) counts as a
            # failure — try the next model in the chain instead of returning
            # "" to the caller.
            if parsed.get("content") or parsed.get("tool_calls"):
                return parsed
            logger.warning(
                "Model %s returned an empty response — trying next model in chain",
                model,
            )

        except ImportError:
            logger.error("litellm is not installed. Run: pip install litellm")
            return {"content": "", "tool_calls": [], "stop_reason": "error"}
        except Exception as exc:
            # OpenRouter key rotation on rate limit
            err_str = str(exc).lower()
            if model.lower().startswith("openrouter/") and any(
                p in err_str for p in ("rate_limit", "429", "too many requests")
            ):
                rotate_in_openrouter_key()
            logger.warning(
                "LLM acompletion failed for %s, trying next model: %s",
                model, exc,
            )
            last_error = str(exc)

    logger.error(
        "All %d model(s) failed for acompletion. Last error: %s",
        len(chain), last_error,
    )
    return {"content": "", "tool_calls": [], "stop_reason": "error"}


def _parse_openai_response(response: Any) -> dict[str, Any]:
    """Parse an OpenAI-format completion response into our standard format."""
    try:
        choice = response.choices[0]
    except (IndexError, AttributeError):
        return {"content": "", "tool_calls": [], "stop_reason": "error"}

    # Extract text content
    content = choice.message.content or ""

    # Extract tool calls
    raw_tool_calls = getattr(choice.message, "tool_calls", None)
    tool_calls = _convert_tool_calls_from_openai(raw_tool_calls)

    # Determine stop reason
    finish_reason = getattr(choice, "finish_reason", "stop")
    stop_reason_map = {
        "stop": "end_turn",
        "tool_calls": "tool_use",
        "length": "length",
        "error": "error",
    }
    stop_reason = stop_reason_map.get(finish_reason, finish_reason)

    return {
        "content": content,
        "tool_calls": tool_calls,
        "stop_reason": stop_reason,
        "raw": response,
    }


# ---------------------------------------------------------------------------
# Async streaming (for SSE / real-time chat)
# ---------------------------------------------------------------------------

# When a model emits a tool call as plain JSON text, we hold the text back
# from the token stream until we know what it is. Beyond this size we give up
# holding and treat it as prose (a normal answer that merely starts with '{').
_MAX_TEXT_TOOL_CALL_HOLD = 1024


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

async def llm_astream(
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream tokens and tool calls from any LLM via LiteLLM.

    Yields dicts:
        {"type": "token", "text": "..."}
        {"type": "tool_use", "id": "...", "name": "...", "input": {...}}
        {"type": "done", "stop_reason": "end_turn" | "tool_use"}
        {"type": "error", "message": "..."}

    Usage:
        async for event in llm_astream(messages, system=system, tools=tools):
            if event["type"] == "token":
                yield ("token", event)
            elif event["type"] == "tool_use":
                yield ("_tool_use", event)
    """
    config = _get_config()
    max_tok = max_tokens or config["max_tokens"]
    temp = config["temperature"]

    openai_tools = _convert_tools_to_openai(tools) if tools else None

    chain = _get_model_chain()
    if not chain:
        yield {"type": "error", "message": (
            "No usable LLM models. Set LLM_MODEL (and optionally "
            "LLM_FALLBACK_MODELS) with a valid API key."
        )}
        return

    # Try models in priority order. Fallback applies when opening the stream
    # fails (provider outage, rate limit, missing model) — once tokens are
    # flowing we can't switch models mid-stream.
    stream = None
    active_model = ""
    last_error = ""
    for model in chain:
        full_messages = list(messages)
        if system:
            full_messages.insert(0, {"role": "system", "content": system})

        # Normalize Anthropic content-block messages to OpenAI format for
        # non-Anthropic providers (the orchestrator stores history as blocks).
        if not model.lower().startswith("claude") and not "anthropic" in model.lower():
            full_messages = _normalize_messages_for_openai(full_messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tok,
            "temperature": temp,
            "stream": True,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        try:
            import litellm
            stream = await litellm.acompletion(**kwargs)
            active_model = model
            break
        except ImportError:
            yield {"type": "error", "message": "litellm not installed. Run: pip install litellm"}
            return
        except Exception as exc:
            # OpenRouter key rotation on rate limit
            err_str = str(exc).lower()
            if model.lower().startswith("openrouter/") and any(
                p in err_str for p in ("rate_limit", "429", "too many requests")
            ):
                rotate_in_openrouter_key()
            logger.warning(
                "LLM astream failed for %s, trying next model: %s",
                model, exc,
            )
            last_error = str(exc)

    if stream is None:
        yield {"type": "error", "message": f"All {len(chain)} model(s) failed. Last error: {last_error}"}
        return

    try:

        # Buffer for accumulating tool call chunks
        tool_call_buffers: dict[int, dict] = {}
        # Some providers (e.g. Ollama streaming) return tool calls as plain JSON
        # text instead of structured tool_calls deltas — accumulate it here.
        text_buffer = ""

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Text content — hold back tokens that could be part of a JSON
            # tool call (Ollama / small models emit them as plain text).
            if delta.content:
                text_buffer += delta.content
                if _could_be_text_tool_call(text_buffer):
                    # Might be a tool call — don't stream it yet.
                    if len(text_buffer) > _MAX_TEXT_TOOL_CALL_HOLD:
                        # Too big to be a tool call → it's prose that merely
                        # starts with '{'; flush it as normal text.
                        yield {"type": "token", "text": text_buffer}
                        text_buffer = ""
                    continue
                # Real prose — emit what we've accumulated.
                yield {"type": "token", "text": text_buffer}
                text_buffer = ""

            # Tool calls (streamed in chunks that need assembly)
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    idx = tc_chunk.index
                    if idx not in tool_call_buffers:
                        tool_call_buffers[idx] = {
                            "id": tc_chunk.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    buf = tool_call_buffers[idx]
                    if tc_chunk.id:
                        buf["id"] = tc_chunk.id
                    if tc_chunk.function and tc_chunk.function.name:
                        buf["name"] = tc_chunk.function.name
                    if tc_chunk.function and tc_chunk.function.arguments:
                        buf["arguments"] += tc_chunk.function.arguments

            # Check finish reason
            finish_reason = chunk.choices[0].finish_reason
            if finish_reason:
                # 1) Structured tool calls (OpenAI-format providers)
                for idx, buf in sorted(tool_call_buffers.items()):
                    try:
                        arguments = json.loads(buf["arguments"])
                    except json.JSONDecodeError:
                        arguments = {}
                    yield {
                        "type": "tool_use",
                        "id": buf["id"],
                        "name": buf["name"],
                        "input": arguments,
                    }
                tool_call_buffers.clear()

                # 2) Fallback: tool call returned as plain JSON text (Ollama
                #    streaming does this). Formats supported:
                #      {"name": "open_app", "arguments": {"name": "Safari"}}
                #      {"type": "function", "name": "...", "parameters": {...}}
                text_tool_call = _extract_text_tool_call(text_buffer)
                if text_tool_call:
                    name, arguments = text_tool_call
                    yield {
                        "type": "tool_use",
                        "id": f"call_{abs(hash(name)):x}",
                        "name": name,
                        "input": arguments,
                    }
                    text_buffer = ""
                elif text_buffer:
                    # Whatever we held never became a tool call — it's prose.
                    # Emit it now so the user never loses text.
                    yield {"type": "token", "text": text_buffer}
                    text_buffer = ""

                stop_map = {
                    "stop": "end_turn",
                    "tool_calls": "tool_use",
                    "length": "length",
                }
                # If a tool call was recovered from plain text, the turn is NOT
                # finished — the caller must execute the tool. Report tool_use
                # so agent loops don't short-circuit before executing.
                effective_stop = "tool_use" if (tool_call_buffers or text_tool_call) else stop_map.get(finish_reason, finish_reason)
                yield {"type": "done", "stop_reason": effective_stop}

    except Exception as exc:
        logger.error("LLM astream failed for %s: %s", active_model, exc)
        yield {"type": "error", "message": str(exc)}


# ---------------------------------------------------------------------------
# Sync convenience (for suggestion_engine which is sync)
# ---------------------------------------------------------------------------

def llm_completion_sync(
    messages: list[dict[str, Any]],
    system: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Synchronous LLM completion. Returns text string or empty on failure.

    Tries the primary model first, then each fallback in ``LLM_FALLBACK_MODELS``.
    """
    config = _get_config()
    max_tok = max_tokens or config["max_tokens"]
    temp = config["temperature"]

    chain = _get_model_chain()
    if not chain:
        logger.error(
            "No usable LLM models: set LLM_MODEL (and optionally "
            "LLM_FALLBACK_MODELS) with a valid API key for at least one provider."
        )
        return ""

    for model in chain:
        full_messages = list(messages)
        if system:
            full_messages.insert(0, {"role": "system", "content": system})

        api_key = _get_api_key_for_model(model)
        try:
            import litellm
            response = litellm.completion(
                model=model,
                messages=full_messages,
                max_tokens=max_tok,
                temperature=temp,
                api_key=None if api_key == "local" else api_key,
            )
            text = response.choices[0].message.content or ""
            if text:
                return text
            logger.warning(
                "Model %s returned an empty response — trying next model in chain",
                model,
            )
        except Exception as exc:
            logger.warning(
                "LLM sync completion failed for %s, trying next model: %s",
                model, exc,
            )

    logger.error("All %d model(s) failed for sync completion", len(chain))
    return ""
                                     