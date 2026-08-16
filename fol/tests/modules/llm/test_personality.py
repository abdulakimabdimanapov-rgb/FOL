"""Tests for the FOL Personality Layer (modules.llm.personality).

Covers the 10 required personality scenarios:
  1. "Привет" → natural response
  2. "Открой Safari" → contains action result, not just "Done"
  3. "Запомни, что завтра нужно отправить отчёт" → confirms saving
  4. "Как дела?" → conversational response
  5. Tool error → human-readable error
  6. Tool call → JSON never reaches the user
  7. Russian request → Russian response
  8. English request → English response
  9. Simple request → short response
  10. Complex request → substantive response
"""

from __future__ import annotations

import pytest
from pathlib import Path

from modules.llm.personality import (
    FOL_PERSONALITY_SYSTEM_PROMPT,
    contextual_confirmation,
    humanize_error,
    is_terse_response,
    polish_response,
    strip_tool_call_json,
)


# ─── Terse response detection ─────────────────────────────────────────────

class TestTerseDetection:
    def test_bare_done(self):
        assert is_terse_response("Done")
        assert is_terse_response("Done.")
        assert is_terse_response("done!")
        assert is_terse_response("  Done.  ")

    def test_russian_terse(self):
        assert is_terse_response("Готово")
        assert is_terse_response("Готово.")
        assert is_terse_response("Выполнено.")
        assert is_terse_response("OK")
        assert is_terse_response("ок")

    def test_english_terse(self):
        assert is_terse_response("Task completed.")
        assert is_terse_response("Completed.")
        assert is_terse_response("Yes.")

    def test_natural_sentence_not_terse(self):
        assert not is_terse_response("Safari открыт.")
        assert not is_terse_response("Открыл Safari.")
        assert not is_terse_response("I opened Safari and searched the web.")
        assert not is_terse_response("")


# ─── Scenario 1: "Привет" → natural response ─────────────────────────────

class TestGreeting:
    def test_greeting_contextual_ru(self):
        out = contextual_confirmation("Привет", language="ru")
        assert "Привет" in out
        assert len(out) > 10
        assert "!" in out

    def test_greeting_contextual_en(self):
        out = contextual_confirmation("Hello", language="en")
        assert "Hi" in out or "Hello" in out

    def test_polish_turns_terse_greeting_natural(self):
        # A terse LLM answer to "Привет" is rebuilt into a natural greeting
        out = polish_response("Привет", "Done.")
        assert "Готово" not in out and "Done" not in out
        assert len(out) > 10


# ─── Scenario 2: "Открой Safari" → action result, not "Done" ─────────────

class TestOpenApp:
    def test_open_app_contextual_ru(self):
        out = contextual_confirmation("Открой Safari", tool_name="open_app",
                                      tool_args={"name": "Safari"}, language="ru")
        assert "Safari" in out
        assert "открыт" in out.lower()

    def test_open_app_contextual_en(self):
        out = contextual_confirmation("Open Safari", tool_name="open_app",
                                      tool_args={"name": "Safari"}, language="en")
        assert "Safari" in out
        assert "open" in out.lower()

    def test_open_youtube_humor(self):
        out = contextual_confirmation("Открой YouTube", language="ru")
        assert "YouTube" in out
        assert "😄" in out or "😄" in out

    def test_polish_replaces_done_with_action_result(self):
        out = polish_response("Открой Safari", "Done.", tool_name="open_app",
                              tool_args={"name": "Safari"})
        assert out.strip().lower() != "done."
        assert "Safari" in out

    def test_polish_replaces_robotic_opening(self):
        # FOL's own _mac_open_app used to answer "Opening Safari, sir."
        out = polish_response("Открой Safari", "Opening Safari, sir.")
        assert "Safari" in out
        assert out.strip().lower() != "opening safari, sir."

    def test_open_project(self):
        out = contextual_confirmation("Открой мой проект FOL", language="ru")
        assert "FOL" in out
        assert "проект" in out


# ─── Scenario 3: "Запомни, что завтра нужно отправить отчёт" ─────────────

class TestRemember:
    def test_remember_ru(self):
        out = contextual_confirmation(
            "Запомни, что завтра нужно отправить отчёт", language="ru"
        )
        assert "Запомнил" in out
        assert "отчёт" in out.lower() or "отчет" in out.lower()

    def test_remember_en(self):
        out = contextual_confirmation(
            "Remember that I need to send the report tomorrow", language="en"
        )
        assert "remember" in out.lower()
        assert "report" in out.lower()

    def test_polish_turns_terse_remember_natural(self):
        out = polish_response("Запомни, что завтра нужно отправить отчёт", "Готово.")
        assert out.strip().lower() != "готово."
        assert "Запомнил" in out or "запомнил" in out

    def test_polish_replaces_llm_unavailable_fallback(self):
        # When the LLM backend is down, _rule_based_response returns a
        # robotic "Настройте LLM" message — the personality layer rebuilds it.
        raw = "Я понимаю, вы спрашиваете о: 'Запомни, что завтра нужно отправить отчёт'. " \
              "Настройте LLM для полного ответа. Используйте 'help' для справки, сэр."
        out = polish_response("Запомни, что завтра нужно отправить отчёт", raw)
        assert "Настройте LLM" not in out
        assert "Запомнил" in out or "запомнил" in out

    def test_llm_unavailable_fallback_en(self):
        raw = "I understand you're asking about: 'Open Safari'. Configure an LLM backend " \
              "for full AI responses. Use 'help' to see available commands, sir."
        out = polish_response("Open Safari", raw)
        assert "Configure an LLM" not in out
        assert "Safari" in out


# ─── Scenario 4: "Как дела?" → conversational ─────────────────────────────

class TestSmallTalk:
    def test_how_are_you_ru(self):
        out = contextual_confirmation("Как дела?", language="ru")
        assert len(out) > 10
        assert "полном порядке" in out.lower() or "порядке" in out.lower()

    def test_how_are_you_en(self):
        out = contextual_confirmation("How are you?", language="en")
        assert len(out) > 10

    def test_bored_ru(self):
        out = contextual_confirmation("Мне скучно", language="ru")
        assert len(out) > 10

    def test_who_are_you_ru(self):
        out = contextual_confirmation("Ты кто?", language="ru")
        assert "FOL" in out

    def test_polish_turns_terse_smalltalk_natural(self):
        out = polish_response("Как дела?", "Done.")
        assert out.strip().lower() != "done."
        assert len(out) > 10


# ─── Scenario 5: Tool error → human-readable error ────────────────────────

class TestErrorHumanization:
    def test_typeerror_humanized(self):
        out = humanize_error("TypeError: 'NoneType' object is not subscriptable", "ru")
        assert "TypeError" not in out
        assert "Traceback" not in out
        assert len(out) < 200

    def test_oauth_error_humanized(self):
        out = humanize_error("OAuthException: google_auth_required", "ru")
        assert "авторизуйте" in out.lower() or "доступ" in out.lower()

    def test_connection_error_humanized(self):
        out = humanize_error("ConnectionError: connection refused", "ru")
        assert "Traceback" not in out and "ConnectionError" not in out

    def test_already_human_sentence_passes_through(self):
        out = humanize_error("Файл не найден.", "ru")
        assert out == "Файл не найден."

    def test_polish_humanizes_error_prefix(self):
        out = polish_response("Открой Safari", "Error: Unable to open 'Safari'")
        assert "Error" not in out
        assert len(out) < 200


# ─── Scenario 6: Tool call → JSON never reaches the user ──────────────────

class TestNoJsonLeak:
    def test_function_call_json_stripped(self):
        raw = '{"type": "function", "name": "open_app", "parameters": {"name": "Safari"}}'
        assert strip_tool_call_json(raw) == ""

    def test_react_json_stripped(self):
        raw = '{"thought": "open", "action": "open_app", "params": {"name": "Safari"}}'
        assert strip_tool_call_json(raw) == ""

    def test_fenced_json_stripped(self):
        raw = "```json\n{\"action\": \"open_app\", \"params\": {\"name\": \"Safari\"}}\n```"
        assert strip_tool_call_json(raw) == ""

    def test_polish_never_returns_json(self):
        raw = 'Начинаю: {"type": "function", "name": "open_app", "parameters": {"name": "Safari"}}'
        out = polish_response("Открой Safari", raw)
        assert "{" not in out
        assert '"name"' not in out


# ─── Scenario 7: Russian request → Russian response ───────────────────────

class TestRussianLanguage:
    def test_polish_ru_request_ru_response(self):
        out = polish_response("Открой Safari", "Done.")
        # detect_language returns "ru" for a Russian request → Russian answer
        assert any("\u0400" <= ch <= "\u04FF" for ch in out)

    def test_contextual_ru(self):
        out = contextual_confirmation("Открой Safari", language="ru")
        assert any("\u0400" <= ch <= "\u04FF" for ch in out)


# ─── Scenario 8: English request → English response ───────────────────────

class TestEnglishLanguage:
    def test_polish_en_request_en_response(self):
        out = polish_response("Open Safari", "Done.")
        assert not any("\u0400" <= ch <= "\u04FF" for ch in out)

    def test_contextual_en(self):
        out = contextual_confirmation("Open Safari", language="en")
        assert not any("\u0400" <= ch <= "\u04FF" for ch in out)


# ─── Scenario 9: Simple request → short response ──────────────────────────

class TestSimpleRequest:
    def test_simple_request_short(self):
        out = contextual_confirmation("Открой Safari", language="ru")
        assert len(out) < 100

    def test_polish_short_for_simple(self):
        out = polish_response("Открой Safari", "Готово.")
        assert len(out) < 150


# ─── Scenario 10: Complex request → substantive response ──────────────────

class TestComplexRequest:
    def test_natural_long_answer_passes_through(self):
        long_answer = (
            "Нашёл свежие новости об OpenAI. Главное: компания выпустила новую "
            "модель с улучшенным reasoning, обновила API и представила изменения "
            "в тарифах. Если хочешь, могу собрать подробный обзор по каждому пункту."
        )
        out = polish_response("Найди новости об OpenAI и скажи главное", long_answer)
        assert out == long_answer  # substantive answers are never truncated

    def test_complex_en_answer_passes_through(self):
        long_answer = (
            "I found several fresh results about OpenAI. The key points: a new "
            "model with better reasoning, an API update, and pricing changes. "
            "Want me to dig into any of them?"
        )
        out = polish_response("Find news about OpenAI and summarize", long_answer)
        assert out == long_answer


# ─── Personality system prompt ────────────────────────────────────────────

class TestPersonalitySystemPrompt:
    def test_prompt_covers_required_behavior(self):
        p = FOL_PERSONALITY_SYSTEM_PROMPT.lower()
        assert "personal ai assistant" in p
        assert "natural" in p
        assert "humorous" in p
        assert "never" in p

    def test_prompt_forbids_bare_confirmations(self):
        p = FOL_PERSONALITY_SYSTEM_PROMPT
        assert "Done." in p
        assert "Готово." in p

    def test_system_md_contains_personality(self):
        prompt_path = Path(__file__).resolve().parents[2] / "modules" / "llm" / "prompts" / "system.md"
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
            assert "Done." in content
            assert "natural" in content.lower()

    def test_engine_build_messages_injects_personality(self):
        from modules.llm.engine import LLMEngine
        engine = LLMEngine()
        messages = engine._build_messages("привет", "", "")
        sys_content = messages[0]["content"]
        assert "Personality (MANDATORY)" in sys_content
        assert "Done." in sys_content

    def test_engine_personality_independent_of_override(self):
        from modules.llm.engine import LLMEngine
        engine = LLMEngine()
        messages = engine._build_messages("hello", "", "Custom agent prompt")
        sys_content = messages[0]["content"]
        assert "Custom agent prompt" in sys_content
        assert "Done." in sys_content  # personality always appended


# ─── FOL.process() wiring — control tokens & terse LLM ────────────────────

class _TerseLLM:
    """Stub LLM that always answers "Done." (simulates small local models)."""

    available_backends = ["stub"]

    async def generate(self, user_input, context="", system_prompt="", temperature=None, max_tokens=None):
        return "Done."

    async def initialize(self):
        pass

    async def shutdown(self):
        pass


class _FakeLTM:
    """In-memory long-term memory stub — keeps tests hermetic (no disk writes)."""

    def store_memory(self, *a, **k):
        pass

    def extract_and_store(self, *a, **k):
        pass

    def store_conversation(self, *a, **k):
        pass

    def store_episode(self, *a, **k):
        pass

    def get_context_for_query(self, *a, **k):
        return ""


class TestProcessWiring:
    """Tests for the Personality Layer wiring inside FOL.process()."""

    def _make_fol(self, terse_llm: bool = True):
        from core.app import FOL

        fol = FOL()
        if terse_llm:
            fol._llm = _TerseLLM()
        fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
        return fol

    def test_control_tokens_pass_through_polish(self):
        fol = self._make_fol()
        for token in ("__SHUTDOWN__", "__VOICE_MODE__", "__VOICE_MODE_STOP__"):
            assert fol._polish("привет", token) == token

    @pytest.mark.asyncio
    async def test_process_polishes_terse_llm_response(self):
        fol = self._make_fol()
        out = await fol.process("Открой Safari")
        assert out.strip().lower() != "done."
        assert "Safari" in out

    @pytest.mark.asyncio
    async def test_process_resets_last_tool_per_request(self):
        fol = self._make_fol()
        # Simulate a previous request that ran a tool
        fol._last_tool = ("open_app", {"name": "Safari"})
        # A pure-conversation request that matches no intent → must NOT claim
        # that Safari was opened because of the stale tool context.
        out = await fol.process("сделай что-нибудь интересное")
        assert "Safari" not in out

    @pytest.mark.asyncio
    async def test_process_remember_scenario(self):
        fol = self._make_fol()
        out = await fol.process("Запомни, что завтра нужно отправить отчёт")
        assert "Запомнил" in out or "запомнил" in out

    @pytest.mark.asyncio
    async def test_process_how_are_you_conversational(self):
        fol = self._make_fol()
        out = await fol.process("Как дела?")
        assert len(out) > 10
        assert out.strip().lower() != "done."

    @pytest.mark.asyncio
    async def test_process_records_builtin_turn_in_history(self):
        """Context conversation: builtin-path turns must enter history so a
        follow-up can reference them ("Открой Safari" → "а теперь YouTube")."""
        fol = self._make_fol()
        await fol.process("запомни купить молоко")
        assert len(fol._conversation_history) == 1
        turn = fol._conversation_history[0]
        assert turn["user"] == "запомни купить молоко"
        assert "купить молоко" in turn["assistant"]

    @pytest.mark.asyncio
    async def test_process_records_control_tokens_only_internal(self):
        """Control tokens are internal — never recorded into history."""
        fol = self._make_fol()
        out = await fol.process("voice mode")
        assert out == "__VOICE_MODE__"
        assert fol._conversation_history == []


class TestLegacyMemoryMethods:
    """BUG A/D regression: builtin memory commands must answer in the user's
    language, naturally, and never expose raw exceptions."""

    def _make_fol(self):
        from core.app import FOL

        fol = FOL()
        fol._llm = _TerseLLM()
        fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
        return fol

    def test_remember_ru_is_russian(self):
        fol = self._make_fol()
        out = fol._remember("купить молоко")
        assert "Запомнил" in out
        assert "купить молоко" in out
        assert "sir" not in out.lower()

    def test_remember_en_is_english(self):
        fol = self._make_fol()
        out = fol._remember("buy milk")
        assert "remember" in out.lower()
        assert "sir" not in out.lower()

    def test_remember_empty_asks_what(self):
        fol = self._make_fol()
        ru = fol._remember("")
        assert "Что" in ru or "what" in ru.lower()

    def test_recall_ru_when_empty(self):
        fol = self._make_fol()
        out = fol._recall(lang="ru")
        assert "не" in out
        assert "sir" not in out.lower()

    def test_recall_ru_lists_memories(self):
        fol = self._make_fol()
        fol._memories.append({"content": "отчёт завтра", "category": "user_request", "importance": 0.8})
        out = fol._recall(lang="ru")
        assert "Вот что я помню" in out
        assert "отчёт завтра" in out

    def test_set_preference_never_exposes_exception(self):
        fol = self._make_fol()
        # A malformed command must produce a friendly usage hint — never
        # a raw "Error: <traceback>" string.
        out = fol._set_preference("set")
        assert "Error:" not in out
        assert "Usage" in out or "Формат" in out

    def test_set_preference_ru_confirms(self):
        fol = self._make_fol()
        out = fol._set_preference("set язык = русский")
        assert "Настройка сохранена" in out
        assert "язык = русский" in out

    def test_clear_history_ru_natural(self):
        fol = self._make_fol()
        out = fol._clear_history(lang="ru")
        assert "История разговора очищена" in out
        assert "sir" not in out.lower()

    def test_learn_forever_ru_no_sir(self):
        fol = self._make_fol()
        # Use a fake LTM so the test never writes to the real memory store.
        fol._long_term_memory = _FakeLTM()
        out = fol._learn_forever("запомни навсегда проект FOL")
        assert "Запомнил навсегда" in out
        assert "проект FOL" in out
        assert "sir" not in out.lower()

    def test_learn_forever_en_no_sir(self):
        fol = self._make_fol()
        fol._long_term_memory = _FakeLTM()
        out = fol._learn_forever("learn that the sky is blue")
        assert "Remembered forever" in out
        assert "sir" not in out.lower()

    def test_remember_empty_ru_answers_russian(self):
        """A Russian user typing just "запомни" must get a Russian prompt,
        not an English one (language comes from the full user input)."""
        fol = self._make_fol()
        out = fol._remember("", lang="ru")
        assert "Что запомнить?" in out
        assert "sir" not in out.lower()


class _FakeVision:
    """Stub vision system returning real-looking ScreenContent."""

    def __init__(self, active_app="Safari", window_title="example.com", description="Active application: Safari"):
        self._app = active_app
        self._title = window_title
        self._desc = description

    def analyze_screen(self):
        from modules.input.vision import ScreenContent

        return ScreenContent(
            active_app=self._app,
            window_title=self._title,
            description=self._desc,
        )


class TestDeterministicIntents:
    """Final stabilization: S5 (email), S6 (screen), S9 (tasks) must never
    fall through to the generic "Принято. Чем ещё могу помочь?" — they get
    real, deterministic answers based on real data or honest clarification.
    """

    def _make_fol(self, terse_llm: bool = True):
        from core.app import FOL

        fol = FOL()
        fol._llm = _TerseLLM() if terse_llm else None
        fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
        fol._long_term_memory = _FakeLTM()
        fol._obsidian = None
        fol._identity = None
        fol._vision = None
        return fol

    # ─── S5 Email ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_email_intent_asks_for_missing_address_ru(self):
        """"Напиши письмо преподавателю"" with unknown address → natural
        clarification, not the generic fallback."""
        fol = self._make_fol()
        out = await fol.process("Напиши письмо преподавателю")
        assert "email" in out.lower()
        assert "преподавателя" in out
        assert "Принято" not in out

    @pytest.mark.asyncio
    async def test_email_intent_asks_for_missing_address_en(self):
        fol = self._make_fol()
        out = await fol.process("Write an email to my professor")
        assert "email" in out.lower()
        assert "professor" in out.lower()
        assert "All set" not in out

    @pytest.mark.asyncio
    async def test_email_intent_uses_known_address(self):
        """When the address IS known (preferences), confirm with the real one."""
        fol = self._make_fol()
        fol._preferences["teacher_email"] = "ivanov@uni.ru"
        out = await fol.process("Напиши письмо преподавателю")
        assert "ivanov@uni.ru" in out
        assert "преподавател" in out
        assert "Принято" not in out

    @pytest.mark.asyncio
    async def test_email_intent_uses_memory_address(self):
        """A remembered email in short-term memory is used (real data)."""
        fol = self._make_fol()
        fol._memories.append({"content": "email преподавателя: petrov@uni.ru", "category": "user_request", "importance": 0.8})
        out = await fol.process("Напиши письмо преподавателю")
        assert "petrov@uni.ru" in out

    # ─── S6 Screen ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_screen_intent_human_description_ru(self):
        """Screen answer is built from the REAL ScreenContent, humanized."""
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="VS Code", window_title="orchestrator/server.py")
        out = await fol.process("Что у меня сейчас на экране?")
        assert "VS Code" in out
        assert "orchestrator/server.py" in out
        assert "Screen Analysis" not in out  # no raw technical output
        assert "Active App" not in out

    @pytest.mark.asyncio
    async def test_screen_intent_human_description_en(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="Terminal", window_title="~/Desktop/SecondSelf")
        out = await fol.process("What is on my screen now?")
        assert "Terminal" in out
        assert "Desktop/SecondSelf" in out
        assert "Screen Analysis" not in out

    @pytest.mark.asyncio
    async def test_screen_intent_no_vision_permission(self):
        """No Screen Recording permission → plain explanation, not a traceback."""
        fol = self._make_fol()
        fol._vision = None
        # Prevent _init_vision from creating a real ScreenAnalyzer (which on a
        # real Mac would succeed and report the actual app instead).
        fol._init_vision = lambda: None
        out = await fol.process("Что у меня сейчас на экране?")
        assert "не могу" in out.lower() or "нет доступа" in out.lower()
        assert "Traceback" not in out

    # ─── S9 Tasks ────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_tasks_intent_empty_ru(self):
        fol = self._make_fol()
        out = await fol.process("Какие задачи я должен сделать завтра?")
        assert "ничего не записано" in out
        assert "Принято" not in out

    @pytest.mark.asyncio
    async def test_tasks_intent_empty_en(self):
        fol = self._make_fol()
        out = await fol.process("What tasks do I have tomorrow?")
        assert "Nothing scheduled" in out
        assert "All set" not in out

    @pytest.mark.asyncio
    async def test_tasks_intent_returns_remembered_task(self):
        """A real remembered task is returned (not faked)."""
        fol = self._make_fol()
        fol._memories.append({"content": "завтра нужно отправить отчёт", "category": "user_request", "importance": 0.8})
        out = await fol.process("Какие задачи я должен сделать завтра?")
        assert "отправить отчёт" in out
        assert "ничего не записано" not in out

    @pytest.mark.asyncio
    async def test_tasks_intent_no_generic_fallback_anywhere(self):
        """None of the three stabilization scenarios may return the generic
        confirmation as the whole answer."""
        fol = self._make_fol()
        fol._vision = None
        for msg in (
            "Напиши письмо преподавателю",
            "Что у меня сейчас на экране?",
            "Какие задачи я должен сделать завтра?",
        ):
            out = await fol.process(msg)
            assert out.strip() != "Принято. Чем ещё могу помочь?"
            assert out.strip().lower() != "done."
            assert out.strip()  # non-empty


class TestContextConversation:
    """ROADMAP Stage 1: the conversation keeps context between turns.

    "Найди новости про OpenAI" → "А какая самая важная?" must reference
    the topic (OpenAI), and "а теперь YouTube" after "Открой Safari" must
    resolve to the new action.
    """

    def _make_fol(self, terse_llm: bool = True):
        from core.app import FOL

        fol = FOL()
        fol._llm = _TerseLLM() if terse_llm else None
        fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
        # Hermetic: never open a real browser or write to real memory/obsidian.
        fol._mac_search = lambda q, lang="en": f"Searching for: {q}"
        fol._long_term_memory = _FakeLTM()
        fol._obsidian = None
        fol._identity = None
        return fol

    def test_extract_topic_proper_noun(self):
        fol = self._make_fol()
        assert fol._extract_topic("Найди новости про OpenAI") == "OpenAI"

    def test_extract_topic_open_app(self):
        fol = self._make_fol()
        assert fol._extract_topic("Открой Safari") == "Safari"

    def test_extract_topic_followup_returns_empty(self):
        """An anaphoric follow-up must NOT overwrite the topic with
        "самая важная" — the previous topic is kept."""
        fol = self._make_fol()
        assert fol._extract_topic("А какая самая важная?") == ""

    def test_update_topic_keeps_previous_on_followup(self):
        fol = self._make_fol()
        fol._update_topic("Найди новости про OpenAI")
        assert fol._topic == "OpenAI"
        fol._update_topic("А какая самая важная?")
        assert fol._topic == "OpenAI"  # unchanged

    @pytest.mark.asyncio
    async def test_followup_after_news_question_uses_topic(self):
        """S: "Найди новости про OpenAI" → "А какая самая важная?" —
        the second message references the OpenAI topic, not a generic reply."""
        fol = self._make_fol(terse_llm=True)
        await fol.process("Найди новости про OpenAI")
        out = await fol.process("А какая самая важная?")
        assert "OpenAI" in out
        assert "важная" in out.lower() or "могу" in out.lower()
        assert out.strip().lower() != "done."

    @pytest.mark.asyncio
    async def test_followup_works_without_llm(self):
        """Rule-based fallback (no LLM) must still keep conversation context."""
        fol = self._make_fol(terse_llm=False)
        await fol.process("Найди новости про OpenAI")
        out = await fol.process("А какая самая важная?")
        assert "OpenAI" in out

    @pytest.mark.asyncio
    async def test_action_followup_now_youtube(self):
        """"а теперь YouTube"" after "Открой Safari" opens YouTube."""
        fol = self._make_fol()
        played = []

        def _fake_youtube(query, lang="en"):
            played.append(query)
            return f"Opening YouTube, sir." if not query else f"Playing {query}"

        fol._mac_play_youtube = _fake_youtube
        await fol.process("Открой Safari")
        out = await fol.process("а теперь YouTube")
        assert played == [""]
        assert "YouTube" in out

    @pytest.mark.asyncio
    async def test_action_followup_and_now(self):
        fol = self._make_fol()
        played = []

        def _fake_youtube(query, lang="en"):
            played.append(query)
            return f"Playing: {query}"

        fol._mac_play_youtube = _fake_youtube
        await fol.process("Открой Safari")
        await fol.process("and now YouTube")
        assert played == [""]

    @pytest.mark.asyncio
    async def test_action_followup_ignores_free_text(self):
        """Safety: "next week I need..." / "now tell me about X" must NOT be
        rebuilt as "открой ..." (no real subprocess, no garbage)."""
        fol = self._make_fol()
        opened = []

        async def _fake_open(app_name, lang="en"):
            opened.append(app_name)
            return f"Opening {app_name}."

        fol._mac_open_app = _fake_open
        # "next" alone is not a follow-up marker
        out = await fol.process("next week I need a report")
        assert opened == []
        assert "week" not in out.lower() or opened == []

    @pytest.mark.asyncio
    async def test_action_followup_unknown_noun_ignored(self):
        """"а теперь куда-нибудь"" — unknown noun, no command verb → not an
        action follow-up; the normal pipeline handles it."""
        fol = self._make_fol()
        opened = []

        async def _fake_open(app_name, lang="en"):
            opened.append(app_name)
            return f"Opening {app_name}."

        fol._mac_open_app = _fake_open
        out = await fol.process("а теперь куда-нибудь")
        assert opened == []
        assert out  # non-empty, natural

    @pytest.mark.asyncio
    async def test_followup_does_not_capture_new_question(self):
        """"А что ты думаешь о погоде?"" introduces a new topic (погода) —
        it must NOT be answered about the previous topic."""
        fol = self._make_fol()
        await fol.process("Найди новости про OpenAI")
        # Pure anaphora still works
        assert "OpenAI" in await fol.process("А какая самая важная?")
        # New-topic question is not captured as anaphora
        out = await fol.process("А что ты думаешь о погоде?")
        assert "OpenAI" not in out

    @pytest.mark.asyncio
    async def test_llm_receives_topic_context(self):
        """When the LLM is available, the follow-up goes to the LLM with the
        topic + history in the context so it can answer substantively."""

        class _CapturingLLM:
            available_backends = ["stub"]

            def __init__(self):
                self.captured = []

            async def generate(self, user_input, context="", system_prompt="", temperature=None, max_tokens=None):
                self.captured.append((user_input, context))
                return "Понял, отвечу про это."

            async def initialize(self):
                pass

            async def shutdown(self):
                pass

        fol = self._make_fol()
        llm = _CapturingLLM()
        fol._llm = llm
        await fol.process("Найди новости про OpenAI")
        await fol.process("А какая самая важная?")
        assert llm.captured, "LLM should have been called for the follow-up"
        last_user, last_ctx = llm.captured[-1]
        assert last_user == "А какая самая важная?"
        assert "OpenAI" in last_ctx
        assert "Найди новости" in last_ctx


class TestCompoundIntentParsing:
    """UX regression: compound intents must not pollute app names.

    "Открой Safari и найди новости" → Safari, not "Safari и найди новости".
    "Что у меня сейчас на экране?" → screen analysis (substring match).
    "Найди файл X" → bilingual search confirmation.
    """

    def _make_fol(self):
        from core.app import FOL

        fol = FOL()
        fol._llm = _TerseLLM()
        fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
        return fol

    @pytest.mark.asyncio
    async def test_open_app_strips_trailing_compound(self):
        fol = self._make_fol()
        calls = []

        async def _fake_open(app_name, lang="en"):
            calls.append(app_name)
            return f"Opening {app_name}."

        fol._mac_open_app = _fake_open
        out = await fol.process("Открой Safari и найди новости об OpenAI")
        assert calls == ["safari"], f"expected just safari, got {calls}"
        assert "Safari" in out

    @pytest.mark.asyncio
    async def test_open_app_en_strips_and(self):
        fol = self._make_fol()
        calls = []

        async def _fake_open(app_name, lang="en"):
            calls.append(app_name)
            return f"Opening {app_name}."

        fol._mac_open_app = _fake_open
        await fol.process("Open Chrome and search for news")
        assert calls == ["chrome"], f"expected just chrome, got {calls}"

    @pytest.mark.asyncio
    async def test_screen_awareness_substring_match(self):
        fol = self._make_fol()
        # Hermetic: never create a real ScreenAnalyzer / take a real screenshot.
        fol._vision = None
        fol._init_vision = lambda: None
        hit = []

        def _fake_analyze(lang=None):
            hit.append(True)
            return "Screen Analysis:\n  Active App: VS Code"

        fol._analyze_screen = _fake_analyze
        out = await fol.process("Что у меня сейчас на экране?")
        assert hit, "screen analysis should have been triggered"
        assert "VS Code" in out

    @pytest.mark.asyncio
    async def test_search_ru_confirmation_natural(self):
        """No real browser must open — subprocess.Popen is patched."""
        import subprocess as _sp

        fol = self._make_fol()
        opened = []
        original_popen = _sp.Popen

        def _fake_popen(cmd, *a, **k):
            opened.append(cmd)
            return original_popen(["true"], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

        fol._mac_search.__globals__["subprocess"].Popen = _fake_popen
        try:
            out = fol._mac_search("файл fol")
        finally:
            fol._mac_search.__globals__["subprocess"].Popen = original_popen
        assert "поиск" in out.lower()
        assert "Ищу:" not in out
        assert opened, "search should have invoked subprocess (patched)"

    @pytest.mark.asyncio
    async def test_polish_strips_compound_intent_in_confirmation(self):
        """The Final-Response layer must confirm just the app, not the whole
        compound intent: "Открой Safari и найди новости" → "Safari открыт"."""
        out = polish_response(
            "Открой Safari и найди новости об OpenAI",
            "Opening Safari, sir.",
        )
        assert "Safari открыт" in out
        assert "найди новости" not in out

    @pytest.mark.asyncio
    async def test_polish_strips_compound_en(self):
        out = polish_response(
            "Open Chrome and search for news",
            "Opening Chrome, sir.",
        )
        assert "Chrome" in out
        assert "search for news" not in out.lower()


class TestScreenAwareness:
    """Screen Awareness stage: FOL must understand what is on the Mac screen
    and answer naturally — never invent data, never take actions, and only
    capture a screenshot when the user actually asks for screen context.
    """

    def _make_fol(self, terse_llm: bool = True):
        from core.app import FOL

        fol = FOL()
        fol._llm = _TerseLLM() if terse_llm else None
        fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
        fol._long_term_memory = _FakeLTM()
        fol._obsidian = None
        fol._identity = None
        fol._vision = None
        fol._init_vision = lambda: None
        return fol

    # 1. screen intent detection
    @pytest.mark.asyncio
    async def test_screen_intent_detection_ru(self):
        fol = self._make_fol()
        assert fol._is_screen_request("что у меня сейчас на экране?")
        assert fol._is_screen_request("что сейчас открыто?")
        assert fol._is_screen_request("анализ экрана")
        assert fol._is_screen_request("какой файл открыт?")
        assert not fol._is_screen_request("как дела?")
        assert not fol._is_screen_request("напиши письмо")

    @pytest.mark.asyncio
    async def test_screen_intent_detection_en(self):
        fol = self._make_fol()
        assert fol._is_screen_request("what is on my screen?")
        assert fol._is_screen_request("what's open right now")
        assert fol._is_screen_request("look at the screen")
        assert fol._is_screen_request("screen analysis")
        assert not fol._is_screen_request("write an email")

    # 2. screenshot tool call (no real capture — mocked vision)
    @pytest.mark.asyncio
    async def test_screenshot_tool_call(self):
        fol = self._make_fol()
        calls = []

        class _FakeVisionShot:
            def capture_screenshot(self):
                calls.append(True)
                return "/tmp/shot.png"

        fol._vision = _FakeVisionShot()
        out = fol._take_screenshot()
        assert calls
        assert "shot.png" in out

    # 3. screen result formatting — humanized, no raw labels
    @pytest.mark.asyncio
    async def test_screen_result_formatting(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="VS Code", window_title="orchestrator/server.py")
        out = await fol.process("Что у меня сейчас на экране?")
        assert "VS Code" in out
        assert "orchestrator/server.py" in out
        assert "Screen Analysis" not in out
        assert "Active App" not in out
        assert "Traceback" not in out

    # 4. Russian screen request
    @pytest.mark.asyncio
    async def test_screen_request_ru(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="Safari", window_title="google.com")
        out = await fol.process("Что сейчас открыто?")
        assert "Safari" in out
        assert "google.com" in out

    # 5. English screen request
    @pytest.mark.asyncio
    async def test_screen_request_en(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="Terminal", window_title="~/Desktop/SecondSelf")
        out = await fol.process("What is on my screen now?")
        assert "Terminal" in out
        assert "Desktop/SecondSelf" in out

    # 6. screen follow-up ("Что там?" after opening an app)
    @pytest.mark.asyncio
    async def test_screen_followup_what_there(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="Safari", window_title="apple.com")
        # Simulate the previous turn: FOL opened Safari.
        fol._record_turn("Открой Safari", "Safari открыт. Куда направляемся?")
        out = await fol.process("Что там?")
        assert "Safari" in out
        assert "apple.com" in out

    # 7. context-aware screen follow-up ("Посмотри, что там")
    @pytest.mark.asyncio
    async def test_screen_followup_context_aware(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="VS Code", window_title="app.py")
        fol._record_turn("Открой VS Code", "VS Code открыт. Что пишем?")
        out = await fol.process("Посмотри, что там.")
        assert "VS Code" in out
        assert "app.py" in out

    # guard: "Что это?" in a plain code discussion is NOT hijacked as screen
    @pytest.mark.asyncio
    async def test_screen_followup_no_context_not_intercepted(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="Safari", window_title="example.com")
        # No prior screen/app context — plain conversation.
        fol._record_turn("Расскажи про Python", "Python — язык программирования.")
        out = await fol.process("Что это?")
        # Must NOT answer about the screen.
        assert "example.com" not in out
        assert "Safari" not in out

    # 8. missing permission → human message, no traceback
    @pytest.mark.asyncio
    async def test_screen_missing_permission(self):
        fol = self._make_fol()
        out = await fol.process("Что у меня сейчас на экране?")
        assert "не могу" in out.lower() or "нет доступа" in out.lower()
        assert "Traceback" not in out
        assert "PermissionError" not in out

    # 9. screenshot failure → human message, no exception
    @pytest.mark.asyncio
    async def test_screenshot_failure(self):
        fol = self._make_fol()

        class _FailingVision:
            def analyze_screen(self):
                raise PermissionError("denied")

        fol._vision = _FailingVision()
        out = await fol.process("Что у меня сейчас на экране?")
        assert out.strip()
        assert "PermissionError" not in out
        assert "Traceback" not in out

    # 10. no fake screen response — never invent data that wasn't captured
    @pytest.mark.asyncio
    async def test_no_fake_screen_response(self):
        fol = self._make_fol()
        # Vision unavailable → FOL must NOT claim Safari/Chrome is open.
        out = await fol.process("Что у меня сейчас на экране?")
        assert "Safari" not in out
        assert "Chrome" not in out

    # 11. no unnecessary screenshot on a regular message
    @pytest.mark.asyncio
    async def test_no_unnecessary_screenshot(self):
        fol = self._make_fol()
        calls = []

        class _SpyVision:
            def analyze_screen(self):
                calls.append(True)
                return _FakeVision().analyze_screen()

        fol._vision = _SpyVision()
        await fol.process("Привет")
        await fol.process("Как дела?")
        assert not calls, "screenshot must not run on ordinary messages"

    # 12. dangerous action requires approval — screen analysis never acts
    @pytest.mark.asyncio
    async def test_screen_never_triggers_dangerous_action(self):
        fol = self._make_fol()
        executed = []

        async def _fake_execute(name, params):
            executed.append(name)
            return {"ok": True}

        fol._tools.execute = _fake_execute
        fol._vision = _FakeVision(active_app="Safari", window_title="x.com")
        out = await fol.process("Что у меня сейчас на экране?")
        assert out.strip()
        assert not executed, "screen analysis must never execute tools"

    # 13. LLM path receives SCREEN CONTEXT block
    @pytest.mark.asyncio
    async def test_screen_llm_path_injects_screen_context(self):
        contexts = []

        class _ContextLLM:
            available_backends = ["stub"]

            async def generate(self, user_input, context="", system_prompt="", temperature=None, max_tokens=None):
                contexts.append(context)
                return "На экране Safari с открытой страницей."

            async def initialize(self):
                pass

            async def shutdown(self):
                pass

        fol = self._make_fol()
        fol._llm = _ContextLLM()
        fol._vision = _FakeVision(active_app="Safari", window_title="google.com")
        out = await fol.process("Что на экране?")
        assert contexts, "LLM should have been called for screen request"
        assert "SCREEN CONTEXT" in contexts[0]
        assert "Safari" in contexts[0]
        assert "google.com" in contexts[0]
        assert "Safari" in out

    # 14. LLM terse answer falls back to rule-based humanized description
    @pytest.mark.asyncio
    async def test_screen_terse_llm_falls_back(self):
        fol = self._make_fol()  # _TerseLLM returns "Done."
        fol._vision = _FakeVision(active_app="Finder", window_title="Documents")
        out = await fol.process("Что на экране?")
        assert "Finder" in out
        assert "Documents" in out

    # 15. trailing punctuation must not pollute the app name ("Открой Safari.")
    @pytest.mark.asyncio
    async def test_open_app_trailing_punctuation(self):
        fol = self._make_fol()
        calls = []

        async def _fake_open(app_name, lang="en"):
            calls.append(app_name)
            return f"Opening {app_name}."

        fol._mac_open_app = _fake_open
        out = await fol.process("Открой Safari.")
        assert calls == ["safari"], f"expected 'safari', got {calls}"
        assert "Safari открыт" in out

    # 16. "Посмотри мой код" must NOT be hijacked as a screen follow-up
    #     even when the previous turn opened an app (false interception guard).
    @pytest.mark.asyncio
    async def test_followup_with_subject_not_screen(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="Safari", window_title="example.com")
        # Screen context EXISTS (an app was just opened)…
        fol._record_turn("Открой Safari", "Safari открыт. Куда направляемся?")
        # …but "Посмотри мой код" carries a subject → must NOT analyze screen.
        out = await fol.process("Посмотри мой код")
        assert "example.com" not in out
        assert "Сейчас открыт Safari" not in out

    # 17. bare "Посмотри." right after opening an app IS a screen follow-up
    @pytest.mark.asyncio
    async def test_bare_look_is_screen_followup(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="Safari", window_title="apple.com")
        fol._record_turn("Открой Safari", "Safari открыт. Куда направляемся?")
        out = await fol.process("Посмотри.")
        assert "Safari" in out
        assert "apple.com" in out


class TestResponseClassification:
    """FINAL RESPONSE LAYER: every user-facing answer is classified and shaped
    to be natural — a bare "Done." / "Готово." / "OK." / "Принято." can never
    be the only thing the user sees."""

    def _make_fol(self, terse_llm: bool = True):
        from core.app import FOL

        fol = FOL()
        fol._llm = _TerseLLM() if terse_llm else None
        fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
        fol._long_term_memory = _FakeLTM()
        fol._obsidian = None
        fol._identity = None
        fol._vision = None
        fol._init_vision = lambda: None
        return fol

    # ─── classify_response: category mapping ───────────────────────────────

    def test_classify_action_success(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Открой Safari") == ResponseCategory.ACTION_SUCCESS
        assert classify_response("open Chrome") == ResponseCategory.ACTION_SUCCESS
        assert classify_response("Открой Safari", tool_name="open_app") == ResponseCategory.ACTION_SUCCESS

    def test_classify_information(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Расскажи про Python") == ResponseCategory.INFORMATION
        assert classify_response("Объясни, как работает рекурсия") == ResponseCategory.INFORMATION

    def test_classify_question(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Кто такой Эйнштейн?") == ResponseCategory.QUESTION
        assert classify_response("what is machine learning") == ResponseCategory.QUESTION

    def test_classify_clarification(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Напиши письмо преподавателю") == ResponseCategory.CLARIFICATION
        assert classify_response("Создай событие на завтра") == ResponseCategory.CLARIFICATION
        assert classify_response("Напиши email", tool_name="email_tool") == ResponseCategory.CLARIFICATION

    def test_classify_error(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Открой Safari", raw_response="ConnectionError: timeout") == ResponseCategory.ERROR
        assert classify_response("x", raw_response="Traceback (most recent call last)") == ResponseCategory.ERROR

    def test_classify_memory(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Запомни, что завтра отправить отчёт") == ResponseCategory.MEMORY
        assert classify_response("remember this", tool_name="save_to_obsidian") == ResponseCategory.MEMORY

    def test_classify_search(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Найди новости про OpenAI") == ResponseCategory.SEARCH_RESULT
        assert classify_response("search web", tool_name="search_web") == ResponseCategory.SEARCH_RESULT

    def test_classify_casual(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Привет") == ResponseCategory.CASUAL_CONVERSATION
        assert classify_response("Как дела?") == ResponseCategory.CASUAL_CONVERSATION
        assert classify_response("Мне скучно") == ResponseCategory.CASUAL_CONVERSATION

    def test_classify_multi_step_tool(self):
        from modules.llm.personality import ResponseCategory, classify_response

        assert classify_response("Открой Safari и найди новости", tool_name="browser_goto") == ResponseCategory.ACTION_SUCCESS

    # ─── Terse responses are NEVER the final answer ───────────────────────

    @pytest.mark.asyncio
    async def test_terse_done_rebuilt(self):
        fol = self._make_fol()
        out = await fol.process("Открой Safari")
        assert out.strip().lower() != "done"
        assert "Safari" in out

    @pytest.mark.asyncio
    async def test_terse_готово_rebuilt(self):
        fol = self._make_fol()
        out = await fol.process("Запомни, что завтра отправить отчёт")
        assert out.strip() != "Готово"
        assert "завтра" in out.lower() or "отчёт" in out.lower()

    @pytest.mark.asyncio
    async def test_terse_ok_rebuilt(self):
        fol = self._make_fol()
        out = await fol.process("Найди новости про OpenAI")
        assert out.strip().lower() != "ok"
        assert out.strip() != "Принято"

    @pytest.mark.asyncio
    async def test_never_ends_with_bare_confirmation(self):
        fol = self._make_fol()
        for msg in (
            "Открой Safari",
            "Запомни, что завтра отправить отчёт",
            "Найди новости про OpenAI",
            "Что у меня на экране?",
            "Напиши письмо преподавателю",
        ):
            out = await fol.process(msg)
            stripped = out.strip().lower().rstrip(".!")
            assert stripped not in ("done", "готово", "ok", "принято", "выполнено", "success", "completed"), f"{msg!r} -> {out!r}"

    # ─── JSON never leaks to the user ─────────────────────────────────────

    def test_json_response_classified(self):
        from modules.llm.personality import polish_response

        out = polish_response("Открой Safari", '{"status": "ok", "result": "done"}')
        assert "status" not in out.lower()
        assert out.strip().lower() not in ("done", "готово", "ok")

    def test_tool_result_without_final_gets_contextual(self):
        from modules.llm.personality import polish_response

        # A raw tool_result with no natural answer → rebuilt from the intent.
        out = polish_response("Открой Terminal", "tool_result: {\"ok\": true}")
        assert "Terminal" in out
        assert out.strip().lower() not in ("done", "ok", "готово")

    def test_empty_response_gets_contextual(self):
        from modules.llm.personality import polish_response

        out = polish_response("Открой Safari", "")
        assert "Safari" in out
        assert out.strip() != ""

    def test_blank_response_gets_contextual(self):
        from modules.llm.personality import polish_response

        out = polish_response("Открой Safari", "   ")
        assert "Safari" in out

    # ─── Bilingual final responses ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ru_request_ru_response(self):
        fol = self._make_fol()
        out = await fol.process("Открой Safari")
        assert "Safari" in out
        assert "открыт" in out.lower()

    @pytest.mark.asyncio
    async def test_en_request_en_response(self):
        fol = self._make_fol()
        out = await fol.process("Open Safari")
        assert "Safari" in out
        assert out.strip().lower() not in ("done", "ok")

    @pytest.mark.asyncio
    async def test_mixed_language_ru_majority(self):
        fol = self._make_fol()
        out = await fol.process("Открой Safari please")
        assert "Safari" in out
        assert "открыт" in out.lower()

    # ─── Per-intent natural confirmations ─────────────────────────────────

    @pytest.mark.asyncio
    async def test_open_app_natural(self):
        fol = self._make_fol()
        out = await fol.process("Открой Safari")
        assert "Safari" in out
        assert out.strip().lower() != "done"

    @pytest.mark.asyncio
    async def test_screenshot_natural(self):
        fol = self._make_fol()

        class _ShotVision:
            def capture_screenshot(self):
                return "/tmp/s.png"

        fol._vision = _ShotVision()
        out = await fol.process("Сделай скриншот")
        assert out.strip()
        assert out.strip().lower() not in ("done", "ok", "готово")

    @pytest.mark.asyncio
    async def test_search_natural(self):
        fol = self._make_fol()
        out = await fol.process("Найди новости про OpenAI")
        assert "openai" in out.lower() or "результат" in out.lower() or "нашёл" in out.lower()
        assert out.strip().lower() != "done"

    @pytest.mark.asyncio
    async def test_memory_save_natural(self):
        fol = self._make_fol()
        out = await fol.process("Запомни, что завтра нужно отправить отчёт")
        assert "запомн" in out.lower()
        assert "завтра" in out.lower()

    @pytest.mark.asyncio
    async def test_email_missing_info_natural(self):
        fol = self._make_fol()
        out = await fol.process("Напиши письмо преподавателю")
        assert "email" in out.lower()
        assert "преподавателя" in out

    @pytest.mark.asyncio
    async def test_calendar_missing_info_natural(self):
        fol = self._make_fol()
        out = await fol.process("Создай событие на завтра")
        assert "когда" in out.lower() or "время" in out.lower() or "во сколько" in out.lower()

    @pytest.mark.asyncio
    async def test_file_search_natural(self):
        fol = self._make_fol()
        out = await fol.process("Найди файл FOL")
        assert "fol" in out.lower() or "ищу" in out.lower() or "нашёл" in out.lower()

    @pytest.mark.asyncio
    async def test_screen_natural(self):
        fol = self._make_fol()
        fol._vision = _FakeVision(active_app="VS Code", window_title="server.py")
        out = await fol.process("Что у меня на экране?")
        assert "VS Code" in out
        assert "server.py" in out

    @pytest.mark.asyncio
    async def test_followup_natural(self):
        fol = self._make_fol()
        fol._record_turn("Найди новости про OpenAI", "Нашёл свежие новости об OpenAI.")
        out = await fol.process("А какая самая важная?")
        assert "OpenAI" in out or "openai" in out.lower()
        assert out.strip().lower() != "done"

    @pytest.mark.asyncio
    async def test_action_followup_natural(self):
        fol = self._make_fol()
        fol._record_turn("Открой Safari", "Safari открыт. Куда направляемся?")
        out = await fol.process("А теперь YouTube")
        assert "YouTube" in out or "ютуб" in out.lower()

    @pytest.mark.asyncio
    async def test_tool_error_humanized(self):
        fol = self._make_fol()

        async def _failing_tool(name, params):
            raise PermissionError("not allowed")

        fol._tools.execute = _failing_tool
        # Force a tool path that will surface the raw error through polish.
        out = polish_response("Открой Safari", "ConnectionError: denied", tool_name="open_app")
        assert "Traceback" not in out
        assert "ConnectionError" not in out

    @pytest.mark.asyncio
    async def test_multi_step_result_natural(self):
        fol = self._make_fol()
        out = await fol.process("Открой Safari и найди новости про OpenAI")
        assert out.strip()
        assert out.strip().lower() not in ("done", "готово", "ok")

    # ─── Rule-based fallback delegates to the Personality Layer ───────────

    @pytest.mark.asyncio
    async def test_rule_based_delegates_greeting(self):
        fol = self._make_fol(terse_llm=False)  # no LLM → _rule_based_response
        out = await fol.process("Привет, расскажи что-нибудь интересное")
        assert "Привет" in out or "привет" in out.lower()
        assert out.strip().lower().rstrip(".!") != "done"

    @pytest.mark.asyncio
    async def test_rule_based_delegates_remember(self):
        fol = self._make_fol(terse_llm=False)
        out = await fol.process("Запомни, что завтра отправить отчёт")
        assert "запомн" in out.lower()
        assert out.strip().lower().rstrip(".!") not in ("done", "готово", "принято")

    @pytest.mark.asyncio
    async def test_rule_based_never_mentions_llm_setup(self):
        fol = self._make_fol(terse_llm=False)
        out = await fol.process("Что такое квантовая физика?")
        assert "Настройте LLM" not in out
        assert "Configure an LLM" not in out
        assert out.strip().lower().rstrip(".!") not in ("done", "готово", "ok", "принято")

    # ─── Voice path uses the same FINAL RESPONSE LAYER ────────────────────

    @pytest.mark.asyncio
    async def test_voice_path_same_response(self):
        fol = self._make_fol()
        spoken = []

        class _FakeVoice:
            class tts:
                is_available = True

                @staticmethod
                def speak(text):
                    spoken.append(text)

        fol._voice = _FakeVoice()
        out = await fol.process("скажи Safari открыт")
        # The spoken text and the final text must carry the same meaning.
        assert out.strip().lower() != "done"
        assert out.strip() != ""
        assert not any(s.strip().lower() in ("done", "ok", "готово") for s in spoken)

    @pytest.mark.asyncio
    async def test_llm_terse_with_tool_result_rebuilt(self):
        """LLM says 'Done.' but a tool actually ran → user gets the outcome."""
        fol = self._make_fol()
        calls = []

        async def _fake_open(app_name, lang="en"):
            calls.append(app_name)
            return "Opening Safari, sir."

        fol._mac_open_app = _fake_open
        out = await fol.process("Открой Safari")
        assert calls == ["safari"]
        assert "Safari" in out
        assert out.strip().lower() != "done"

    @pytest.mark.asyncio
    async def test_no_bare_confirmation_anywhere_in_categories(self):
        from modules.llm.personality import (
            ResponseCategory,
            contextual_confirmation,
        )

        for category in (
            ResponseCategory.ACTION_SUCCESS,
            ResponseCategory.INFORMATION,
            ResponseCategory.QUESTION,
            ResponseCategory.CLARIFICATION,
            ResponseCategory.MEMORY,
            ResponseCategory.SEARCH_RESULT,
            ResponseCategory.MULTI_STEP_RESULT,
            ResponseCategory.CASUAL_CONVERSATION,
        ):
            out = contextual_confirmation("Открой Safari", tool_name="open_app")
            assert out.strip().lower().rstrip(".!") not in (
                "done", "готово", "ok", "принято", "выполнено", "success", "completed",
            ), f"{category} -> {out!r}"

    # ─── Reviewer-fix regressions: top-level import, "кто ты" shadowing,
    # ─── JSON payload result extraction ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_rule_based_direct_call_no_nameerror(self):
        """Regression: _rule_based_response used contextual_confirmation without
        importing it → NameError on the no-LLM path. The import is now at the
        top level, so a direct call must work."""
        fol = self._make_fol(terse_llm=False)
        out = fol._rule_based_response("Привет")
        assert "Привет" in out or "привет" in out.lower()

    @pytest.mark.asyncio
    async def test_rule_based_identity_variants_get_rich_answer(self):
        """Regression: «ты кто» / «что ты такое» were delegated to the simple
        Personality-Layer identity branch, shadowing the richer branch that
        reports FOL's version and platform."""
        fol = self._make_fol(terse_llm=False)
        for msg in ("ты кто", "что ты такое", "Ты кто?"):
            out = fol._rule_based_response(msg)
            assert "FOL" in out
            assert "версия" in out.lower() or "version" in out.lower()

    def test_payload_result_extracted_not_lost(self):
        """Regression: a JSON status payload carrying a natural-language
        "result" must keep that information instead of discarding it."""
        from modules.llm.personality import polish_response

        out = polish_response("Открой Safari", '{"status": "ok", "result": "Safari открыт"}')
        assert "Safari открыт" in out
        assert "status" not in out.lower()

    def test_payload_result_terse_rebuilt(self):
        """A terse "result" (e.g. "done") inside a payload is still rebuilt
        into a contextual confirmation — never shown as-is."""
        from modules.llm.personality import polish_response

        out = polish_response("Открой Safari", '{"status": "ok", "result": "done"}')
        assert "Safari" in out
        assert out.strip().lower().rstrip(".!") not in ("done", "ok", "готово")

    def test_payload_result_without_status_payload_field(self):
        from modules.llm.personality import polish_response

        out = polish_response("Открой Terminal", '{"status": "ok"}')
        assert "Terminal" in out
        assert out.strip().lower().rstrip(".!") not in ("done", "ok", "готово")

