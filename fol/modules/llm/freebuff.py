"""Freebuff / Codebuff backend configuration.

This module holds configuration and requirements for connecting Freebuff
(or Codebuff) as a FOL brain. It deliberately imports nothing from
``modules.llm.brain`` so ``brain.py`` can import it without a circular
dependency.

Integration options (updated 2026-08-18):

  1. **Freebuff models via OpenRouter** (recommended, FREE):
     Use Freebuff's models (DeepSeek V4 Flash, MiMo 2.5) through OpenRouter.
     Set ``LLM_MODEL=openrouter/deepseek/deepseek-v4-flash`` — no code
     changes needed, works with the existing ``CurrentLLMAdapter``.

  2. **Codebuff SDK** (PAID — requires CODEBUFF_API_KEY):
     ``@codebuff/sdk`` provides agent-based AI via ``CodebuffClient.run()``.
     Set ``FOL_BRAIN=codebuff`` and ``CODEBUFF_API_KEY=sk-...``.
     The adapter runs Codebuff agents as a brain backend.

  3. **Freebuff HTTP API** (FUTURE — when official):
     Set ``FOL_BRAIN=freebuff`` + ``FREEBUFF_API_URL`` + ``FREEBUFF_API_TOKEN``.
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Freebuff (free service) — still no public API
# ---------------------------------------------------------------------------

FREEBUFF_REQUIREMENTS = (
    "Freebuff programmatic interface unavailable: the free Freebuff service "
    "has no public HTTP API, server or socket. To use Freebuff models as a "
    "brain, EITHER: (1) set LLM_MODEL to a Freebuff model via OpenRouter "
    "(e.g. openrouter/deepseek/deepseek-v4-flash) — FREE, no code changes; "
    "(2) use the Codebuff SDK (paid) with FOL_BRAIN=codebuff + "
    "CODEBUFF_API_KEY. See FOL_FREEBUFF_AUDIT.md for details."
)

# ---------------------------------------------------------------------------
# Codebuff SDK (paid — requires CODEBUFF_API_KEY)
# ---------------------------------------------------------------------------

def codebuff_config() -> dict[str, str]:
    """Codebuff SDK configuration read from the environment.

    Credentials are read HERE (at the adapter boundary), never passed
    through FOL Core.
    """
    return {
        "api_key": (os.environ.get("CODEBUFF_API_KEY") or "").strip(),
        "agent": (os.environ.get("CODEBUFF_AGENT") or "codebuff/base@latest").strip(),
        "timeout": (os.environ.get("CODEBUFF_TIMEOUT") or "120").strip(),
    }


def freebuff_config() -> dict[str, str]:
    """Freebuff configuration (legacy — for future HTTP API).

    Returns the keys FOL will use once an official interface ships.
    """
    return {
        "api_url": (os.environ.get("FREEBUFF_API_URL") or "").strip(),
        "api_token": (os.environ.get("FREEBUFF_API_TOKEN") or "").strip(),
        "timeout": (os.environ.get("FREEBUFF_TIMEOUT") or "60").strip(),
    }


__all__ = ["FREEBUFF_REQUIREMENTS", "freebuff_config", "codebuff_config"]
