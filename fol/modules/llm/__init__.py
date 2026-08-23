"""LLM module — canonical routing + backends + brain abstraction.

New code should depend on the ``LLMRouter`` interface from
``modules.llm.router`` (local / cloud / fallback through one abstraction)
for raw model routing, and on the ``BrainInterface`` from
``modules.llm.brain`` for provider-independent reasoning capabilities
(chat, classify, plan, select_tools, summarize, verify).
"""

from modules.llm.router import (
    LLMRouter,
    LiteLLMRouter,
    EngineBackendRouter,
    get_llm_router,
    build_model_chain,
    api_key_for_model,
)
from modules.llm.key_manager import (
    KeyManager,
    ValidationResult,
    PROVIDERS,
    get_key_manager,
)
from modules.llm.brain import (
    BrainInterface,
    CurrentLLMAdapter,
    FreebuffBrainAdapter,
    get_brain,
    BrainError,
    BrainConfigurationError,
    BrainUnavailableError,
)
from modules.llm.brain_router import BrainRouter

__all__ = [
    "LLMRouter",
    "LiteLLMRouter",
    "EngineBackendRouter",
    "get_llm_router",
    "build_model_chain",
    "api_key_for_model",
    "KeyManager",
    "ValidationResult",
    "PROVIDERS",
    "get_key_manager",
    "BrainInterface",
    "CurrentLLMAdapter",
    "FreebuffBrainAdapter",
    "BrainRouter",
    "get_brain",
    "BrainError",
    "BrainConfigurationError",
    "BrainUnavailableError",
]
