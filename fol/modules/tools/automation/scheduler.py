"""Scheduler tool — run commands on a schedule."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine
from uuid import UUID, uuid4

from modules.tools.base import AbstractTool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """A scheduled task."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    command: str = ""
    interval_seconds: float = 0.0
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None


class SchedulerTool(AbstractTool):
    """Schedule commands to run periodically."""

    name = "schedule"
    description = "Schedule a command to run at intervals or at a specific time."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "remove", "list", "run_now"],
                "description": "Scheduler action",
            },
            "name": {"type": "string", "description": "Task name"},
            "command": {"type": "string", "description": "Command to execute"},
            "interval_seconds": {
                "type": "number",
                "description": "Interval in seconds between runs",
            },
        },
        "required": ["action"],
    }

    def __init__(self, tool_registry: Any = None) -> None:
        self._registry = tool_registry
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute a scheduler action."""
        action = params.get("action", "")

        if action == "add":
            return self._add_task(params)
        elif action == "remove":
            return self._remove_task(params)
        elif action == "list":
            return self._list_tasks()
        elif action == "run_now":
            return await self._run_now(params)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    def _add_task(self, params: dict[str, Any]) -> ToolResult:
        """Add a scheduled task."""
        name = params.get("name", "")
        command = params.get("command", "")
        interval = params.get("interval_seconds", 60.0)

        if not name or not command:
            return ToolResult(success=False, error="Name and command are required")

        task = ScheduledTask(
            name=name,
            command=command,
            interval_seconds=interval,
        )
        self._tasks[name] = task
        logger.info("Task scheduled", name=name, interval=interval)
        return ToolResult(success=True, output=f"Task '{name}' scheduled every {interval}s")

    def _remove_task(self, params: dict[str, Any]) -> ToolResult:
        """Remove a scheduled task."""
        name = params.get("name", "")
        if name in self._tasks:
            del self._tasks[name]
            return ToolResult(success=True, output=f"Task '{name}' removed")
        return ToolResult(success=False, error=f"Task '{name}' not found")

    def _list_tasks(self) -> ToolResult:
        """List all scheduled tasks."""
        if not self._tasks:
            return ToolResult(success=True, output="No scheduled tasks")

        lines = []
        for name, task in self._tasks.items():
            status = "enabled" if task.enabled else "disabled"
            lines.append(f"- {name}: {task.command} (every {task.interval_seconds}s, {status})")

        return ToolResult(success=True, output="\n".join(lines))

    async def _run_now(self, params: dict[str, Any]) -> ToolResult:
        """Immediately run a scheduled task."""
        name = params.get("name", "")
        task = self._tasks.get(name)
        if task is None:
            return ToolResult(success=False, error=f"Task '{name}' not found")

        if self._registry is None:
            return ToolResult(success=False, error="Tool registry not available")

        result = await self._registry.execute("execute_command", {"command": task.command})
        task.last_run = datetime.now()
        return result
