"""Tools module — canonical registry + tool metadata.

All tools are registered exactly once in ``modules.tools.registry.ToolRegistry``
and described by the canonical ``ToolSpec``.
"""

from modules.tools.base import (
    AbstractTool,
    Permission,
    RiskLevel,
    ToolResult,
    ToolSpec,
)
from modules.tools.registry import ToolRegistry

__all__ = [
    "AbstractTool",
    "Permission",
    "RiskLevel",
    "ToolResult",
    "ToolSpec",
    "ToolRegistry",
]
