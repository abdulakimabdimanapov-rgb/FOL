"""RESPONSE QUALITY regression tests.

Problem: small local models (Ollama llama3.2:3b, MLX Qwen2.5-0.5B) frequently
answer ANY input with a generic offer of help:

    "How can I help you?"
    "What can I help you with?"
    "I'm here to help."
    "Чем могу помочь?"

That is a greeting-like non-answer and must NEVER be the final response to a
concrete question. Contract under test:

  1. A concrete user question must receive a concrete answer — and at minimum
     never a generic offer of help.
  2. Generic offers of help are allowed ONLY when the user actually greets FOL
     or asks about FOL's capabilities.
  3. The response follows the user's language (RU/EN/mixed).
  4. Previous conversation context is used for follow-ups.
  5. The same sentence is never repeated.
  6. No hallucinated capabilities.
  7. If the model cannot answer, the response explains why + concrete options.
"""

from __future__ import annotations

import pytest

from modules.llm.personality import (
    _is_generic_help_offer,
    _is_pure_greeting,
    _user_asks_capabilities,
    dedupe_repeated_sentences,
    polish_response,
)

# ─── Detection unit tests ───────────────────────────────────────────────────

GENERIC_OFFERS = (
    "How can I help you?",
    "How can I help you today?",
    "How may I help you?",
    "How can I assist you?",
    "How can I be of assistance?",
    "What can I help you with?",
    "What can I help you with today?",
    "What can I do for you?",
    "What can I do to help?",
    "What do you need help with?",
    "What would you like me to do?",
    "Is there anything I can help you with?",
    "Is there anything else I can help you with?",
    "Let me know how I can help.",
    "Let me know what you need.",
    "I'm here to help.",
    "I am here to help.",
    "Hi! How can I help you?",
    "Hello! What can I do for you today? 😊",
    "Чем могу помочь?",
    "Чем я могу помочь?",
    "Чем могу быть полезен?",
    "Чем помочь?",
    "Чем вам помочь?",
    "Как я могу помочь?",
    "Что я могу сделать для вас?",
    "Я здесь, чтобы помочь.",
    "Привет! Чем могу помочь?",
)

NOT_GENERIC_OFFERS = (
    # Real answers that merely mention help — must pass through.
    "I can help you set up the printer. First, open System Settings.",
    "How can I help you with your code? Let's look at the error.",
    "Чем могу помочь: могу открывать приложения, искать информацию и помнить важное.",
    "Я могу помочь с проектом — расскажи подробнее, что нужно сделать.",
    # Long content dominates the phrase.
    "How can I help you? Here are the steps to fix the issue: restart the service, "
    "check the logs, and verify the config. That usually resolves the problem.",
    # The user's own words quoted inside a real answer.
    "You asked 'What can I help you with?' — the answer is: start with the README.",
)


class TestGenericHelpDetection:
    @pytest.mark.parametrize("text", GENERIC_OFFERS)
    def test_generic_offers_detected(self, text):
        assert _is_generic_help_offer(text), f"must detect: {text!r}"

    @pytest.mark.parametrize("text", NOT_GENERIC_OFFERS)
    def test_real_answers_not_detected(self, text):
        assert not _is_generic_help_offer(text), f"must NOT detect: {text!r}"

    @pytest.mark.parametrize("empty", ["", "   ", None])
    def test_empty_never_flagged(self, empty):
        assert not _is_generic_help_offer(empty)


class TestGreetingAndCapabilityGuards:
    @pytest.mark.parametrize("msg", ["Привет", "Hello", "Hi", "Добрый день", "Hey there",
                                     "Привет!", "hello"])
    def test_pure_greeting(self, msg):
        assert _is_pure_greeting(msg), msg

    @pytest.mark.parametrize("msg", [
        "Привет, какой сегодня день?", "Hello, what time is it?",
        "What is the capital of France?", "Открой Safari",
        "А какая самая важная?", "Привет, открой Safari",
    ])
    def test_not_pure_greeting(self, msg):
        assert not _is_pure_greeting(msg), msg

    @pytest.mark.parametrize("msg", [
        "Что ты умеешь?", "what can you do", "Чем можешь помочь?",
        "What are your capabilities?", "что ты можешь",
    ])
    def test_capability_questions(self, msg):
        assert _user_asks_capabilities(msg), msg

    @pytest.mark.parametrize("msg", [
        "How can I help you?", "Расскажи про энтропию", "Что такое FOL?",
    ])
    def test_not_capability_questions(self, msg):
        assert not _user_asks_capabilities(msg), msg


# ─── The core contract: concrete questions never get a help offer ───────────

class TestConcreteQuestionsNeverGeneric:
    @pytest.mark.parametrize("question,offer", [
        ("What is the capital of France?", "How can I help you?"),
        ("What is the capital of France?", "What can I help you with?"),
        ("Расскажи про энтропию", "Чем могу помочь?"),
        ("Как работает интернет?", "Чем я могу помочь?"),
        ("What is the capital of France?", "I'm here to help."),
        ("Расскажи про энтропию", "Hi! How can I help you?"),
    ])
    def test_offer_replaced(self, question, offer):
        out = polish_response(question, offer)
        assert out and out.strip()
        assert "How can I help you?" not in out
        assert "What can I help you with?" not in out
        assert "Чем могу помочь" not in out
        assert "I'm here to help" not in out
        assert "{" not in out

    def test_replacement_explains_and_offers_concrete_actions_ru(self):
        out = polish_response("Что такое энтропия?", "Чем могу помочь?")
        # Requirement 7: explain the limit + concrete options, never a bare offer.
        assert "интернет" in out.lower() or "память" in out.lower()
        assert "Чем могу помочь?" not in out

    def test_replacement_explains_and_offers_concrete_actions_en(self):
        out = polish_response("What is the capital of France?", "How can I help you?")
        assert "search the web" in out or "check memory" in out
        assert "How can I help you?" not in out

    def test_unknown_request_ru(self):
        out = polish_response("Что такое квантовая запутанность?", "Чем могу помочь?")
        assert out and "Чем могу помочь?" not in out

    def test_command_request_never_generic(self):
        # Even a command request must not get a generic help offer.
        out = polish_response("Открой Safari", "How can I help you?")
        assert out and "How can I help you?" not in out

    def test_followup_question_never_generic(self):
        out = polish_response("А какая самая важная?", "Чем могу помочь?")
        assert out and "Чем могу помочь?" not in out


# ─── Greeting / capability exemptions ───────────────────────────────────────

class TestExemptions:
    def test_greeting_may_get_offer(self):
        # Requirement 2: offers of help are allowed when the user greets FOL.
        out = polish_response("Привет", "Привет! Чем могу помочь?")
        assert out and out.strip()

    def test_capability_question_offer_allowed(self):
        # The user asked what FOL can do — the answer may be help-shaped.
        out = polish_response("Что ты умеешь?", "Чем могу помочь?")
        assert out and out.strip()


# ─── Language preservation ──────────────────────────────────────────────────

class TestLanguagePreservation:
    def test_ru_question_ru_replacement(self):
        out = polish_response("Что такое энтропия?", "How can I help you?")
        assert any(ord(c) > 0x0400 for c in out), "RU question must get a RU answer"

    def test_en_question_en_replacement(self):
        out = polish_response("What is entropy?", "Чем могу помочь?")
        assert out.isascii(), "EN question must get an EN answer"

    def test_mixed_question_follows_dominant(self):
        out = polish_response("открой Safari и найди новости про OpenAI", "How can I help you?")
        assert any(ord(c) > 0x0400 for c in out), "RU-dominant input must get a RU answer"


# ─── No repeated sentences (small-model stutter) ────────────────────────────

class TestNoRepeats:
    def test_dedupe_consecutive(self):
        assert dedupe_repeated_sentences(
            "I can check that for you. I can check that for you."
        ) == "I can check that for you."

    def test_dedupe_case_insensitive(self):
        assert dedupe_repeated_sentences(
            "Открыл. ОТКРЫЛ."
        ) == "Открыл."

    def test_dedupe_does_not_touch_distinct_sentences(self):
        text = "First. Second. First."
        assert dedupe_repeated_sentences(text) == text

    def test_stutter_polished_away(self):
        out = polish_response("Which file should I edit?", "Open the README. Open the README.")
        assert out.count("Open the README") == 1

    def test_repeated_generic_never_final(self):
        out = polish_response("What is entropy?", "How can I help you? How can I help you?")
        assert "How can I help you?" not in out
