"""
Universal LLM calling module — supports any provider via LiteLLM.

Usage:
    from analyze._llm import llm_call_json

    result = llm_call_json("Extract the name", "John Doe is 30")
    # Returns parsed dict from any supported provider

Environment variables:
    LLM_MODEL        (required) — model name, e.g.:
        Anthropic:  claude-sonnet-4-20250514, claude-3-haiku-20240307
        OpenAI:     gpt-4o, gpt-4o-mini
        Google:     gemini/gemini-2.0-flash
        Local:      ollama/llama3, ollama/mistral
        OpenRouter: openrouter/anthropic/claude-3.5-sonnet
    
    ANTHROPIC_API_KEY — required for Anthropic models
    OPENAI_API_KEY    — required for OpenAI models
    GEMINI_API_KEY    — required for Google Gemini models
    (Other providers use their own env vars per LiteLLM docs)

    LLM_MAX_TOKENS    (optional, default: 1500)
    LLM_TEMPERATURE   (optional, default: 0)
    LLM_FALLBACK_MODELS (optional) — comma-separated fallback models tried in
        order after LLM_MODEL fails (e.g. "ollama/llama3.2:3b"). Models whose
        provider API key is missing are skipped automatically, so the
        assistant keeps working as long as at least one provider is available.

Returns parsed JSON dict. Never raises — returns {} on failure.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 1500
_DEFAULT_MODEL = "claude-sonnet-4-20250514"

# Retry settings
_MAX_RETRIES = 2
_RATE_LIMIT_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 10  # seconds


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _get_config() -> dict[str, str]:
    """Read LLM config from environment. Returns dict with model, api_key, etc."""
    load_dotenv()
    model = os.environ.get("LLM_MODEL", "").strip() or _DEFAULT_MODEL
    return {
        "model": model,
        "max_tokens": os.environ.get("LLM_MAX_TOKENS", str(_DEFAULT_MAX_TOKENS)),
        "temperature": os.environ.get("LLM_TEMPERATURE", "0"),
    }


def _get_api_key_for_model(model: str) -> str | None:
    """Return the appropriate API key for a given model name.

    Order matters: provider-specific prefixes (openrouter/, ollama/)
    must be checked BEFORE generic substring matches ("anthropic", "openai")
    to avoid false positives like 'openrouter/anthropic/claude' matching Anthropic.
    """
    model_lower = model.lower()

    # --- Prefix-based matches (check FIRST to avoid false positives) ---

    # OpenRouter — "openrouter/anthropic/claude" must NOT match Anthropic
    if model_lower.startswith("openrouter/") or model_lower.startswith("openrouter:"):
        return os.environ.get("OPENROUTER_API_KEY")

    # Local models — no API key needed
    if any(model_lower.startswith(p) for p in ("ollama/", "local/", "vllm/", "lm-studio")):
        return "local"

    # Google Gemini
    if model_lower.startswith("gemini/"):
        return os.environ.get("GEMINI_API_KEY")

    # --- Substring-based matches ---

    # Anthropic models: claude-*, or contains "anthropic"
    if model_lower.startswith("claude") or "anthropic" in model_lower:
        return os.environ.get("ANTHROPIC_API_KEY")

    # OpenAI models: gpt-*, o1-*, o3-*, or contains "openai"
    if any(model_lower.startswith(p) for p in ("gpt", "o1", "o3")) or "openai" in model_lower:
        return os.environ.get("OPENAI_API_KEY")

    # Together AI
    if "together" in model_lower:
        return os.environ.get("TOGETHER_API_KEY")

    # DeepSeek
    if "deepseek" in model_lower:
        return os.environ.get("DEEPSEEK_API_KEY")

    # Groq
    if "groq" in model_lower:
        return os.environ.get("GROQ_API_KEY")

    # Fallback: try ANTHROPIC_API_KEY
    return os.environ.get("ANTHROPIC_API_KEY")


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

    chain: list[str] = []
    for model in [primary] + fallbacks:
        if model in chain:
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
# Markdown fence stripping
# ---------------------------------------------------------------------------

def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Rate limit detection
# ---------------------------------------------------------------------------

def _is_rate_limit_error(error: Exception) -> bool:
    """Check if an exception is a rate limit error."""
    err_str = str(error).lower()
    return any(phrase in err_str for phrase in (
        "rate_limit", "rate limit", "429", "too many requests",
        "quota exceeded", "insufficient_quota",
    ))


# ---------------------------------------------------------------------------
# Main LLM call
# ---------------------------------------------------------------------------

def _call_single_model(model: str, api_key: str | None, full_prompt: str,
                       max_tok: int, temp: float,
                       has_fallback: bool = False) -> str | None:
    """Try one model with temperature escalation + rate-limit retries.

    Returns the raw text response, or None if the model failed after all
    attempts (so the caller can fall back to the next model in the chain).

    When ``has_fallback`` is True (a fallback model is available), rate-limit
    and quota errors fail fast instead of sleeping — waiting out a dead
    provider wastes the user's time when another model can answer right away.
    """
    temperatures = [temp, min(temp + 0.3, 1.0)]
    for attempt_idx, temperature in enumerate(temperatures):
        for retry in range(_RATE_LIMIT_RETRIES):
            try:
                # Dynamic import: LiteLLM might not be installed yet
                import litellm
                response = litellm.completion(
                    model=model,
                    messages=[{"role": "user", "content": full_prompt}],
                    max_tokens=max_tok,
                    temperature=temperature,
                    api_key=api_key,
                )
                return response.choices[0].message.content or ""

            except ImportError:
                logger.error(
                    "litellm is not installed. Run: pip install litellm"
                )
                return None

            except Exception as exc:
                if _is_rate_limit_error(exc):
                    # Quota exhausted / 429 — the exact case fallback exists
                    # for. Don't burn ~30s sleeping on a dead provider.
                    if has_fallback:
                        logger.warning(
                            "Rate limited on %s — falling back to next model",
                            model,
                        )
                        return None
                    if retry < _RATE_LIMIT_RETRIES - 1:
                        delay = _RATE_LIMIT_BASE_DELAY * (2 ** retry)
                        logger.warning(
                            "Rate limited on %s (attempt %d, retry %d). Waiting %ds...",
                            model, attempt_idx, retry, delay,
                        )
                        time.sleep(delay)
                        continue

                logger.warning(
                    "LLM call failed on %s (attempt %d): %s",
                    model, attempt_idx, exc,
                )
                break  # try next temperature
        else:
            # All retries exhausted for this temperature
            logger.error(
                "Rate limit retries exhausted for model %s (attempt %d)",
                model, attempt_idx,
            )
    return None


def llm_call(prompt: str, text_block: str, max_tokens: int | None = None) -> str:
    """Send a prompt + text to any supported LLM. Returns raw text response.

    Tries the primary model (``LLM_MODEL``) first, then each model in
    ``LLM_FALLBACK_MODELS`` in order, so a provider outage or exhausted free
    quota doesn't take the assistant down. Never raises — returns empty
    string on failure after all models are exhausted.
    """
    config = _get_config()
    max_tok = max_tokens or int(config["max_tokens"])
    temp = float(config["temperature"])

    full_prompt = f"{prompt}\n\n---\n\n{text_block}"

    chain = _get_model_chain()
    if not chain:
        logger.error(
            "No usable LLM models: set LLM_MODEL (and optionally "
            "LLM_FALLBACK_MODELS) with a valid API key for at least one provider."
        )
        return ""

    for idx, model in enumerate(chain):
        api_key = _get_api_key_for_model(model)
        if api_key == "local":
            api_key = None  # Local models don't need API key
        result = _call_single_model(
            model, api_key, full_prompt, max_tok, temp,
            has_fallback=idx < len(chain) - 1,
        )
        # Empty (or None) result counts as a failure — try the next model.
        # A model that returns "" produced no usable answer.
        if result:
            return result
        logger.warning("Model %s failed — trying next model in chain", model)

    logger.error("All %d model(s) failed: %s", len(chain), " -> ".join(chain))
    return ""


def llm_call_json(prompt: str, text_block: str, max_tokens: int | None = None) -> dict:
    """Send a prompt + text to any supported LLM. Returns parsed JSON dict.

    Strips markdown fences and retries once with higher temperature
    if the first response is not valid JSON.
    Never raises — returns {} on failure.
    """
    temperatures = [0, 0.3]
    last_error = ""

    for temp in temperatures:
        raw = llm_call(prompt, text_block, max_tokens)
        if not raw:
            continue

        cleaned = _strip_markdown_fences(raw)
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            # If it's a list, wrap it
            if isinstance(parsed, list):
                return {"data": parsed}
            last_error = f"Response is {type(parsed).__name__}, not dict"
            logger.warning("LLM returned non-dict JSON (%s): %.200s", last_error, cleaned)
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            if temp == 0:
                logger.warning(
                    "LLM returned non-JSON (temp=0), retrying with temp=%s. Raw: %.200s",
                    temp, raw,
                )
            else:
                logger.warning(
                    "LLM returned non-JSON after retry. Raw: %.200s", raw,
                )

    logger.error("LLM JSON call failed after all retries. Last error: %s", last_error)
    return {}


# ---------------------------------------------------------------------------
# Convenience: test that the configured model works
# ---------------------------------------------------------------------------

def test_connection() -> str:
    """Quick connectivity test — returns the model name on success, error string on failure.

    Tries every model in the chain (primary + fallbacks) and reports the first
    one that responds.
    """
    chain = _get_model_chain()
    if not chain:
        return "❌ No API key configured for any model in the chain (LLM_MODEL / LLM_FALLBACK_MODELS)."

    last_error = ""
    for model in chain:
        api_key = _get_api_key_for_model(model)
        try:
            import litellm
            response = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": "Reply with just the word OK"}],
                max_tokens=10,
                temperature=0,
                api_key=None if api_key == "local" else api_key,
            )
            text = response.choices[0].message.content or ""
            return f"✅ {model} responds: {text.strip()}"
        except Exception as exc:
            last_error = str(exc)

    return f"❌ All {len(chain)} model(s) failed. Last error: {last_error}"


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print(test_connection())
