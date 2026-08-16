"""Final Response Layer guarantees (orchestrator side).

The orchestrator's ``format_final_response`` is the last gate before the
user's chat window. Contract (spec 14/15/19):

  - A bare "Done." / "Готово." / "OK." / "Принято." can NEVER be the final
    answer — even when the model's text IS one of those strings.
  - Unknown tools get a natural confirmation, never "Готово."/"Done.".
  - Honorifics ("X, sir." / "X, сэр.") are stripped.
  - Errors are humanized; JSON and tracebacks never surface.
"""

from __future__ import annotations

import pytest

from orchestrator.response_formatter import (
    _is_bare_confirmation,
    format_final_response,
    humanize_error,
    humanize_tool_call,
    sanitize_event_stream,
)

FORBIDDEN = ("done", "готово", "ok", "принято", "выполнено", "сделано",
             "success", "completed", "task completed", "yes")


def _assert_natural(text: str):
    assert text and text.strip(), "final answer must be non-empty"
    stripped = text.strip().rstrip(".!").strip().lower()
    assert stripped not in FORBIDDEN, f"bare confirmation leaked: {text!r}"
    assert "traceback" not in text.lower()
    assert "{" not in text, f"JSON leaked: {text!r}"


class TestIsBareConfirmation:
    def test_bare_forms(self):
        for bad in ("Done", "Done.", "Готово.", "ok", "OK", "Принято",
                    "Выполнено.", "Completed.", "Task completed.", "Done, sir.",
                    "Готово, сэр."):
            assert _is_bare_confirmation(bad), bad

    def test_natural_sentences_are_not_bare(self):
        for good in ("Safari открыт.", "Открыл Safari.", "The report is saved.",
                     "Готово, но есть один нюанс: сеть не работает."):
            assert not _is_bare_confirmation(good), good


class TestTerseNeverFinal:
    def test_llm_says_done(self):
        assert format_final_response("Done.") not in ("Done.", "Done")
        _assert_natural(format_final_response("Done."))

    def test_llm_says_готово(self):
        out = format_final_response("Готово.", [], "ru")
        _assert_natural(out)

    def test_llm_says_ok(self):
        _assert_natural(format_final_response("OK"))

    def test_llm_says_done_sir(self):
        out = format_final_response("Done, sir.", [], "en")
        _assert_natural(out)

    def test_terse_with_executed_tool_rebuilt(self):
        out = format_final_response("Done.", [("open_app", {"name": "Safari"})], "ru")
        assert "Safari" in out
        _assert_natural(out)

    def test_json_error_payload_humanized(self):
        out = format_final_response('{"error": "google_auth_required"}', [], "ru")
        _assert_natural(out)
        assert "{" not in out
        assert "google_auth_required" not in out

    def test_json_status_payload_keeps_useful_result(self):
        # {"status":"ok","result":"note saved"} → the useful field survives.
        out = format_final_response('{"status": "ok", "result": "note saved"}', [], "ru")
        _assert_natural(out)
        assert "{" not in out
        assert "note saved" in out

    def test_fenced_status_json_never_leaks(self):
        out = format_final_response('```json\n{"status": "ok"}\n```', [], "ru")
        _assert_natural(out)
        assert "{" not in out

    def test_bare_sir_rebuilt(self):
        out = format_final_response("Sir.", [], "en")
        _assert_natural(out)
        assert "sir" not in out.lower()

    def test_empty_with_tools_rebuilt(self):
        out = format_final_response("", [("open_app", {"name": "Safari"})], "ru")
        assert out == "Открыл Safari."

    def test_empty_no_tools_natural_fallback(self):
        ru = format_final_response("", [], "ru")
        en = format_final_response("", [], "en")
        _assert_natural(ru)
        _assert_natural(en)
        assert ru != en  # follows the language


class TestUnknownToolHumanized:
    def test_unknown_tool_ru(self):
        out = humanize_tool_call("mystery_tool_9", {}, "ru")
        _assert_natural(out)

    def test_unknown_tool_en(self):
        out = humanize_tool_call("mystery_tool_9", {}, "en")
        _assert_natural(out)

    def test_fol_command_en(self):
        out = humanize_tool_call("fol_command", {}, "en")
        assert "Done." != out
        _assert_natural(out)


class TestHonorificsStripped:
    def test_llm_sir_text_stripped(self):
        assert format_final_response("Safari is open, sir.", [], "en") == "Safari is open."

    def test_llm_сэр_text_stripped(self):
        assert format_final_response("Открыл Safari, сэр.", [], "ru") == "Открыл Safari."


class TestErrorsHumanized:
    def test_raw_json_error_never_shown(self):
        out = format_final_response(None, [], "ru")  # fallback path is natural
        _assert_natural(out)
        msg = humanize_error('{"error": "internal_code_42", "detail": "boom"}', "ru")
        _assert_natural(msg)
        assert "internal_code_42" not in msg

    def test_traceback_never_shown(self):
        msg = humanize_error("Traceback (most recent call last):\nTypeError: x", "ru")
        _assert_natural(msg)
        assert "TypeError" not in msg

    def test_llm_unavailable_message_never_shown(self):
        # Engine graceful failure (all backends down) is technical state and
        # must never reach the user — stress-test finding #1 (orchestrator side).
        raw = "All LLM backends are unavailable. Please configure an API key or install mlx-lm."
        out = format_final_response(raw, [], "ru")
        _assert_natural(out)
        assert "mlx-lm" not in out.lower()
        assert "api key" not in out.lower()
        assert "backend" not in out.lower()

    def test_raw_error_sentence_humanized(self):
        # "Error: ..." in model text must be humanized, never shown verbatim.
        out = format_final_response("Error: connection refused to service", [], "ru")
        _assert_natural(out)
        assert "Error:" not in out
        assert "connection refused" not in out.lower()

    def test_traceback_sentence_humanized(self):
        out = format_final_response(
            "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: boom",
            [], "ru")
        _assert_natural(out)
        assert "ValueError" not in out
        assert "Traceback" not in out

    def test_api_key_redacted_never_reaches_user(self):
        # Stress-test finding #2: keys echoed by the model are redacted and
        # the remaining bare confirmation is rebuilt.
        key = "sk-or-v1-" + "a" * 40
        out = format_final_response(f"Done. {key}", [], "ru")
        _assert_natural(out)
        assert "sk-or-v1-" not in out

    def test_code_fence_stripped_when_not_requested(self):
        # Stress-test finding #3: raw applescript/shell code is implementation
        # detail — never shown unless the user asked for code.
        out = format_final_response("```applescript\ncurrent date\n```", [], "ru")
        _assert_natural(out)
        assert "applescript" not in out
        assert "current date" not in out

    def test_code_fence_kept_when_user_asks_for_code(self):
        out = format_final_response("```python\nprint(1)\n```", [], "ru",
                                    user_input="напиши код на python")
        assert "print(1)" in out


class TestSanitizeStream:
    @pytest.mark.asyncio
    async def test_tool_events_dropped(self):
        async def fake_events():
            yield ("state", {"state": "thinking"})
            yield ("tool_call", {"tool": "open_app", "args": {"name": "Safari"}})
            yield ("tool_result", {"result": "ok"})
            yield ("token", {"text": "Safari is open."})
            yield ("error", {"message": '{"error": "rate_limit"}'})
            yield ("state", {"state": "complete", "message": "Safari is open."})

        events = [e async for e in sanitize_event_stream(fake_events())]
        types = [t for t, _ in events]
        assert "tool_call" not in types and "tool_result" not in types
        texts = " ".join(str(d) for _, d in events)
        assert "open_app" not in texts
        assert "rate_limit" not in texts
        assert "Safari is open" in texts
