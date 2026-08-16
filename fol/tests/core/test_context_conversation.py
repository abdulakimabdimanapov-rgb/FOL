"""Tests for the Context Conversation feature — follow-up detection and grounding.

ROADMAP Этап 1: «Найди новости про OpenAI» → «А какая из них самая важная?» →
FOL должен понимать, что речь всё ещё про OpenAI.
"""

from __future__ import annotations

import pytest

from core.context_manager import ContextManager
from core.orchestrator import Orchestrator


def _seeded_cm() -> ContextManager:
    """A context manager with one established topic (OpenAI news)."""
    cm = ContextManager()
    cm.add_turn("Найди новости про OpenAI", "OpenAI представила новую модель. Цены выросли.")
    return cm


class TestFollowUpDetection:
    @pytest.mark.parametrize(
        "text",
        [
            # Russian continuations
            "А какая из них самая важная?",
            "а что с ценами?",
            "и ещё про новые модели",
            "расскажи подробнее",
            "дальше",
            "продолжай",
            "кстати, а что с акциями?",
            "а SpaceX?",
            "а потом что?",
            # English continuations
            "What about the new model?",
            "and how does it compare to GPT?",
            "tell me more",
            "continue",
            "but why is that?",
            "what else?",
        ],
    )
    def test_detects_follow_ups(self, text: str):
        cm = _seeded_cm()
        assert cm.is_follow_up(text), f"{text!r} should be a follow-up"

    @pytest.mark.parametrize(
        "text",
        [
            # New topics / fresh commands must NOT be treated as follow-ups
            "Привет",
            "Открой Safari",
            "Напиши код для сортировки",
            "Включи музыку",
            "Сколько сейчас времени?",
            "запусти тесты",
            "Which restaurants do you recommend?",
            "Create a new file",
            "Почему небо синее?",
            "Как приготовить пасту?",
        ],
    )
    def test_does_not_detect_new_topics(self, text: str):
        cm = _seeded_cm()
        assert not cm.is_follow_up(text), f"{text!r} should NOT be a follow-up"

    @pytest.mark.parametrize(
        "text",
        [
            # Long "А…"/"And…" sentences start a NEW topic — the generic
            # conjunction prefix must not force them back into the old one.
            "А вчера я ходил в кино с друзьями и видел новый фильм",
            "А как тебе новый iPhone от Apple?",
            "И ещё хочу спросить про мой отпуск летом",
            "And also fix the bug in file.py that I found earlier",
            "But the weather in Moscow is really nice today",
        ],
    )
    def test_long_conjunction_pivot_is_not_follow_up(self, text: str):
        cm = _seeded_cm()
        assert not cm.is_follow_up(text), f"{text!r} is a pivot, not a follow-up"

    def test_short_conjunction_still_follow_up(self):
        # Short messages that start with a conjunction ARE follow-ups.
        cm = _seeded_cm()
        assert cm.is_follow_up("а SpaceX?")
        assert cm.is_follow_up("и ещё про новые модели")

    def test_no_history_is_never_follow_up(self):
        assert not ContextManager().is_follow_up("а что?")

    def test_empty_input(self):
        assert not _seeded_cm().is_follow_up("   ")


class TestCurrentTopic:
    def test_extracts_named_entity(self):
        topic = _seeded_cm().get_current_topic()
        assert "OpenAI" in topic

    def test_ignores_sentence_start_words(self):
        cm = ContextManager()
        cm.add_turn("python is great", "It is indeed great")
        topic = cm.get_current_topic()
        assert "It" not in topic  # sentence-start capitalization, not an entity
        assert "python" in topic.lower()

    def test_empty_history(self):
        assert ContextManager().get_current_topic() == ""


class TestFollowUpContextBlock:
    def test_grounds_follow_up_in_topic(self):
        cm = _seeded_cm()
        block = cm.get_follow_up_context()
        assert "OpenAI" in block
        assert "follow-up" in block
        assert "Найди новости про OpenAI" in block

    def test_empty_history(self):
        assert ContextManager().get_follow_up_context() == ""

    def test_english_context(self):
        cm = ContextManager()
        cm.add_turn("Find news about OpenAI", "OpenAI released a new model")
        block = cm.get_follow_up_context()
        assert "OpenAI" in block
        assert "Find news about OpenAI" in block

    def test_clear_history_resets_follow_ups(self):
        cm = _seeded_cm()
        assert cm.is_follow_up("а какая из них самая важная?")
        cm.clear_history()
        assert cm.history_length == 0
        assert not cm.is_follow_up("а какая из них самая важная?")
        assert cm.get_follow_up_context() == ""


class TestOrchestratorGrounding:
    @pytest.mark.asyncio
    async def test_assemble_context_adds_follow_up_block(self, orchestrator: Orchestrator):
        orchestrator._context_manager.add_turn(
            "Найди новости про OpenAI", "OpenAI представила новую модель"
        )
        context = await orchestrator._assemble_context("а какая из них самая важная?", is_follow_up=True)
        assert "OpenAI" in context
        assert "follow-up" in context.lower()

    @pytest.mark.asyncio
    async def test_assemble_context_skips_block_for_new_topic(self, orchestrator: Orchestrator):
        orchestrator._context_manager.add_turn(
            "Найди новости про OpenAI", "OpenAI представила новую модель"
        )
        context = await orchestrator._assemble_context("Открой Safari", is_follow_up=False)
        assert "follow-up" not in context.lower()

    @pytest.mark.asyncio
    async def test_process_input_grounds_follow_up_in_llm_prompt(self, orchestrator: Orchestrator):
        captured: dict = {}

        class FakeLLM:
            async def generate(self, user_input: str, **kwargs):
                captured["input"] = user_input
                captured["context"] = kwargs.get("context", "")
                return "Отвечаю: важная новость."

        orchestrator.register_module("llm", FakeLLM())
        orchestrator._context_manager.add_turn(
            "Найди новости про OpenAI", "OpenAI представила новую модель"
        )
        response = await orchestrator.process_input("а какая из них самая важная?")
        assert response == "Отвечаю: важная новость."
        # The LLM prompt must contain the topic grounding block.
        assert "OpenAI" in captured["context"]
        assert "follow-up" in captured["context"].lower()
        # And the exchange is stored for the next turn.
        assert orchestrator._context_manager.history_length == 2
