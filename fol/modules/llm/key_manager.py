"""Unified API Key Manager — validation, loading, and rotation for all LLM providers.

This module provides a single interface to:
  1. Load API keys from .env / environment variables for all providers
  2. Validate each key with a lightweight test request
  3. Report which providers are configured and healthy

Supported providers:
  - OpenAI (OPENAI_API_KEY) — gpt-4o-mini
  - Anthropic (ANTHROPIC_API_KEY) — claude-sonnet-4-20250514
  - Google Gemini (GEMINI_API_KEY) — gemini-2.0-flash
  - OpenRouter (OPENROUTER_API_KEY) — openrouter/deepseek/deepseek-v4-flash
  - DeepSeek (DEEPSEEK_API_KEY) — deepseek-chat
  - Groq (GROQ_API_KEY) — llama3-70b-8192
  - xAI (XAI_API_KEY) — grok-3

Usage:
    from modules.llm.key_manager import get_key_manager

    km = get_key_manager()
    results = km.validate_all()
    for provider, result in results.items():
        print(f"{provider}: {result['status']}")
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderSpec:
    """Definition of an AI provider — env var, test model, validation endpoint."""
    name: str
    display_name: str
    env_var: str
    test_model: str
    api_base: str
    key_prefix: str = ""
    description: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        name="openai",
        display_name="OpenAI (GPT-4o)",
        env_var="OPENAI_API_KEY",
        test_model="gpt-4o-mini",
        api_base="https://api.openai.com/v1",
        key_prefix="sk-",
        description="OpenAI — GPT-4o, GPT-4o-mini, o1, o3",
    ),
    "anthropic": ProviderSpec(
        name="anthropic",
        display_name="Anthropic (Claude)",
        env_var="ANTHROPIC_API_KEY",
        test_model="claude-sonnet-4-20250514",
        api_base="https://api.anthropic.com/v1",
        key_prefix="sk-ant-",
        description="Anthropic — Claude Sonnet, Claude Opus, Claude Haiku",
    ),
    "gemini": ProviderSpec(
        name="gemini",
        display_name="Google Gemini",
        env_var="GEMINI_API_KEY",
        test_model="gemini-2.0-flash",
        api_base="https://generativelanguage.googleapis.com/v1beta",
        description="Google — Gemini 2.0 Flash (free tier), Gemini Pro",
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        display_name="OpenRouter (100+ models)",
        env_var="OPENROUTER_API_KEY",
        test_model="openrouter/deepseek/deepseek-v4-flash:free",
        api_base="https://openrouter.ai/api/v1",
        key_prefix="sk-or-",
        description="OpenRouter — DeepSeek, MiMo, Nemotron, Claude, GPT (free + paid)",
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        display_name="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        test_model="deepseek-chat",
        api_base="https://api.deepseek.com/v1",
        key_prefix="sk-",
        description="DeepSeek — Chat, Coder, V4 ($0.14/M tokens)",
    ),
    "groq": ProviderSpec(
        name="groq",
        display_name="Groq (free tier)",
        env_var="GROQ_API_KEY",
        test_model="llama3-70b-8192",
        api_base="https://api.groq.com/openai/v1",
        key_prefix="gsk_",
        description="Groq — ultra-fast inference, free tier ~30 req/min",
    ),
    "xai": ProviderSpec(
        name="xai",
        display_name="xAI (Grok)",
        env_var="XAI_API_KEY",
        test_model="grok-3",
        api_base="https://api.x.ai/v1",
        key_prefix="xai-",
        description="xAI — Grok-3, Grok-3-mini",
    ),
}


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of validating an API key."""
    provider: str
    key_preview: str          # e.g. "sk-ant-...xyz9"
    status: str               # "ok", "error", "invalid_key", "rate_limited", "not_configured"
    message: str              # human-readable explanation
    latency_ms: float = 0.0   # how long the test request took
    model_used: str = ""      # which model responded

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def __str__(self) -> str:
        icon = {"ok": "✅", "error": "❌", "invalid_key": "🔑", "rate_limited": "⏳", "not_configured": "⬜"}
        return f"{icon.get(self.status, '?')} {self.provider}: {self.message} ({self.latency_ms:.0f}ms)"


# ---------------------------------------------------------------------------
# Key validation functions (per provider)
# ---------------------------------------------------------------------------

def _validate_openai(key: str) -> ValidationResult:
    """Validate OpenAI API key with a minimal request."""
    import urllib.request
    import json

    t0 = time.time()
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Reply with just the word OK"}],
                "max_tokens": 5,
            }).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - t0) * 1000
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return ValidationResult(
                provider="openai",
                key_preview=f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***",
                status="ok",
                message=f"GPT-4o-mini responded: {reply.strip()[:30]}",
                latency_ms=latency,
                model_used="gpt-4o-mini",
            )
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        if e.code == 401:
            return ValidationResult("openai", f"{key[:8]}...", "invalid_key", "Invalid API key (401)", latency)
        if e.code == 429:
            return ValidationResult("openai", f"{key[:8]}...", "rate_limited", "Rate limited (429)", latency)
        return ValidationResult("openai", f"{key[:8]}...", "error", f"HTTP {e.code}: {e.reason}", latency)
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ValidationResult("openai", f"{key[:8]}...", "error", str(e)[:100], latency)


def _validate_anthropic(key: str) -> ValidationResult:
    """Validate Anthropic API key with a minimal request."""
    import urllib.request
    import json

    t0 = time.time()
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 5,
                "messages": [{"role": "user", "content": "Reply with just the word OK"}],
            }).encode(),
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - t0) * 1000
            reply = data.get("content", [{}])[0].get("text", "")
            return ValidationResult(
                provider="anthropic",
                key_preview=f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***",
                status="ok",
                message=f"Claude responded: {reply.strip()[:30]}",
                latency_ms=latency,
                model_used="claude-sonnet-4-20250514",
            )
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        if e.code == 401:
            return ValidationResult("anthropic", f"{key[:8]}...", "invalid_key", "Invalid API key (401)", latency)
        if e.code == 429:
            return ValidationResult("anthropic", f"{key[:8]}...", "rate_limited", "Rate limited (429)", latency)
        return ValidationResult("anthropic", f"{key[:8]}...", "error", f"HTTP {e.code}: {e.reason}", latency)
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ValidationResult("anthropic", f"{key[:8]}...", "error", str(e)[:100], latency)


def _validate_gemini(key: str) -> ValidationResult:
    """Validate Google Gemini API key with a minimal request."""
    import urllib.request
    import json

    t0 = time.time()
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
        req = urllib.request.Request(
            url,
            data=json.dumps({
                "contents": [{"parts": [{"text": "Reply with just the word OK"}]}],
                "generationConfig": {"maxOutputTokens": 5},
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - t0) * 1000
            reply = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return ValidationResult(
                provider="gemini",
                key_preview=f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***",
                status="ok",
                message=f"Gemini responded: {reply.strip()[:30]}",
                latency_ms=latency,
                model_used="gemini-2.0-flash",
            )
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        if e.code in (400, 403):
            return ValidationResult("gemini", f"{key[:8]}...", "invalid_key", "Invalid API key", latency)
        if e.code == 429:
            return ValidationResult("gemini", f"{key[:8]}...", "rate_limited", "Rate limited (429)", latency)
        return ValidationResult("gemini", f"{key[:8]}...", "error", f"HTTP {e.code}: {e.reason}", latency)
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ValidationResult("gemini", f"{key[:8]}...", "error", str(e)[:100], latency)


def _validate_openrouter(key: str) -> ValidationResult:
    """Validate OpenRouter API key with a minimal request."""
    import urllib.request
    import json

    t0 = time.time()
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps({
                "model": "deepseek/deepseek-v4-flash:free",
                "messages": [{"role": "user", "content": "Reply with just the word OK"}],
                "max_tokens": 5,
            }).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/fol-assistant",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - t0) * 1000
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return ValidationResult(
                provider="openrouter",
                key_preview=f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***",
                status="ok",
                message=f"DeepSeek V4 responded: {reply.strip()[:30]}",
                latency_ms=latency,
                model_used="deepseek/deepseek-v4-flash:free",
            )
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        if e.code == 401:
            return ValidationResult("openrouter", f"{key[:8]}...", "invalid_key", "Invalid API key (401)", latency)
        if e.code == 429:
            return ValidationResult("openrouter", f"{key[:8]}...", "rate_limited", "Rate limited (429)", latency)
        return ValidationResult("openrouter", f"{key[:8]}...", "error", f"HTTP {e.code}: {e.reason}", latency)
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ValidationResult("openrouter", f"{key[:8]}...", "error", str(e)[:100], latency)


def _validate_deepseek(key: str) -> ValidationResult:
    """Validate DeepSeek API key with a minimal request."""
    import urllib.request
    import json

    t0 = time.time()
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions",
            data=json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "Reply with just the word OK"}],
                "max_tokens": 5,
            }).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - t0) * 1000
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return ValidationResult(
                provider="deepseek",
                key_preview=f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***",
                status="ok",
                message=f"DeepSeek responded: {reply.strip()[:30]}",
                latency_ms=latency,
                model_used="deepseek-chat",
            )
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        if e.code == 401:
            return ValidationResult("deepseek", f"{key[:8]}...", "invalid_key", "Invalid API key (401)", latency)
        if e.code == 429:
            return ValidationResult("deepseek", f"{key[:8]}...", "rate_limited", "Rate limited (429)", latency)
        return ValidationResult("deepseek", f"{key[:8]}...", "error", f"HTTP {e.code}: {e.reason}", latency)
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ValidationResult("deepseek", f"{key[:8]}...", "error", str(e)[:100], latency)


def _validate_groq(key: str) -> ValidationResult:
    """Validate Groq API key with a minimal request."""
    import urllib.request
    import json

    t0 = time.time()
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps({
                "model": "llama3-70b-8192",
                "messages": [{"role": "user", "content": "Reply with just the word OK"}],
                "max_tokens": 5,
            }).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - t0) * 1000
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return ValidationResult(
                provider="groq",
                key_preview=f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***",
                status="ok",
                message=f"Groq responded: {reply.strip()[:30]}",
                latency_ms=latency,
                model_used="llama3-70b-8192",
            )
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        if e.code in (401, 403):
            return ValidationResult("groq", f"{key[:8]}...", "invalid_key", f"Invalid API key ({e.code})", latency)
        if e.code == 429:
            return ValidationResult("groq", f"{key[:8]}...", "rate_limited", "Rate limited (429)", latency)
        return ValidationResult("groq", f"{key[:8]}...", "error", f"HTTP {e.code}: {e.reason}", latency)
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ValidationResult("groq", f"{key[:8]}...", "error", str(e)[:100], latency)


def _validate_xai(key: str) -> ValidationResult:
    """Validate xAI API key with a minimal request."""
    import urllib.request
    import json

    t0 = time.time()
    try:
        req = urllib.request.Request(
            "https://api.x.ai/v1/chat/completions",
            data=json.dumps({
                "model": "grok-3",
                "messages": [{"role": "user", "content": "Reply with just the word OK"}],
                "max_tokens": 5,
            }).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            latency = (time.time() - t0) * 1000
            reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return ValidationResult(
                provider="xai",
                key_preview=f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***",
                status="ok",
                message=f"Grok responded: {reply.strip()[:30]}",
                latency_ms=latency,
                model_used="grok-3",
            )
    except urllib.error.HTTPError as e:
        latency = (time.time() - t0) * 1000
        if e.code in (401, 400, 403):
            return ValidationResult("xai", f"{key[:8]}...", "invalid_key", f"Invalid API key ({e.code})", latency)
        if e.code == 429:
            return ValidationResult("xai", f"{key[:8]}...", "rate_limited", "Rate limited (429)", latency)
        return ValidationResult("xai", f"{key[:8]}...", "error", f"HTTP {e.code}: {e.reason}", latency)
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return ValidationResult("xai", f"{key[:8]}...", "error", str(e)[:100], latency)


# Validation function registry
_VALIDATORS: dict[str, Callable[[str], ValidationResult]] = {
    "openai": _validate_openai,
    "anthropic": _validate_anthropic,
    "gemini": _validate_gemini,
    "openrouter": _validate_openrouter,
    "deepseek": _validate_deepseek,
    "groq": _validate_groq,
    "xai": _validate_xai,
}


# ---------------------------------------------------------------------------
# Key Manager
# ---------------------------------------------------------------------------

class KeyManager:
    """Unified API key manager for all LLM providers.

    Loads keys from environment, validates them, and provides a single
    interface to query provider status.
    """

    def __init__(self) -> None:
        load_dotenv()
        self._providers = dict(PROVIDERS)
        self._validators = dict(_VALIDATORS)
        self._cache: dict[str, ValidationResult] = {}

    def get_key(self, provider: str) -> str | None:
        """Return the API key for a provider, or None if not set."""
        spec = self._providers.get(provider)
        if not spec:
            return None
        key = os.environ.get(spec.env_var, "").strip()
        return key if key else None

    def configured_providers(self) -> list[str]:
        """Return names of providers that have a key configured."""
        return [name for name, spec in self._providers.items()
                if os.environ.get(spec.env_var, "").strip()]

    def missing_providers(self) -> list[str]:
        """Return names of providers that are NOT configured."""
        return [name for name, spec in self._providers.items()
                if not os.environ.get(spec.env_var, "").strip()]

    def validate(self, provider: str, key: str | None = None) -> ValidationResult:
        """Validate a single provider's API key.

        Args:
            provider: provider name (e.g. "openai", "anthropic")
            key: API key to validate (reads from env if None)

        Returns:
            ValidationResult with status and message
        """
        if provider not in self._providers:
            return ValidationResult(provider, "***", "error", f"Unknown provider: {provider}")

        if key is None:
            key = self.get_key(provider)
        if not key:
            return ValidationResult(
                provider, "***", "not_configured",
                f"No {self._providers[provider].env_var} set",
            )

        validator = self._validators.get(provider)
        if not validator:
            return ValidationResult(provider, f"{key[:8]}...", "error", "No validator available")

        result = validator(key)
        self._cache[provider] = result
        return result

    def validate_all(self) -> dict[str, ValidationResult]:
        """Validate all configured providers. Returns dict of results."""
        results: dict[str, ValidationResult] = {}
        for provider in self.configured_providers():
            results[provider] = self.validate(provider)
        return results

    def status_report(self) -> str:
        """Human-readable status report of all providers."""
        lines = ["╔══════════════════════════════════════════════════════╗",
                 "║         FOL API Key Status Report                  ║",
                 "╠══════════════════════════════════════════════════════╣"]

        for name, spec in self._providers.items():
            key = os.environ.get(spec.env_var, "").strip()
            if key:
                preview = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
                lines.append(f"║  ✅ {spec.display_name:<30} {preview:<14} ║")
            else:
                lines.append(f"║  ⬜ {spec.display_name:<30} {'NOT SET':<14} ║")

        lines.append("╠══════════════════════════════════════════════════════╣")

        n_configured = len(self.configured_providers())
        n_total = len(self._providers)
        lines.append(f"║  Configured: {n_configured}/{n_total} providers{' ' * (35 - len(str(n_configured)) - len(str(n_total)))}║")

        lines.append("╚══════════════════════════════════════════════════════╝")
        return "\n".join(lines)

    def save_to_env(self, updates: dict[str, str], env_path: str = ".env") -> None:
        """Update .env file with new key values.

        Args:
            updates: dict of env_var_name -> value (e.g. {"OPENAI_API_KEY": "sk-..."})
            env_path: path to .env file
        """
        lines: list[str] = []
        updated_keys: set[str] = set()

        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    matched = False
                    for env_var, value in updates.items():
                        if stripped.startswith(f"{env_var}=") or stripped.startswith(f"{env_var} ="):
                            lines.append(f"{env_var}={value}\n")
                            updated_keys.add(env_var)
                            matched = True
                            break
                    if not matched:
                        lines.append(line)

        # Append any keys not yet in .env
        for env_var, value in updates.items():
            if env_var not in updated_keys:
                lines.append(f"\n{env_var}={value}\n")

        with open(env_path, "w") as f:
            f.writelines(lines)

        logger.info("Updated %s with %d key(s)", env_path, len(updates))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: KeyManager | None = None


def get_key_manager() -> KeyManager:
    """Get or create the global KeyManager singleton."""
    global _instance
    if _instance is None:
        _instance = KeyManager()
    return _instance


def reset_key_manager() -> None:
    """Reset singleton (for testing)."""
    global _instance
    _instance = None


__all__ = [
    "KeyManager",
    "ValidationResult",
    "ProviderSpec",
    "PROVIDERS",
    "get_key_manager",
    "reset_key_manager",
]
