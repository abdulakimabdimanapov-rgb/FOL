"""FINAL RESPONSE LAYER tests — the spec's 30+ scenario matrix.

Contract under test (spec section 1-17 of the audit task):

  - A bare "Done." / "Готово." / "OK." / "Принято." / "Выполнено." can NEVER
    be the user's final answer.
  - Tool-call JSON, tool names, tracebacks and internal status never reach
    the user.
  - The answer follows the user's language (RU/EN/mixed) and describes the
    ACTUAL outcome.
  - No constant "Sir"/"сэр" honorific.
  - The voice path uses the SAME final-response layer (FOL.process()).
"""

from __future__ import annotations

import pytest

from modules.llm.personality import (
    contextual_confirmation,
    humanize_error,
    is_terse_response,
    polish_response,
    strip_tool_call_json,
)


class _TerseLLM:
    """Stub LLM that always answers "Done." (small local models behave this way)."""

    available_backends = ["stub"]

    async def generate(self, user_input, context="", system_prompt="", temperature=None, max_tokens=None):
        return "Done."

    async def initialize(self):
        pass

    async def shutdown(self):
        pass


class _FakeLTM:
    """Hermetic long-term memory stub (no disk writes)."""

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

    def search_memories(self, *a, **k):
        return []

    def get_recent_memories(self, *a, **k):
        return []

    @property
    def stats(self):
        return {"memories": 0, "conversations": 0, "knowledge": 0, "episodes": 0}

    def clear_all(self):
        pass


def _make_fol(terse_llm: bool = True):
    """Hermetic FOL instance — no real tools, memory, obsidian or network."""
    from core.app import FOL

    fol = FOL()
    fol._llm = _TerseLLM() if terse_llm else None
    fol._tools = type("T", (), {"execute": None, "list_all": lambda self: []})()
    fol._long_term_memory = _FakeLTM()
    fol._obsidian = None
    fol._identity = None
    fol._vision = None
    return fol


# ─── The forbidden final answers (spec: never bare Done/Готово/OK) ─────────

FORBIDDEN_FINALS = ("done", "готово", "ok", "принято", "выполнено", "сделано",
                    "success", "completed", "task completed", "yes", "успешно")


def _assert_natural(text: str, *, forbid: str | None = None):
    """Assert the answer is non-empty, natural and never a bare confirmation."""
    assert text, "final answer must be non-empty"
    stripped = text.strip().rstrip(".!").strip().lower()
    assert stripped not in FORBIDDEN_FINALS, f"bare confirmation leaked: {text!r}"
    if forbid:
        assert forbid.lower() not in text.lower(), f"forbidden content leaked: {text!r}"
    assert "traceback" not in text.lower()
    assert "{" not in text.replace("«", "").replace("»", ""), f"JSON leaked: {text!r}"


# ─── Scenario: open_app ─────────────────────────────────────────────────────

class TestOpenApp:
    def test_open_app_done_rebuilt_ru(self):
        out = polish_response("Открой Safari", "Done.")
        _assert_natural(out)
        assert "Safari" in out
        assert "открыт" in out.lower() or "открыл" in out.lower()

    def test_open_app_готово_rebuilt(self):
        out = polish_response("Открой Safari", "Готово.")
        _assert_natural(out)
        assert "Safari" in out

    def test_open_app_ok_rebuilt(self):
        out = polish_response("Открой Safari", "OK")
        _assert_natural(out)
        assert "Safari" in out

    def test_open_app_en(self):
        out = polish_response("open Terminal", "Done.")
        _assert_natural(out)
        assert "Terminal" in out

    def test_open_app_plain_confirmation_no_forced_question(self):
        # Spec 6: a complete command is confirmed plainly — no forced question.
        out = contextual_confirmation("Открой Terminal", language="ru")
        assert "Terminal открыт" in out
        assert "Что будем делать" not in out and "Куда направляемся" not in out

    def test_open_app_no_sir(self):
        out = contextual_confirmation("Открой Safari", language="ru")
        assert "сэр" not in out.lower() and "sir" not in out.lower()


# ─── Scenario: project open ─────────────────────────────────────────────────

class TestOpenProject:
    def test_open_project_ru(self):
        out = contextual_confirmation("Открой проект FOL", language="ru")
        assert "FOL" in out
        assert "открыл" in out.lower()

    def test_open_project_en(self):
        out = contextual_confirmation("open the project FOL", language="en")
        assert "FOL" in out


# ─── Scenario: screenshot ───────────────────────────────────────────────────

class TestScreenshot:
    def test_screenshot_done_rebuilt(self):
        out = polish_response("Сделай скриншот", "Done.")
        _assert_natural(out)
        assert "скриншот" in out.lower() or "снимок" in out.lower()


# ─── Scenario: search / web research ───────────────────────────────────────

class TestSearch:
    def test_search_done_rebuilt_ru(self):
        out = polish_response("Найди новости про OpenAI", "Done.")
        _assert_natural(out)
        assert "OpenAI" in out or "результат" in out.lower() or "новост" in out.lower()

    def test_search_en(self):
        out = polish_response("search for AI papers", "Done.")
        _assert_natural(out)
        assert out.isascii(), "EN request must get an EN answer"

    def test_search_result_text_preserved(self):
        out = polish_response("Найди новости про OpenAI", "Нашёл свежие новости об OpenAI.")
        _assert_natural(out)
        assert "OpenAI" in out


# ─── Scenario: memory save / recall ─────────────────────────────────────────

class TestMemory:
    def test_memory_save_confirmation(self):
        out = polish_response("Запомни, что завтра отправить отчёт", "Готово.")
        _assert_natural(out)
        assert "Запомнил" in out
        assert "отчёт" in out.lower() or "отчет" in out.lower()

    def test_memory_save_en(self):
        out = polish_response("remember to send the report tomorrow", "Done.")
        _assert_natural(out)
        assert "report" in out.lower() or "remember" in out.lower()

    @pytest.mark.asyncio
    async def test_process_remember_natural(self):
        fol = _make_fol()
        out = await fol.process("запомни что завтра отправить отчёт")
        _assert_natural(out)
        assert "Запомнил" in out
        assert "отчёт" in out.lower()

    @pytest.mark.asyncio
    async def test_tasks_tomorrow_empty(self):
        fol = _make_fol()
        out = await fol.process("Что мне нужно сделать завтра?")
        _assert_natural(out)
        assert "ничего не записано" in out.lower() or "nothing" in out.lower()

    @pytest.mark.asyncio
    async def test_tasks_tomorrow_returns_real_memory(self):
        fol = _make_fol()
        fol._memories.append({"content": "завтра отправить отчёт", "category": "user_request"})
        out = await fol.process("Что мне нужно сделать завтра?")
        _assert_natural(out)
        assert "отчёт" in out.lower()

    @pytest.mark.asyncio
    async def test_remember_with_comma_persists(self):
        """E2E gap: «Запомни, что завтра отправить отчёт» must STORE the
        reminder (not just confirm) so a later recall finds it."""
        fol = _make_fol()
        out = await fol.process("запомни, что завтра отправить отчёт")
        _assert_natural(out)
        assert "Запомнил" in out
        assert fol._memories, "the reminder must actually be stored"
        recall = await fol.process("Что мне нужно сделать завтра?")
        _assert_natural(recall)
        assert "отчёт" in recall.lower()

    @pytest.mark.asyncio
    async def test_remember_that_en_persists(self):
        fol = _make_fol()
        out = await fol.process("remember that I need to send the report tomorrow")
        _assert_natural(out)
        assert fol._memories, "the EN reminder must actually be stored"



# ─── Scenario: email / calendar (missing info → clarification) ──────────────

class TestClarification:
    def test_email_asks_for_address(self):
        out = polish_response("Напиши письмо преподавателю", "Готово.",
                              tool_name="email_tool")
        _assert_natural(out)
        assert "email" in out.lower() or "почт" in out.lower() or "напиши" in out.lower()

    def test_email_deterministic_ru(self):
        fol = _make_fol()
        out = fol._email_response("напиши письмо преподавателю")
        _assert_natural(out)
        assert "email" in out.lower() or "почт" in out.lower()

    def test_calendar_asks_for_time(self):
        out = contextual_confirmation("создай событие на завтра", language="ru")
        assert "во сколько" in out.lower()


# ─── Scenario: file search ──────────────────────────────────────────────────

class TestFileSearch:
    def test_read_file_done_rebuilt(self):
        out = polish_response("прочитай файл config.py", "Done.",
                              tool_name="read_file", tool_args={"path": "config.py"})
        _assert_natural(out)
        assert "файл" in out.lower() or "прочитал" in out.lower() or "config" in out.lower()

    def test_search_files_en(self):
        out = polish_response("find files in the project", "Done.",
                              tool_name="search_files")
        _assert_natural(out)
        assert out.isascii()


# ─── Scenario: screen awareness ─────────────────────────────────────────────

class _FakeVision:
    def __init__(self, app="VS Code", title="orchestrator/server.py"):
        self._app = app
        self._title = title

    def analyze_screen(self):
        from modules.input.vision import ScreenContent

        return ScreenContent(active_app=self._app, window_title=self._title, description="")

    def capture_screenshot(self):
        return "/tmp/test_shot.png"


class TestScreenAwareness:
    @pytest.mark.asyncio
    async def test_screen_request_ru(self):
        fol = _make_fol()
        fol._vision = _FakeVision()
        out = await fol.process("Что у меня на экране?")
        _assert_natural(out)
        assert "VS Code" in out
        assert "server.py" in out

    @pytest.mark.asyncio
    async def test_screen_request_en(self):
        fol = _make_fol()
        fol._vision = _FakeVision(app="Safari", title="apple.com")
        out = await fol.process("What is on my screen?")
        _assert_natural(out)
        assert "Safari" in out and "apple.com" in out

    def test_screen_humanized_no_raw_labels(self):
        fol = _make_fol()
        fol._vision = _FakeVision()
        out = fol._analyze_screen("ru")
        assert "Active application" not in out
        assert "ScreenContent" not in out


# ─── Scenario: follow-up (context conversation) ─────────────────────────────

class TestContextFollowup:
    @pytest.mark.asyncio
    async def test_followup_references_topic(self):
        fol = _make_fol()
        fol._record_turn("Найди новости про OpenAI", "Нашёл свежие новости об OpenAI.")
        out = await fol.process("А какая самая важная?")
        _assert_natural(out)
        assert "OpenAI" in out

    @pytest.mark.asyncio
    async def test_action_followup_youtube(self):
        fol = _make_fol()
        opened = []

        async def _fake_open(app_name, lang="en"):
            opened.append(app_name)
            return "YouTube открыт."

        fol._mac_open_app = _fake_open
        await fol.process("Открой Safari")
        out = await fol.process("А теперь YouTube")
        _assert_natural(out)
        assert "youtube" in opened or "YouTube" in opened


# ─── Scenario: bilingual / mixed language ───────────────────────────────────

class TestBilingual:
    def test_ru_request_ru_answer(self):
        out = polish_response("Открой Safari", "Done.")
        assert "сэр" not in out.lower() and "sir" not in out.lower()
        assert any(ord(c) > 0x0400 for c in out), "RU request must get RU answer"

    def test_en_request_en_answer(self):
        out = polish_response("open Safari", "Done.")
        assert out.isascii()

    def test_mixed_request_ru_dominant(self):
        # Russian command + English noun → Russian answer (dominant language).
        out = polish_response("открой Safari и найди новости про OpenAI", "Done.")
        assert any(ord(c) > 0x0400 for c in out), "mixed RU-dominant must answer in RU"

    def test_mixed_request_follows_dominant_language(self):
        # "open Safari и найди новости" is Russian-dominant (Cyrillic ratio
        # > 0.4) → the answer must be Russian, not English.
        out = polish_response("open Safari и найди новости", "Done.")
        assert any(ord(c) > 0x0400 for c in out), "RU-dominant input must get a RU answer"

    def test_no_constant_sir_in_any_language(self):
        for text, lang in (("Открой Safari", "ru"), ("open Safari", "en"),
                           ("Привет", "ru"), ("hello", "en")):
            out = contextual_confirmation(text, language=lang)
            assert "sir" not in out.lower() and "сэр" not in out.lower(), out


# ─── Scenario: tool error → humanized, never traceback ──────────────────────

class TestToolError:
    def test_traceback_humanized(self):
        out = polish_response("Открой Safari", "Traceback (most recent call last):\n  File \"x.py\", line 1\nConnectionError: denied")
        _assert_natural(out)
        assert "Traceback" not in out and "ConnectionError" not in out

    def test_oauth_error_humanized(self):
        out = polish_response("Открой Safari", "OAuthException: access denied")
        _assert_natural(out)
        assert "авторизуйте" in out.lower() or "authorize" in out.lower()

    def test_humanize_error_idempotent(self):
        msg = "Что-то пошло не так. Попробуйте ещё раз."
        assert humanize_error(msg, "ru") == msg


# ─── Scenario: missing information ──────────────────────────────────────────

class TestMissingInformation:
    def test_calendar_needs_details(self):
        out = contextual_confirmation("создай событие на завтра", language="ru")
        assert "?" in out

    def test_email_needs_address(self):
        fol = _make_fol()
        out = fol._email_response("напиши письмо преподавателю")
        assert "?" in out


# ─── Scenario: multi-step result ────────────────────────────────────────────

class TestMultiStep:
    def test_multi_step_not_terse(self):
        out = polish_response(
            "Открой Safari и найди новости про OpenAI",
            "Done.",
            tool_name="browser_search",
            tool_args={"query": "OpenAI news"},
        )
        _assert_natural(out)

    def test_compound_intent_confirms_first_action(self):
        out = polish_response("Открой Safari и найди новости про OpenAI", "Готово.")
        _assert_natural(out)
        assert "Safari" in out


# ─── Scenario: terse / JSON / empty LLM responses ───────────────────────────

class TestTerseLLMResponses:
    @pytest.mark.parametrize("terse", ["Done", "Done.", "done!", "Готово", "Готово.",
                                       "OK", "ok", "Принято", "Выполнено.", "Completed.",
                                       "Success", "Task completed.", "Done, sir.", "Готово, сэр.",
                                       "Sir.", "сэр"])
    def test_terse_never_final(self, terse):
        out = polish_response("Открой Safari", terse)
        _assert_natural(out)
        assert out.strip().rstrip(".!").lower() not in FORBIDDEN_FINALS

    def test_json_tool_call_never_shown(self):
        raw = '{"type":"function","name":"open_app","parameters":{"name":"Safari"}}'
        out = polish_response("Открой Safari", raw)
        _assert_natural(out)
        assert "{" not in out
        assert "open_app" not in out

    def test_json_status_payload_never_shown(self):
        out = polish_response("Открой Safari", '{"status":"ok"}')
        _assert_natural(out)
        assert "{" not in out

    def test_empty_response_gets_contextual(self):
        out = polish_response("Открой Safari", "   ")
        _assert_natural(out)
        assert "Safari" in out

    def test_tool_result_without_final_text(self):
        out = polish_response("Открой Safari", "tool_result: {'status': 'ok'}",
                              tool_name="open_app", tool_args={"name": "Safari"})
        _assert_natural(out)
        assert "tool_result" not in out

    def test_json_error_payload_humanized(self):
        raw = '{"error": "google_auth_required", "detail": "oauth missing"}'
        out = polish_response("Открой Safari", raw)
        _assert_natural(out)
        assert "{" not in out
        assert "google_auth_required" not in out
        assert "oauth" not in out.lower() or "доступ" in out.lower() or "authorize" in out.lower()

    def test_llm_unavailable_fallback_replaced(self):
        out = polish_response("Открой Safari", "Настройте LLM для полного ответа. Доступные бэкенды: нет.")
        _assert_natural(out)
        assert "настройте llm" not in out.lower()

    def test_engine_all_backends_unavailable_never_leaks(self):
        # Engine graceful failure (all backends down) must never reach the
        # user as technical state — stress-test finding #1.
        raw = "All LLM backends are unavailable. Please configure an API key or install mlx-lm."
        out = polish_response("Открой Safari", raw)
        _assert_natural(out)
        assert "mlx-lm" not in out.lower()
        assert "api key" not in out.lower()
        assert "backend" not in out.lower()

    def test_engine_unavailable_with_tool_context_rebuilt(self):
        raw = "All LLM backends are unavailable. Please configure an API key or install mlx-lm."
        out = polish_response("Открой Safari", raw,
                              tool_name="open_app", tool_args={"name": "Safari"})
        _assert_natural(out)
        assert "Safari" in out

    def test_engine_unavailable_greeting_still_natural(self):
        raw = "All LLM backends are unavailable. Please configure an API key or install mlx-lm."
        out = polish_response("Привет", raw)
        _assert_natural(out)
        assert "mlx-lm" not in out.lower()
        assert "api key" not in out.lower()

    def test_api_key_redacted_never_reaches_user(self):
        # Stress-test finding #2: a key echoed by the model must be redacted
        # AND the remaining "Done." must be rebuilt (not shown terse).
        key = "sk-or-v1-" + "a" * 40
        out = polish_response("Открой Safari", f"Done. {key}")
        _assert_natural(out)
        assert "sk-or-v1-" not in out
        assert out.strip().rstrip(".!").lower() not in FORBIDDEN_FINALS

    def test_code_fence_stripped_when_not_requested(self):
        # Stress-test finding #3: raw applescript/impl code never belongs in
        # a personal-assistant answer unless the user asked for code.
        out = polish_response("Который час?", "```applescript\ncurrent date\n```")
        _assert_natural(out)
        assert "applescript" not in out
        assert "current date" not in out

    def test_code_fence_kept_when_user_asks_for_code(self):
        out = polish_response("напиши код на python", "```python\nprint(1)\n```")
        assert "print(1)" in out

    def test_terse_with_redacted_key_is_still_terse(self):
        from modules.llm.personality import is_terse_response
        assert is_terse_response("Done. <ключ скрыт>")
        assert is_terse_response("Готово. <ключ скрыт>")

    def test_strip_tool_call_json_fenced(self):
        raw = 'I did it. ```json\n{"action":"open_app","params":{"name":"Safari"}}\n``` The app is open.'
        cleaned = strip_tool_call_json(raw)
        assert "open_app" not in cleaned and "params" not in cleaned
        assert "The app is open." in cleaned

    def test_xml_tool_call_never_shown(self):
        # Live finding: models emit FOL/Anthropic-style XML tool calls as text.
        raw = '<invoke><tool>open_app</tool><param name="name">Safari</param></invoke>'
        out = polish_response("Открой Safari", raw)
        _assert_natural(out)
        assert "<tool>" not in out
        assert "open_app" not in out
        assert "Safari" in out

    def test_xml_tool_call_with_prose_keeps_prose(self):
        # The exact leak seen in the live FOL test: prose + bare <tool> block
        # (model omitted the opening <invoke>) — prose must survive, XML must not.
        raw = (
            "Посмотрю результаты поиска и выделю главное.\n"
            '<tool>open</tool>\n'
            '<param name="url">https://www.google.com/search?q=новости+про+OpenAI+2024</param>\n'
            "</invoke>"
        )
        out = polish_response("А какая из них самая важная?", raw)
        assert "<tool>" not in out and "<param" not in out and "</invoke>" not in out
        assert "Посмотрю результаты поиска" in out

    def test_strip_tool_call_xml_direct(self):
        from modules.llm.personality import strip_tool_call_xml

        assert strip_tool_call_xml(
            '<invoke><tool>open</tool><param name="url">https://x.com</param></invoke>'
        ) == ""
        assert strip_tool_call_xml("Сделано.\n<tool>open</tool>\n</invoke>") == "Сделано."
        assert strip_tool_call_xml(
            '<tool>search</tool><param name="q">OpenAI</param>'
        ) == ""

    def test_strip_tool_call_xml_multi_param_and_attribute_style(self):
        from modules.llm.personality import strip_tool_call_xml

        # Multiple <param> blocks after the <tool>.
        assert strip_tool_call_xml(
            '<tool>open</tool>'
            '<param name="app">Safari</param>'
            '<param name="url">https://apple.com</param>'
        ) == ""
        # Self-closing attribute style.
        assert strip_tool_call_xml(
            '<tool>click</tool><param name="x" value="100"/>'
        ) == ""
        # Unquoted attribute value.
        assert strip_tool_call_xml(
            '<tool>search</tool><param name=q>OpenAI</param>'
        ) == ""
        # Prose survives, multi-param block is dropped.
        cleaned = strip_tool_call_xml(
            "Открою. "
            '<tool>open</tool>'
            '<param name="app">Safari</param><param name="fullscreen">true</param>'
            "</invoke>"
        )
        assert cleaned == "Открою."


# ─── Scenario: Mac control methods are bilingual and honorific-free ─────────

class TestMacControlNaturalization:
    @pytest.mark.asyncio
    async def test_open_app_ru_no_sir(self, monkeypatch):
        fol = _make_fol()
        import subprocess as sp

        def _fake_popen(cmd, *a, **k):
            # The real call passes stdout/stderr kwargs — accept and ignore them.
            # Return value is unused by _mac_open_app, so None is safe.
            assert cmd and cmd[0] == "open"

        monkeypatch.setattr(sp, "Popen", _fake_popen)
        out = await fol._mac_open_app("Safari", "ru")
        assert out == "Safari открыт."
        assert "sir" not in out.lower()

    @pytest.mark.asyncio
    async def test_open_app_en(self, monkeypatch):
        fol = _make_fol()
        import subprocess as sp

        def _fake_popen(cmd, *a, **k):
            assert cmd and cmd[0] == "open"

        monkeypatch.setattr(sp, "Popen", _fake_popen)
        out = await fol._mac_open_app("Terminal", "en")
        assert out == "Terminal is open."

    def test_volume_mute_ru(self, monkeypatch):
        fol = _make_fol()
        import subprocess as sp
        monkeypatch.setattr(sp, "run", lambda *a, **k: None)
        out = fol._mac_volume("mute", 0, "ru")
        assert out == "Звук выключен."

    def test_youtube_ru(self, monkeypatch):
        fol = _make_fol()
        import subprocess as sp
        monkeypatch.setattr(sp, "Popen", lambda *a, **k: None)
        out = fol._mac_play_youtube("", "ru")
        assert out == "Открыл YouTube."
        assert "sir" not in out.lower()

    def test_search_ru(self, monkeypatch):
        fol = _make_fol()
        import subprocess as sp
        monkeypatch.setattr(sp, "Popen", lambda *a, **k: None)
        out = fol._mac_search("файл fol", "ru")
        assert "поиск" in out.lower()
        assert "Ищу:" not in out

    def test_battery_ru(self, monkeypatch):
        fol = _make_fol()
        import subprocess as sp
        monkeypatch.setattr(sp, "run", lambda *a, **k: type("R", (), {"stdout": "Now drawing from 'Battery Power'\n  89%; discharging;"})())
        out = fol._mac_battery("ru")
        assert "батаре" in out.lower()
        assert "89" in out

    def test_greet_no_sir(self):
        fol = _make_fol()
        ru = fol._greet("ru")
        en = fol._greet("en")
        assert "сэр" not in ru.lower() and "sir" not in en.lower()


# ─── Scenario: voice path uses the same layer ───────────────────────────────

class TestVoicePath:
    @pytest.mark.asyncio
    async def test_voice_process_returns_same_natural_text(self):
        # Voice handler (fol/api/websocket/handler.py) calls fol.process() —
        # the very same method the text path uses. A terse LLM must not win.
        fol = _make_fol()
        out = await fol.process("Открой Safari")
        _assert_natural(out)
        assert "Safari" in out

    @pytest.mark.asyncio
    async def test_voice_ready_tts_never_terse(self):
        fol = _make_fol()
        out = await fol.process("Как дела?")
        _assert_natural(out)
        assert "sir" not in out.lower()
