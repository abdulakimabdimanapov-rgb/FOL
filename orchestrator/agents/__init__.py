"""FOL — Agent Team System.

Specialized AI agents for different task domains.
Each agent has its own system prompt and tool subset.
A router agent classifies incoming tasks and delegates to the right agent.
"""
from __future__ import annotations

from .router import AgentType, route_task
from .architect import ARCHITECT_PROMPT, ARCHITECT_TOOLS_NAMES as ARCHITECT_TOOLS
from .coder import CODER_PROMPT, CODER_TOOLS_NAMES as CODER_TOOLS
from .reviewer import REVIEWER_PROMPT, REVIEWER_TOOLS_NAMES as REVIEWER_TOOLS
from .researcher import RESEARCHER_PROMPT, RESEARCHER_TOOLS_NAMES as RESEARCHER_TOOLS
from .memory import MEMORY_AGENT_PROMPT, MEMORY_AGENT_TOOLS_NAMES as MEMORY_AGENT_TOOLS

__all__ = [
    "AgentType",
    "route_task",
    "ARCHITECT_PROMPT", "ARCHITECT_TOOLS",
    "CODER_PROMPT", "CODER_TOOLS",
    "REVIEWER_PROMPT", "REVIEWER_TOOLS",
    "RESEARCHER_PROMPT", "RESEARCHER_TOOLS",
    "MEMORY_AGENT_PROMPT", "MEMORY_AGENT_TOOLS",
]
