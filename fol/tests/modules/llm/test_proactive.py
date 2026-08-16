"""Tests for ProactiveAssistant."""

from __future__ import annotations

import pytest
from modules.llm.proactive import ProactiveAssistant


@pytest.fixture
def assistant() -> ProactiveAssistant:
    return ProactiveAssistant()


@pytest.mark.asyncio
async def test_morning_suggestion(assistant: ProactiveAssistant):
    suggestion = await assistant.evaluate({"hour": 7})
    assert suggestion is not None
    # Morning suggestion — title can be in Russian ("Доброе утро") or English ("morning")
    title_lower = suggestion.title.lower()
    assert "morning" in title_lower or "утро" in title_lower, f"Expected morning/утро in title: {suggestion.title}"


@pytest.mark.asyncio
async def test_no_suggestion(assistant: ProactiveAssistant):
    suggestion = await assistant.evaluate({"hour": 14})
    assert suggestion is None


@pytest.mark.asyncio
async def test_repeated_command(assistant: ProactiveAssistant):
    suggestion = await assistant.evaluate({"repeated_count": 5})
    assert suggestion is not None
    # Automation suggestion — title can be in Russian ("Автоматизация") or English ("frequent")
    title_lower = suggestion.title.lower()
    assert "frequent" in title_lower or "автоматизац" in title_lower or "автоматиз" in title_lower, f"Expected frequent/автоматизация in title: {suggestion.title}"


@pytest.mark.asyncio
async def test_dismiss(assistant: ProactiveAssistant):
    suggestion = await assistant.evaluate({"hour": 7})
    assert suggestion is not None
    result = await assistant.dismiss_suggestion(suggestion.title)
    assert result


def test_rule_count(assistant: ProactiveAssistant):
    assert assistant.rule_count >= 3
