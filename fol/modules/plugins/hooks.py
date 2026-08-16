"""Plugin hook definitions — predefined hook points."""

from __future__ import annotations

from enum import Enum, auto


class HookPoint(Enum):
    """Available hook points for plugins."""

    ON_LOAD = auto()
    ON_UNLOAD = auto()
    ON_ENABLE = auto()
    ON_DISABLE = auto()
    ON_EVENT = auto()
    ON_USER_INPUT = auto()
    BEFORE_LLM_CALL = auto()
    AFTER_LLM_RESPONSE = auto()
    ON_TOOL_EXECUTE = auto()
    ON_MEMORY_RETRIEVE = auto()
    ON_MEMORY_STORE = auto()
    ON_ERROR = auto()
