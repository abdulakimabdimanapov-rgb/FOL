"""LLM module — canonical routing + backends.

New code should depend on the ``LLMRouter`` interface from
``modules.llm.router`` (local / cloud / fallback through one abstraction).
"""

from modules.llm.router import (
    LLMRouter,
    LiteLLMRouter,
    EngineBackendRouter,
    get_llm_router,
    build_model_chain,
    api_key_for_model,
)

__all__ = [
    "LLMRouter",
    "LiteLLMRouter",
    "EngineBackendRouter",
    "get_llm_router",
    "build_model_chain",
    "api_key_for_model",
]
