"""Tool registry — the canonical central registry for all FOL tools.

Every tool is registered here exactly once and described by the canonical
``ToolSpec`` (name, description, schema, risk level, execution method,
confirmation requirement) — see ``modules.tools.base.ToolSpec``.

The registry supports:

- **Registration** — ``register(AbstractTool)`` and ``register_spec(ToolSpec)``
  (spec-only tools whose execution lives in the host layer, e.g. the
  orchestrator dispatcher).
- **Lookup / listing** — ``get`` / ``list_all`` / ``specs`` / ``names`` / ``has``.
- **Filtering** — ``filter(category=…, names=…, risk_at_most=…, requires_confirmation=…)``.
- **Risk & confirmation inspection** — ``get_spec`` / ``requires_confirmation`` /
  ``high_risk_tools``.
- **Schema generation** — ``to_anthropic_tools`` / ``to_openai_tools``.
- **Deterministic argument validation** — ``validate_args`` (required fields +
  primitive type checks) and **fail-closed execution** — unknown tools and
  unknown tool names are rejected before anything runs.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

from modules.tools.base import AbstractTool, RiskLevel, ToolResult, ToolSpec

logger = logging.getLogger(__name__)


class SpecOnlyTool(AbstractTool):
    """A tool registered with canonical metadata only.

    Execution is performed by the host layer (e.g. the orchestrator's tool
    dispatcher), not by the registry. An optional ``handler`` may be attached
    so the registry can still execute it deterministically when needed.
    """

    def __init__(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self._spec = spec
        self._handler = handler
        self.name = spec.name
        self.description = spec.description
        self.parameters = spec.schema
        self.risk_level = spec.risk_level
        self.requires_confirmation = spec.requires_confirmation
        self.category = spec.category

    def to_spec(self) -> ToolSpec:
        """Return the canonical spec exactly as registered (never re-derived)."""
        return self._spec

    def set_handler(self, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Attach (or replace) the execution handler for this tool.

        Phase 5: the canonical registry is the single dispatch mechanism.
        Metadata-only tools get their host-layer handler attached here, so
        ``registry.execute(name, args)`` runs it deterministically.
        """
        self._handler = handler

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        if self._handler is None:
            return ToolResult(
                success=False,
                error=f"Tool '{self.name}' is metadata-only — executed by the host layer.",
            )
        try:
            result = self._handler(params)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, (dict, list, int, float, bool)) or result is None:
                # JSON-encode structured results so the caller always receives a
                # valid JSON string (never a Python repr like "{'a': 1}").
                import json

                return ToolResult(success=True, output=json.dumps(result))
            return ToolResult(success=True, output=str(result))
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult(success=False, error=str(exc))


class ToolRegistry:
    """Central registry for all FOL tools.

    This is the **single** tool registry abstraction: tool metadata (name,
    description, schema, risk, confirmation) lives here and nowhere else.
    """

    def __init__(self) -> None:
        self._tools: dict[str, AbstractTool] = {}

    # -- registration ------------------------------------------------------

    def register(self, tool: AbstractTool) -> None:
        """Register a tool (an ``AbstractTool`` implementation)."""
        if tool.name in self._tools:
            logger.warning("Tool already registered, overwriting", name=tool.name)
        self._tools[tool.name] = tool
        logger.info("Tool registered", name=tool.name)

    def register_spec(self, spec: ToolSpec, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        """Register a canonical ``ToolSpec`` (metadata-only unless ``handler``)."""
        self.register(SpecOnlyTool(spec, handler=handler))

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def attach_handler(self, name: str, handler: Callable[[dict[str, Any]], Any]) -> bool:
        """Attach an execution handler to an already-registered spec-only tool.

        Returns False when the tool is unknown or not handler-backed (real
        ``AbstractTool`` implementations execute themselves).
        """
        tool = self._tools.get(name)
        if tool is None or not isinstance(tool, SpecOnlyTool):
            return False
        tool.set_handler(handler)
        return True

    def attach_handlers(self, handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> int:
        """Attach a batch of handlers keyed by tool name. Returns count attached."""
        attached = 0
        for name, handler in handlers.items():
            if self.attach_handler(name, handler):
                attached += 1
        return attached

    # -- lookup / listing --------------------------------------------------

    def get(self, name: str) -> AbstractTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Whether a tool is registered under ``name``."""
        return name in self._tools

    def names(self) -> list[str]:
        """All registered tool names (sorted)."""
        return sorted(self._tools)

    def list_all(self) -> list[AbstractTool]:
        """List all registered tools."""
        return list(self._tools.values())

    @property
    def count(self) -> int:
        """Number of registered tools."""
        return len(self._tools)

    # -- canonical metadata ------------------------------------------------

    def specs(self) -> list[ToolSpec]:
        """Describe every registered tool with the canonical ``ToolSpec``."""
        return [tool.to_spec() for tool in self._tools.values()]

    def get_spec(self, name: str) -> ToolSpec | None:
        """Get the canonical spec for a tool by name."""
        tool = self._tools.get(name)
        return tool.to_spec() if tool is not None else None

    def requires_confirmation(self, name: str) -> bool:
        """Whether executing ``name`` requires explicit user confirmation."""
        spec = self.get_spec(name)
        if spec is None:
            return False
        return spec.requires_confirmation or spec.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def high_risk_tools(self) -> list[ToolSpec]:
        """All tools that should be gated behind user confirmation."""
        return [spec for spec in self.specs() if spec.requires_confirmation or spec.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)]

    # -- filtering ---------------------------------------------------------

    def filter(
        self,
        *,
        category: str | None = None,
        names: set[str] | list[str] | None = None,
        risk_at_most: RiskLevel | str | None = None,
        requires_confirmation: bool | None = None,
    ) -> list[ToolSpec]:
        """Return the specs matching every provided criterion.

        ``risk_at_most`` accepts a ``RiskLevel`` or its string value and keeps
        only specs whose risk is at or below that level (LOW < MEDIUM < HIGH <
        CRITICAL). ``requires_confirmation`` filters by the confirmation flag
        (when ``None`` the flag is not used as a filter).
        """
        if isinstance(risk_at_most, str):
            risk_at_most = RiskLevel(risk_at_most)
        name_set = set(names) if names is not None else None

        result = []
        for spec in self.specs():
            if category is not None and spec.category != category:
                continue
            if name_set is not None and spec.name not in name_set:
                continue
            if risk_at_most is not None and _risk_rank(spec.risk_level) > _risk_rank(risk_at_most):
                continue
            if requires_confirmation is not None and spec.requires_confirmation != requires_confirmation:
                continue
            result.append(spec)
        return result

    # -- schema generation -------------------------------------------------

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Convert all tools to OpenAI function calling format."""
        return [spec.to_openai() for spec in self.specs()]

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Convert all tools to Anthropic tool format."""
        return [spec.to_anthropic() for spec in self.specs()]

    # -- validation & execution (fail closed) ------------------------------

    def validate_args(self, name: str, args: Any) -> tuple[bool, str]:
        """Deterministically validate tool arguments before execution.

        Returns ``(True, "")`` when the call is acceptable, or
        ``(False, reason)`` otherwise. Unknown tools always fail closed.
        Checks required-field presence and primitive type matching — it is
        deliberately lenient about optional/unknown fields so small local
        models are not over-restricted.
        """
        spec = self.get_spec(name)
        if spec is None:
            return False, f"Unknown tool '{name}'"
        if not isinstance(args, dict):
            return False, "arguments must be an object"

        schema = spec.schema or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for field in required:
            if field not in args or args[field] in (None, ""):
                return False, f"missing required argument '{field}'"

        for key, value in args.items():
            prop = properties.get(key)
            if not isinstance(prop, dict):
                continue  # unknown/optional argument — lenient
            ptype = prop.get("type")
            if ptype == "string" and not isinstance(value, str):
                return False, f"argument '{key}' must be a string"
            if ptype == "integer" and isinstance(value, bool):
                return False, f"argument '{key}' must be an integer"
            if ptype == "integer" and not isinstance(value, int):
                return False, f"argument '{key}' must be an integer"
            if ptype == "boolean" and not isinstance(value, bool):
                return False, f"argument '{key}' must be a boolean"
            if ptype == "array" and not isinstance(value, list):
                return False, f"argument '{key}' must be an array"
            if ptype == "object" and not isinstance(value, dict):
                return False, f"argument '{key}' must be an object"
        return True, ""

    async def execute(self, name: str, params: dict[str, Any]) -> ToolResult:
        """Execute a tool by name (fail closed: unknown → error result)."""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"Tool '{name}' not found.")
        try:
            return await tool.execute(params)
        except Exception as exc:
            logger.error("Tool execution failed", tool=name, error=str(exc))
            return ToolResult(success=False, error=str(exc))


def _risk_rank(level: RiskLevel) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}[level.value]
