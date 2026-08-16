"""Tests for the Response Formatter — the sanitization layer between the
Agent and the UI.

Guarantees:
- tool-call JSON never appears in user-facing output
- JSON function calls are filtered (bare and fenced)
- the final response is always a plain string
- errors are humanized (never raw JSON)
- tool_call/tool_result SSE events never reach the user
"""
from __future__ import annotations

import asyncio

import pytest

from response_formatter import (
    StreamingTextFilter,
    detect_language,
    extract_tool_call,
    format_final_response,
    humanize_error,
    humanize_tool_call,
    is_tool_call_json,
    sanitize_event_stream,
    strip_tool_call_json,
)


# ---------------------------------------------------------------------------
# Tool-call JSON detection
# ---------------------------------------------------------------------------

class TestExtractToolCall:
    """The exact JSON shapes the user reported leaking into the chat."""

    @pytest.mark.parametrize("payload,expected", [
        # User example 1
        ('{"type":"function","name":"open_app","parameters":{"app":"Safari"}}',
         ("open_app", {"app": "Safari"})),
        # User example 2
        ('{"type":"function","name":"log_daily_activity",'
         '"parameters":{"summary":"Taking a break from work"}}',
         ("log_daily_activity", {"summary": "Taking a break from work"})),
        # Ollama-style {"name": ..., "arguments": ...}
        ('{"name":"open_app","arguments":{"name":"Safari"}}',
         ("open_app", {"name": "Safari"})),
        # Anthropic-style {"type":"tool_use","name":...,"input":...}
        ('{"type":"tool_use","name":"open_app","input":{"name":"Safari"}}',
         ("open_app", {"name": "Safari"})),
        # ReAct-style {"action": ..., "params": ...}
        ('{"thought":"opening it","action":"open_app","params":{"name":"Safari"}}',
         ("open_app", {"name": "Safari"})),
        # OpenAI payload nested under "function"
        ('{"function":{"name":"open_app","arguments":"{\\"name\\":\\"Safari\\"}"}}',
         ("open_app", {"name": "Safari"})),
        # Prose wrapped around the JSON
        ('Sure! Here is the call: {"type":"function","name":"open_app",'
         '"parameters":{"app":"Safari"}}',
         ("open_app", {"app": "Safari"})),
        # Markdown fenced
        ('```json\n{"type":"function","name":"open_app","parameters":{"app":"Safari"}}\n```',
         ("open_app", {"app": "Safari"})),
    ])
    def test_extracts_tool_call(self, payload, expected):
        assert extract_tool_call(payload) == expected

    @pytest.mark.parametrize("text", [
        '{"status":"ok"}',                 # no name → not a tool call
        '{"type":"text","text":"hello"}',  # explicit non-tool type
        "Hello there, how can I help?",
        "I'll open Safari right away.",
        "",
        '{"a":1,"b":{"nested":true}}',     # no tool keys
    ])
    def test_rejects_non_tool_json(self, text):
        assert extract_tool_call(text) is None
        assert is_tool_call_json(text) is False

    def test_is_tool_call_json_positive(self):
        assert is_tool_call_json(
            '{"type":"function","name":"open_app","parameters":{"app":"Safari"}}'
        ) is True


class TestStripToolCallJson:
    """Bare + fenced JSON function calls are filtered from text."""

    def test_user_example_open_app(self):
        text = '{"type":"function","name":"open_app","parameters":{"app":"Safari"}}'
        assert strip_tool_call_json(text) == ""

    def test_user_example_log_daily_activity(self):
        text = ('{"type":"function","name":"log_daily_activity",'
                '"parameters":{"summary":"Taking a break from work"}}')
        assert strip_tool_call_json(text) == ""

    def test_prose_survives(self):
        text = ('I can help with that. {"type":"function","name":"open_app",'
                '"parameters":{"app":"Safari"}} Done, sir.')
        cleaned = strip_tool_call_json(text)
        assert "type" not in cleaned and "open_app" not in cleaned
        assert "I can help with that." in cleaned
        assert "Done, sir." in cleaned

    def test_fenced_block_removed(self):
        text = ('Let me do that.\n```json\n'
                '{"type":"function","name":"open_app","parameters":{"app":"Safari"}}\n'
                '```\nThere you go.')
        cleaned = strip_tool_call_json(text)
        assert "open_app" not in cleaned and "```" not in cleaned
        assert "Let me do that." in cleaned and "There you go." in cleaned

    def test_non_tool_json_kept(self):
        text = 'Here is the data: {"status":"ok","count":3}'
        assert strip_tool_call_json(text) == text


class TestStreamingTextFilter:
    """Token-by-token: a JSON tool call must never stream to the user."""

    def test_tool_call_never_streams(self):
        filt = StreamingTextFilter()
        payload = '{"type":"function","name":"open_app","parameters":{"app":"Safari"}}'
        emitted = []
        # Feed one character at a time — the worst case.
        for ch in payload:
            out = filt.process(ch)
            if out:
                emitted.append(out)
        assert emitted == [], f"tool call leaked: {emitted}"
        assert filt.flush() == ""

    def test_prose_passes_through(self):
        filt = StreamingTextFilter()
        out = "".join(filt.process(ch) for ch in "Открыл Safari, сэр.")
        assert "Открыл Safari" in out

    def test_tool_call_then_prose(self):
        filt = StreamingTextFilter()
        payload = '{"type":"function","name":"open_app","parameters":{"app":"Safari"}}'
        emitted = ""
        for ch in payload + "All done.":
            emitted += filt.process(ch)
        emitted += filt.flush()
        assert "open_app" not in emitted and "function" not in emitted
        assert "All done." in emitted

    def test_partial_tool_call_flushed_as_prose_when_not_a_tool_call(self):
        # A '{-prefixed object that never becomes a tool call is emitted.
        filt = StreamingTextFilter()
        payload = '{"status":"ok","message":"everything fine"}'
        emitted = ""
        for ch in payload:
            emitted += filt.process(ch)
        emitted += filt.flush()
        assert "everything fine" in emitted


# ---------------------------------------------------------------------------
# Humanization
# ---------------------------------------------------------------------------

class TestHumanizeToolCall:
    def test_open_app_russian(self):
        # No constant "сэр" honorific — plain natural confirmation.
        assert humanize_tool_call("open_app", {"name": "Safari"}, "ru") == "Открыл Safari."

    def test_open_app_english(self):
        assert humanize_tool_call("open_app", {"name": "Safari"}, "en") == "Opened Safari."

    def test_log_daily_activity_russian(self):
        assert humanize_tool_call(
            "log_daily_activity",
            {"summary": "Taking a break from work"},
            "ru",
        ) == "Записал это в дневную активность."

    def test_log_daily_activity_english(self):
        assert humanize_tool_call("log_daily_activity", {}, "en") == \
            "Logged it to your daily activity."

    def test_render_tools_give_no_text(self):
        assert humanize_tool_call("render_task_approval", {}, "ru") == ""

    def test_unknown_tool_natural_fallback(self):
        # Bare "Готово."/"Done." is FORBIDDEN — a natural confirmation instead.
        ru = humanize_tool_call("weird_tool_xyz", {}, "ru")
        en = humanize_tool_call("weird_tool_xyz", {}, "en")
        assert ru not in ("Готово.", "Done.")
        assert en not in ("Готово.", "Done.")
        assert len(ru) > 10 and len(en) > 10
        assert ru != "Готово."


class TestHumanizeError:
    def test_google_auth_required(self):
        # User example: {"error":"OAuth missing"} → human text
        msg = humanize_error({"error": "google_auth_required"})
        assert "Google Calendar" in msg
        assert "авторизуйте" in msg
        assert "{" not in msg

    def test_oauth_missing_string(self):
        msg = humanize_error("OAuth missing")
        assert "Google" in msg and "авторизуйте" in msg

    def test_never_returns_raw_json(self):
        raw = '{"error":"internal_code_42","detail":"something broke"}'
        msg = humanize_error(raw)
        assert "{" not in msg
        assert "internal_code_42" not in msg
        assert msg  # non-empty human text

    def test_plain_human_message_passes_through(self):
        # Idempotent: an already-human message is not clobbered.
        assert humanize_error("Что-то пошло не так. Попробуйте ещё раз.") == \
            "Что-то пошло не так. Попробуйте ещё раз."


# ---------------------------------------------------------------------------
# Final response — always a string
# ---------------------------------------------------------------------------

class TestFormatFinalResponse:
    def test_always_string(self):
        for bad in (None, "", "   ", "\n\t"):
            result = format_final_response(bad)
            assert isinstance(result, str)
            assert result.strip()

    def test_json_only_becomes_confirmation(self):
        text = '{"type":"function","name":"open_app","parameters":{"app":"Safari"}}'
        result = format_final_response(
            text,
            executed_tools=[("open_app", {"name": "Safari"})],
            language="ru",
        )
        assert result == "Открыл Safari."

    def test_text_with_embedded_json_stripped(self):
        text = ('I did it. {"type":"function","name":"log_daily_activity",'
                '"parameters":{"summary":"break"}} The note is saved.')
        result = format_final_response(text, [], "ru")
        assert "function" not in result and "parameters" not in result
        assert "The note is saved." in result

    def test_empty_without_tools_defaults(self):
        # The final fallback must be a natural sentence — never a bare
        # "Готово." / "Done.".
        ru = format_final_response("", [], "ru")
        en = format_final_response("", [], "en")
        assert ru not in ("Готово.", "Done.")
        assert en not in ("Готово.", "Done.")
        assert len(ru) > 10 and len(en) > 10

    def test_plain_text_preserved(self):
        # Honorifics are stripped, the natural sentence is kept.
        assert format_final_response("Открыл Safari, сэр.") == "Открыл Safari."


# ---------------------------------------------------------------------------
# SSE boundary — tool events never reach the user
# ---------------------------------------------------------------------------

class TestSanitizeEventStream:
    async def _collect(self, events):
        return [e async for e in sanitize_event_stream(events)]

    @pytest.mark.asyncio
    async def test_tool_call_events_dropped(self):
        async def leaky_stream():
            yield ("state", {"state": "thinking"})
            yield ("token", {"text": '{"type":"function","name":"open_app",'
                                    '"parameters":{"app":"Safari"}}'})
            yield ("tool_call", {"tool": "browser_goto", "args": {"url": "x"}})
            yield ("tool_result", {"tool": "browser_goto", "result": {"status": "ok"}})
            yield ("tool_progress", {"tool": "sync_cookies", "message": "copying"})
            yield ("state", {"state": "complete", "message": "Done."})

        events = await self._collect(leaky_stream())

        event_types = [e[0] for e in events]
        assert "tool_call" not in event_types
        assert "tool_result" not in event_types
        assert "tool_progress" not in event_types
        assert "_tool_use" not in event_types

        # The JSON tool call in the token stream never reaches the user.
        token_text = "".join(e[1].get("text", "") for e in events if e[0] == "token")
        assert "open_app" not in token_text and "function" not in token_text

    @pytest.mark.asyncio
    async def test_components_pass_through(self):
        async def stream():
            yield ("component", {"a2ui": {"version": "0.8", "components": []}})

        events = await self._collect(stream())
        assert events == [("component", {"a2ui": {"version": "0.8", "components": []}})]

    @pytest.mark.asyncio
    async def test_errors_humanized(self):
        async def stream():
            yield ("error", {"error": "google_auth_required"})

        events = await self._collect(stream())
        assert events[0][0] == "error"
        assert "Google Calendar" in events[0][1]["message"]
        assert "{" not in events[0][1]["message"]

    @pytest.mark.asyncio
    async def test_final_token_always_string(self):
        async def stream():
            yield ("state", {"state": "complete", "message": "Всё готово."})

        events = await self._collect(stream())
        for event_type, data in events:
            if event_type == "state":
                assert isinstance(data.get("message", ""), str)


class TestDetectLanguage:
    def test_russian(self):
        assert detect_language("открой Safari") == "ru"

    def test_english(self):
        assert detect_language("open Safari please") == "en"

    def test_empty_defaults_ru(self):
        assert detect_language("") == "ru"
