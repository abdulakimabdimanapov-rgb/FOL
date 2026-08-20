"""Tests for the unified proactive system.

Covers:
- ProactiveAssistant — deterministic rules (existing).
- ProactiveLLMEngine — LLM-based generation (profile/pattern/ambient),
  parsing, duplicate prevention, failure handling.
- ProactiveEngine — the ONE runtime engine: rules + LLM sources behind a
  single toggle/cooldown/cap policy and subscriber-based event emission.
"""

from __future__ import annotations

import json

import pytest

from modules.llm.proactive import (
    ProactiveAssistant,
    ProactiveEngine,
    ProactiveLLMEngine,
)


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


# ---------------------------------------------------------------------------
# ProactiveLLMEngine — parsing
# ---------------------------------------------------------------------------

class TestProactiveLLMEngineParse:
    def test_parse_valid_suggestions_array(self):
        engine = ProactiveLLMEngine(llm_fn=lambda sp, uc: "")
        text = json.dumps({
            "suggestions": [
                {"title": "Research X", "description": "Do research", "confidence": 0.9, "action_id": "research"},
                {"title": "Low confidence", "description": "Maybe", "confidence": 0.3, "action_id": "maybe"},
            ]
        })
        result = engine.parse_suggestions(text)
        assert len(result) == 1  # Only the one above threshold
        assert result[0]["title"] == "Research X"
        assert result[0]["confidence"] == 0.9

    def test_parse_markdown_fenced(self):
        engine = ProactiveLLMEngine(llm_fn=lambda sp, uc: "")
        text = '```json\n{"suggestions": [{"title": "T", "confidence": 0.9}]}\n```'
        result = engine.parse_suggestions(text)
        assert result and result[0]["title"] == "T"

    def test_parse_empty_and_malformed(self):
        engine = ProactiveLLMEngine(llm_fn=lambda sp, uc: "")
        assert engine.parse_suggestions("") == []
        assert engine.parse_suggestions(None) == []
        assert engine.parse_suggestions("not json") == []
        assert engine.parse_suggestions(json.dumps({"suggestions": []})) == []

    def test_parse_stringifies_context(self):
        engine = ProactiveLLMEngine(llm_fn=lambda sp, uc: "")
        text = json.dumps({"suggestions": [{"title": "T", "confidence": 0.9, "context": {"company": "Stripe"}}]})
        result = engine.parse_suggestions(text)
        assert result[0]["context"] == {"company": "Stripe"}


# ---------------------------------------------------------------------------
# ProactiveLLMEngine — triggers
# ---------------------------------------------------------------------------

class TestProactiveLLMEngineTriggers:
    def test_profile_trigger_generates_and_tags_source(self):
        fake_llm = lambda sp, uc: json.dumps({  # noqa: E731
            "suggestions": [{"title": "Research X", "description": "D", "confidence": 0.9, "action_id": "research"}]
        })
        engine = ProactiveLLMEngine(llm_fn=fake_llm)
        profile = {"name": "Jane", "title": "PM", "company": "Stripe", "interests": ["AI"], "recent_activity": "Blog", "bio": "PM"}
        result = engine.profile_trigger(profile)
        assert len(result) == 1
        assert result[0]["source"] == "profile"

    def test_profile_trigger_empty_profile(self):
        engine = ProactiveLLMEngine(llm_fn=lambda sp, uc: "")
        assert engine.profile_trigger({}) == []
        assert engine.profile_trigger(None) == []

    def test_pattern_trigger_requires_three_messages(self):
        engine = ProactiveLLMEngine(llm_fn=lambda sp, uc: json.dumps({"suggestions": [{"title": "P", "confidence": 0.8}]}))
        short = [{"role": "user", "content": "Research John"}, {"role": "user", "content": "Research Sarah"}]
        assert engine.pattern_trigger(short) == []
        assert engine.pattern_trigger([]) == []

    def test_pattern_trigger_detects(self):
        fake_llm = lambda sp, uc: json.dumps({  # noqa: E731
            "suggestions": [{"title": "Auto-research", "description": "D", "confidence": 0.8, "action_id": "auto"}]
        })
        engine = ProactiveLLMEngine(llm_fn=fake_llm)
        history = [
            {"role": "user", "content": "Research John"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Research Sarah"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Research Bob"},
        ]
        result = engine.pattern_trigger(history)
        assert len(result) == 1
        assert result[0]["source"] == "pattern"

    def test_ambient_tick_works_without_screenshot(self, monkeypatch):
        fake_llm = lambda sp, uc: json.dumps({  # noqa: E731
            "suggestions": [{"title": "Ambient", "description": "D", "confidence": 0.8, "action_id": "a"}]
        })
        engine = ProactiveLLMEngine(llm_fn=fake_llm)
        monkeypatch.setattr(engine, "_fetch_screenshot", lambda: None)
        result = engine.ambient_tick([{"role": "user", "content": "hi"}], {"name": "N"})
        assert len(result) == 1
        assert result[0]["source"] == "ambient"

    def test_llm_failure_returns_empty(self):
        def boom(sp, uc):
            raise RuntimeError("provider down")

        engine = ProactiveLLMEngine(llm_fn=boom)
        assert engine.profile_trigger({"name": "X"}) == []


# ---------------------------------------------------------------------------
# ProactiveLLMEngine — duplicate prevention
# ---------------------------------------------------------------------------

class TestProactiveLLMEngineDedupe:
    def test_dedupe_drops_repeated_suggestions(self):
        engine = ProactiveLLMEngine(llm_fn=lambda sp, uc: "")
        one = [{"source": "profile", "title": "T", "id": "1"}]
        assert engine.dedupe(one) == one
        assert engine.dedupe(one) == []  # same source+title -> dropped


# ---------------------------------------------------------------------------
# ProactiveEngine — unified runtime
# ---------------------------------------------------------------------------

class TestProactiveEngine:
    async def test_rule_path_emits_and_respects_toggle(self):
        engine = ProactiveEngine(enabled=True, cooldown_minutes=0)
        events = []
        engine.subscribe(events.append)

        # Force rules: morning context fires a suggestion.
        suggestion = await engine.suggest_rules({"hour": 7}, force=True)
        assert suggestion is not None
        assert len(events) == 1
        assert events[0]["kind"] == "proactive"
        assert events[0]["source"] == "rules"

    async def test_llm_path_emits_with_source(self):
        fake_llm = lambda sp, uc: json.dumps({  # noqa: E731
            "suggestions": [{"title": "Research X", "description": "D", "confidence": 0.9, "action_id": "r"}]
        })
        engine = ProactiveEngine(enabled=True, cooldown_minutes=0, llm_engine=ProactiveLLMEngine(llm_fn=fake_llm))
        events = []
        engine.subscribe(events.append)
        emitted = await engine.suggest_llm("profile", {"name": "Jane", "title": "PM", "company": "S", "interests": [], "recent_activity": "", "bio": ""})
        assert len(emitted) == 1
        assert emitted[0]["source"] == "profile"
        assert len(events) == 1
        assert events[0]["title"] == "Research X"

    async def test_llm_path_respects_toggle(self):
        engine = ProactiveEngine(enabled=False, llm_engine=ProactiveLLMEngine(llm_fn=lambda sp, uc: json.dumps({"suggestions": [{"title": "X", "confidence": 0.9}]})))
        assert await engine.suggest_llm("profile", {"name": "N"}) == []

    async def test_llm_path_cooldown_suppresses(self):
        fake_llm = lambda sp, uc: json.dumps({  # noqa: E731
            "suggestions": [{"title": "X", "description": "D", "confidence": 0.9, "action_id": "a"}]
        })
        engine = ProactiveEngine(enabled=True, cooldown_minutes=60, llm_engine=ProactiveLLMEngine(llm_fn=fake_llm))
        first = await engine.suggest_llm("profile", {"name": "N", "title": "T", "company": "C", "interests": [], "recent_activity": "", "bio": ""})
        assert len(first) == 1
        # Immediately after -> cooldown suppresses.
        second = await engine.suggest_llm("profile", {"name": "N", "title": "T", "company": "C", "interests": [], "recent_activity": "", "bio": ""})
        assert second == []

    async def test_llm_path_force_bypasses_cooldown(self):
        fake_llm = lambda sp, uc: json.dumps({  # noqa: E731
            "suggestions": [{"title": "X", "description": "D", "confidence": 0.9, "action_id": "a"}]
        })
        engine = ProactiveEngine(enabled=True, cooldown_minutes=60, llm_engine=ProactiveLLMEngine(llm_fn=fake_llm))
        await engine.suggest_llm("profile", {"name": "N", "title": "T", "company": "C", "interests": [], "recent_activity": "", "bio": ""})
        second = await engine.suggest_llm("profile", {"name": "N", "title": "T", "company": "C", "interests": [], "recent_activity": "", "bio": ""}, force=True)
        # force bypasses cooldown, but the engine-level dedupe still drops the
        # same source+title suggestion.
        assert second == []

    async def test_unknown_mode_returns_empty(self):
        engine = ProactiveEngine(enabled=True, cooldown_minutes=0)
        assert await engine.suggest_llm("banana", {}) == []

    async def test_subscriber_failure_is_isolated(self):
        engine = ProactiveEngine(enabled=True, cooldown_minutes=0)

        def bad_cb(payload):
            raise RuntimeError("subscriber boom")

        engine.subscribe(bad_cb)
        suggestion = await engine.suggest_rules({"hour": 7}, force=True)
        assert suggestion is not None  # emission failure never breaks the engine

    def test_unsubscribe(self):
        engine = ProactiveEngine()
        cb = lambda p: None  # noqa: E731
        engine.subscribe(cb)
        engine.unsubscribe(cb)
        assert cb not in engine._subscribers

    def test_stats_include_llm_sources(self):
        engine = ProactiveEngine(enabled=True)
        assert engine.stats()["llm_sources"] == ["profile", "pattern", "ambient"]
