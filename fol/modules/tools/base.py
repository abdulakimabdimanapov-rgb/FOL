"""Abstract base class for tools, ToolResult and the canonical ToolSpec."""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


class Permission(enum.Enum):
    """Access levels for tools."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class RiskLevel(str, enum.Enum):
    """Canonical risk levels for tool execution (canonical tool metadata)."""

    LOW = "low"          # Read-only / harmless
    MEDIUM = "medium"    # Affects local state in a reversible way
    HIGH = "high"        # Affects the system / user's data — confirm first
    CRITICAL = "critical"  # Destructive or irreversible

    @classmethod
    def from_permission(cls, permission: Permission) -> "RiskLevel":
        """Map a legacy ``Permission`` to the canonical risk level."""
        return {
            Permission.NONE: cls.LOW,
            Permission.LOW: cls.LOW,
            Permission.MEDIUM: cls.MEDIUM,
            Permission.HIGH: cls.HIGH,
            Permission.CRITICAL: cls.CRITICAL,
        }.get(permission, cls.LOW)


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool = True
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)

    def __str__(self) -> str:
        return self.output if self.success else f"Error: {self.error}"


@dataclass(frozen=True)
class ToolSpec:
    """Canonical tool descriptor — the metadata contract for every tool.

    Mirrors the unified registry requirements: name, description, schema,
    risk level, execution method (the tool object), and confirmation
    requirement.
    """

    name: str
    description: str
    schema: dict[str, Any]           # JSON-schema style parameters
    risk_level: RiskLevel
    requires_confirmation: bool
    category: str = "general"
    execution: Any = None            # the AbstractTool instance

    def to_openai(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        """Convert to Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
        }


class AbstractTool(abc.ABC):
    """Base class for all FOL tools."""

    name: str = "base_tool"
    description: str = ""
    # NOTE: plain mutable class defaults (not ``field(...)``) — ``AbstractTool``
    # is not a dataclass; subclasses override these per tool. This also avoids
    # the pre-existing ``Field``-object bug where ``field()`` was used outside
    # a dataclass.
    parameters: dict[str, Any] = {}
    required_permissions: list[Permission] = []
    timeout: float = 30.0

    # Canonical metadata (Phase 2): risk level + confirmation requirement.
    risk_level: RiskLevel = RiskLevel.LOW
    requires_confirmation: bool = False
    category: str = "general"

    @property
    def schema(self) -> dict[str, Any]:
        """Alias for ``parameters`` — the tool's input schema."""
        return self.parameters

    @property
    def effective_risk_level(self) -> RiskLevel:
        """Canonical risk level, derived from ``required_permissions`` when
        ``risk_level`` was not set explicitly on a legacy tool."""
        if self.risk_level is not RiskLevel.LOW:
            return self.risk_level
        if self.required_permissions:
            worst = max(p.value for p in self.required_permissions)
            return RiskLevel.from_permission(Permission(worst))
        return RiskLevel.LOW

    def to_spec(self) -> ToolSpec:
        """Describe this tool with the canonical ``ToolSpec``."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            schema=self.parameters,
            risk_level=self.effective_risk_level,
            requires_confirmation=self.requires_confirmation,
            category=self.category,
            execution=self,
        )

    @abc.abstractmethod
    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute the tool with given parameters."""
