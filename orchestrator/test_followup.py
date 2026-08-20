"""
Follow-up resolution tests.

Covers the conservative rewrite rules in orchestrator/followup.py:
- pronouns and short referents (это, там, он, она, ещё, а теперь, ...)
- short questions without pronouns ("Какая самая важная?")
- negative cases (greetings, new commands, no history)
"""

from __future__ import annotations

import pytest

from followup import resolve_followup

HISTORY = [
    {"role": "user", "content": "Найди новости про OpenAI."},
    {"role": "assistant", "content": "Нашёл несколько новостей: 1) новый релиз GPT-5. 2) инвестиции в робототехнику."},
]


def _last(assistant_text: str):
    return [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": assistant_text},
    ]


class TestPronounFollowups:
    @pytest.mark.parametrize(
        "followup",
        [
            "Что из этого самое важное?",
            "Расскажи про это подробнее",
            "А что там было главное?",
            "Он хороший?",
            "Она подходит?",
            "Ещё что-нибудь",
            "А теперь про Илона Маска",
            "Продолжай",
            "Сделай так же для Apple",
            "Какой из них лучший?",
            "Первый вариант",
            "Последний",
        ],
    )
    def test_pronoun_followup_is_rewritten(self, followup):
        rewritten, changed = resolve_followup(followup, HISTORY)
        assert changed is True
        assert "Нашёл несколько новостей" in rewritten
        assert followup in rewritten

    def test_save_this_inserts_referent(self):
        rewritten, changed = resolve_followup("Сохрани это в Obsidian", HISTORY)
        assert changed is True
        assert "\x01" not in rewritten  # regression: \1 must not become SOH
        assert rewritten.lower().startswith("сохрани \"нашёл несколько новостей")
        assert "это в Obsidian" in rewritten

    def test_translate_this_is_a_followup(self):
        rewritten, changed = resolve_followup("Переведи это на английский", HISTORY)
        assert changed is True
        assert "Относительно предыдущего результата" in rewritten


class TestShortQuestionFollowups:
    @pytest.mark.parametrize(
        "question",
        [
            "Какая самая важная?",
            "Что самое главное?",
            "Какие минусы?",
            "А в чём суть?",
        ],
    )
    def test_short_question_is_rewritten(self, question):
        rewritten, changed = resolve_followup(question, HISTORY)
        assert changed is True
        assert "Относительно предыдущего результата" in rewritten
        assert question in rewritten

    def test_long_question_not_rewritten(self):
        rewritten, changed = resolve_followup("А что ты думаешь про эти новости и их влияние на рынок труда в Европе?", HISTORY)
        assert changed is False
        assert rewritten == "А что ты думаешь про эти новости и их влияние на рынок труда в Европе?"


class TestNegativeCases:
    @pytest.mark.parametrize(
        "message",
        [
            "привет",
            "как дела?",
            "hello",
            "Найди новости про Anthropic",
            "Открой VS Code",
            "Создай новый файл",
            "Сохрани файл",
        ],
    )
    def test_new_command_or_greeting_not_rewritten(self, message):
        rewritten, changed = resolve_followup(message, HISTORY)
        assert changed is False
        assert rewritten == message

    def test_no_history_not_rewritten(self):
        rewritten, changed = resolve_followup("Какая самая важная?", [])
        assert changed is False

    def test_empty_message_not_rewritten(self):
        rewritten, changed = resolve_followup("", HISTORY)
        assert changed is False
        assert rewritten == ""


class TestContextSanitization:
    def test_assistant_json_tool_calls_stripped(self):
        history = [
            {"role": "user", "content": "task"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Вот результат."},
                    {"type": "tool_use", "name": "search_web", "input": {"q": "x"}},
                ],
            },
        ]
        rewritten, changed = resolve_followup("Какая самая важная?", history)
        assert changed is True
        assert "search_web" not in rewritten
        assert "Вот результат." in rewritten

    def test_truncated_long_context(self):
        long_answer = "слово " * 300
        rewritten, changed = resolve_followup("А что дальше?", _last(long_answer))
        assert changed is True
        assert len(rewritten) < 700  # context truncated to ~400 chars

    def test_rewrite_is_stable_no_double_prepend(self):
        r1, c1 = resolve_followup("Какая самая важная?", HISTORY)
        assert c1
        # Feeding the rewritten message back must not produce another prepend
        r2, c2 = resolve_followup(r1, HISTORY)
        assert c2 is False or r2 == r1
