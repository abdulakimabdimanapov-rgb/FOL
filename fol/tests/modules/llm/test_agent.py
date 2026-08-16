"""Tests for ReActAgent."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from modules.llm.agent import ReActAgent, AgentStep


def test_parse_action_json():
    agent = ReActAgent(llm_engine=MagicMock())
    result = agent._parse_action('```json\n{"thought": "test", "action": "echo", "params": {"msg": "hi"}}\n```')
    assert result is not None
    assert result["action"] == "echo"


def test_parse_action_inline():
    agent = ReActAgent(llm_engine=MagicMock())
    result = agent._parse_action('{"thought": "test", "action": "run"}')
    assert result is not None
    assert result["action"] == "run"


def test_parse_action_none():
    agent = ReActAgent(llm_engine=MagicMock())
    result = agent._parse_action("Just a normal response with no JSON")
    assert result is None


def test_steps_empty():
    agent = ReActAgent(llm_engine=MagicMock())
    assert agent.steps == []


def test_agent_step():
    step = AgentStep(thought="thinking", action="test", params={"x": 1}, observation="done")
    assert step.thought == "thinking"
    assert step.observation == "done"
