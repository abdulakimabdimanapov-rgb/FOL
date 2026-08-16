"""Shared helper functions for orchestrator/server.py integration tests.

Reusable across test files:
- _mock_chat_setup: common mocks for /chat endpoint
- _mock_command_setup: common mocks for /command endpoint
- _parse_sse_events: parse SSE event streams

Note: sys.path is set up by conftest.py (loaded first by pytest).
"""
from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import patch

from agents import AgentType


def _mock_chat_setup() -> tuple[ExitStack, object, object, object]:
    """Set up common mocks for /chat endpoint tests (patches run_agent_loop_streaming).

    Returns (ExitStack, mock_loop, mock_system, mock_route).
    Caller must use ``with stack:`` to activate patches.
    """
    stack = ExitStack()
    mock_loop = stack.enter_context(patch("server.run_agent_loop_streaming"))
    mock_system = stack.enter_context(patch("server.build_system_prompt", return_value="prompt"))
    stack.enter_context(patch("server.build_context_messages", return_value=[]))
    stack.enter_context(patch("server._append_to_history"))
    mock_route = stack.enter_context(patch("server._auto_route_agent"))
    mock_route.return_value = AgentType.GENERAL
    return stack, mock_loop, mock_system, mock_route


def _mock_command_setup() -> tuple[ExitStack, object, object, object]:
    """Set up common mocks for /command endpoint tests (patches run_agent_loop).

    Returns (ExitStack, mock_loop, mock_system, mock_route).
    Caller must use ``with stack:`` to activate patches.
    """
    stack = ExitStack()
    mock_loop = stack.enter_context(patch("server.run_agent_loop"))
    mock_system = stack.enter_context(patch("server.build_system_prompt", return_value="prompt"))
    stack.enter_context(patch("server.build_context_messages", return_value=[]))
    stack.enter_context(patch("server._append_to_history"))
    mock_route = stack.enter_context(patch("server._auto_route_agent"))
    mock_route.return_value = AgentType.GENERAL
    return stack, mock_loop, mock_system, mock_route


def _parse_sse_events(lines: list[str | bytes]) -> list[dict]:
    """Parse SSE event stream lines into structured events.

    Each SSE event is a block of:
        event: <type>
        data: <json>
        <blank line>

    Returns a list of {"event": str, "data": dict} dicts.
    """
    events: list[dict] = []
    current_event: str | None = None
    current_data: str | None = None

    for line in lines:
        if not line:  # blank line = end of event
            if current_event is not None and current_data is not None:
                try:
                    parsed_data = json.loads(current_data)
                except (json.JSONDecodeError, TypeError):
                    parsed_data = current_data
                events.append({"event": current_event, "data": parsed_data})
            current_event = None
            current_data = None
            continue

        line_str = line if isinstance(line, str) else line.decode("utf-8")

        if line_str.startswith("event: "):
            current_event = line_str[len("event: "):].strip()
        elif line_str.startswith("data: "):
            current_data = line_str[len("data: "):].strip()

    # Flush last event if the stream ended without a blank line
    if current_event is not None and current_data is not None:
        try:
            parsed_data = json.loads(current_data)
        except (json.JSONDecodeError, TypeError):
            parsed_data = current_data
        events.append({"event": current_event, "data": parsed_data})

    return events
