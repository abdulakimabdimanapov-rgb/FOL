"""Workflow tool — execute multi-step action sequences."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from modules.tools.base import AbstractTool, ToolResult

logger = logging.getLogger(__name__)


class WorkflowTool(AbstractTool):
    """Execute a sequence of steps as a workflow."""

    name = "run_workflow"
    description = "Execute a multi-step workflow. Each step is a tool call with parameters."
    parameters = {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "description": "List of workflow steps",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "description": "Tool name to execute"},
                        "params": {"type": "object", "description": "Tool parameters"},
                    },
                    "required": ["tool"],
                },
            },
        },
        "required": ["steps"],
    }

    def __init__(self, tool_registry: Any = None) -> None:
        self._registry = tool_registry

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute workflow steps sequentially."""
        steps = params.get("steps", [])
        if not steps:
            return ToolResult(success=False, error="No steps provided")

        if self._registry is None:
            return ToolResult(success=False, error="Tool registry not available")

        results = []
        for i, step in enumerate(steps):
            tool_name = step.get("tool", "")
            step_params = step.get("params", {})

            logger.info("Workflow step", step=i + 1, tool=tool_name)
            result = await self._registry.execute(tool_name, step_params)
            results.append({
                "step": i + 1,
                "tool": tool_name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
            })

            if not result.success:
                logger.warning("Workflow step failed", step=i + 1, error=result.error)
                return ToolResult(
                    success=False,
                    error=f"Step {i + 1} failed: {result.error}",
                    metadata={"results": results},
                )

        return ToolResult(
            success=True,
            output=f"Workflow completed: {len(steps)} steps",
            metadata={"results": results},
        )
