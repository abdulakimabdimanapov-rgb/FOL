"""Recorder tool — record and replay user actions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from modules.tools.base import AbstractTool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class RecordedAction:
    """A single recorded action."""

    id: UUID = field(default_factory=uuid4)
    tool: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    delay_from_previous: float = 0.0


@dataclass
class Recording:
    """A recording session."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    actions: list[RecordedAction] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    is_recording: bool = False


class RecorderTool(AbstractTool):
    """Record and replay sequences of actions."""

    name = "recorder"
    description = "Record user actions and replay them as macros."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "record_step", "replay", "list", "save", "load"],
                "description": "Recorder action",
            },
            "name": {"type": "string", "description": "Recording name"},
            "tool": {"type": "string", "description": "Tool name (for record_step)"},
            "params": {"type": "object", "description": "Tool params (for record_step)"},
        },
        "required": ["action"],
    }

    def __init__(self, tool_registry: Any = None, recordings_dir: str = "~/.fol/recordings") -> None:
        self._registry = tool_registry
        self._recordings_dir = Path(recordings_dir).expanduser()
        self._recordings_dir.mkdir(parents=True, exist_ok=True)
        self._current: Recording | None = None
        self._recordings: dict[str, Recording] = {}

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        """Execute a recorder action."""
        action = params.get("action", "")

        if action == "start":
            return self._start_recording(params)
        elif action == "stop":
            return self._stop_recording()
        elif action == "record_step":
            return self._record_step(params)
        elif action == "replay":
            return await self._replay(params)
        elif action == "list":
            return self._list_recordings()
        elif action == "save":
            return self._save(params)
        elif action == "load":
            return self._load(params)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    def _start_recording(self, params: dict[str, Any]) -> ToolResult:
        """Start a new recording."""
        name = params.get("name", f"recording_{uuid4().hex[:8]}")
        self._current = Recording(name=name, is_recording=True)
        logger.info("Recording started", name=name)
        return ToolResult(success=True, output=f"Recording '{name}' started")

    def _stop_recording(self) -> ToolResult:
        """Stop current recording."""
        if self._current is None:
            return ToolResult(success=False, error="No active recording")

        self._current.is_recording = False
        name = self._current.name
        self._recordings[name] = self._current
        count = len(self._current.actions)
        self._current = None
        logger.info("Recording stopped", name=name, actions=count)
        return ToolResult(success=True, output=f"Recording '{name}' stopped with {count} actions")

    def _record_step(self, params: dict[str, Any]) -> ToolResult:
        """Record a single step in the current recording."""
        if self._current is None or not self._current.is_recording:
            return ToolResult(success=False, error="No active recording")

        tool = params.get("tool", "")
        tool_params = params.get("params", {})

        import time
        now = time.time()
        delay = now - (self._current.actions[-1].timestamp if self._current.actions else now)

        action = RecordedAction(
            tool=tool,
            params=tool_params,
            timestamp=now,
            delay_from_previous=delay,
        )
        self._current.actions.append(action)
        return ToolResult(success=True, output=f"Step recorded: {tool}")

    async def _replay(self, params: dict[str, Any]) -> ToolResult:
        """Replay a recording."""
        name = params.get("name", "")
        recording = self._recordings.get(name)
        if recording is None:
            return ToolResult(success=False, error=f"Recording '{name}' not found")

        if self._registry is None:
            return ToolResult(success=False, error="Tool registry not available")

        import asyncio
        results = []
        for i, action in enumerate(recording.actions):
            if action.delay_from_previous > 0:
                await asyncio.sleep(action.delay_from_previous)

            result = await self._registry.execute(action.tool, action.params)
            results.append({
                "step": i + 1,
                "tool": action.tool,
                "success": result.success,
            })

            if not result.success:
                return ToolResult(
                    success=False,
                    error=f"Replay failed at step {i + 1}: {result.error}",
                    metadata={"results": results},
                )

        return ToolResult(
            success=True,
            output=f"Replay '{name}' completed: {len(recording.actions)} actions",
            metadata={"results": results},
        )

    def _list_recordings(self) -> ToolResult:
        """List all saved recordings."""
        if not self._recordings:
            return ToolResult(success=True, output="No recordings saved")

        lines = []
        for name, rec in self._recordings.items():
            lines.append(f"- {name}: {len(rec.actions)} actions")
        return ToolResult(success=True, output="\n".join(lines))

    def _save(self, params: dict[str, Any]) -> ToolResult:
        """Save a recording to disk."""
        name = params.get("name", "")
        recording = self._recordings.get(name)
        if recording is None:
            return ToolResult(success=False, error=f"Recording '{name}' not found")

        path = self._recordings_dir / f"{name}.json"
        data = {
            "name": recording.name,
            "actions": [
                {"tool": a.tool, "params": a.params, "delay": a.delay_from_previous}
                for a in recording.actions
            ],
        }
        path.write_text(json.dumps(data, indent=2))
        return ToolResult(success=True, output=f"Recording saved to {path}")

    def _load(self, params: dict[str, Any]) -> ToolResult:
        """Load a recording from disk."""
        name = params.get("name", "")
        path = self._recordings_dir / f"{name}.json"
        if not path.exists():
            return ToolResult(success=False, error=f"Recording file '{name}.json' not found")

        data = json.loads(path.read_text())
        recording = Recording(name=data["name"])
        for a in data.get("actions", []):
            recording.actions.append(
                RecordedAction(
                    tool=a["tool"],
                    params=a.get("params", {}),
                    delay_from_previous=a.get("delay", 0.0),
                )
            )
        self._recordings[recording.name] = recording
        return ToolResult(success=True, output=f"Recording '{name}' loaded with {len(recording.actions)} actions")
