"""Response Formatter — the single sanitization layer between the Agent and the UI.

Some models (notably small Ollama models) return tool calls as raw JSON text
instead of structured ``tool_calls`` deltas, and tools can fail with raw
error dicts. Without a formatting layer all of that leaks straight to the
user's chat window.

This module guarantees that the user only ever sees natural-language text
or an A2UI component payload:

    User → Agent → Tool Call → Tool Result → Response Formatter → text/component → UI

Rules enforced here:
  - Never expose tool calls or JSON structures to the user.
  - Tool names, parameters, internal logs and agent reasoning are internal.
  - After tools execute the user gets a short, natural confirmation.
  - Errors are converted to friendly human text (never raw JSON).
  - The final response is always a plain string.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Tool-call JSON detection
# ---------------------------------------------------------------------------

# Keys that mark a JSON object as a tool call. A dict is only treated as a
# tool call if it carries one of these *plus* a resolvable tool name.
_TOOL_CALL_TYPE_VALUES = {"function", "tool_use", "tool_call"}


def _first_balanced_json(text: str) -> tuple[str | None, int]:
    """Return (json_string, end_index) of the first balanced ``{...}`` in text."""
    start = text.find("{")
    if start == -1:
        return None, -1
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1], i + 1
    return None, -1


def _resolve_tool_name(obj: dict[str, Any]) -> str | None:
    """Extract the tool name from a candidate JSON object, or None."""
    name = obj.get("name")
    if isinstance(name, dict):  # OpenAI: {"function": {"name": ...}}
        name = name.get("name")
    if not name:
        action = obj.get("action")
        if action:
            name = action
    if not name:
        function = obj.get("function")
        if isinstance(function, dict):
            name = function.get("name")
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or not name.replace("_", "").isalnum():
        return None
    return name


def _resolve_tool_args(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the arguments dict from a candidate tool-call object."""
    for key in ("arguments", "parameters", "input", "params"):
        args = obj.get(key)
        if args is None:
            # OpenAI payload: {"function": {"name": ..., "arguments": "..."}}
            function = obj.get("function")
            if isinstance(function, dict):
                args = function.get(key)
        if args is None:
            continue
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                return None
        if isinstance(args, dict):
            return args
        return None
    return None


def extract_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Try to parse a tool call that a model emitted as plain JSON text.

    Supported shapes:
      {"type": "function", "name": "open_app", "parameters": {"name": "Safari"}}
      {"name": "open_app", "arguments": {"name": "Safari"}}
      {"type": "tool_use", "name": "...", "input": {...}}
      {"action": "open_app", "params": {...}}            (ReAct)
      {"thought": "...", "action": "...", "params": {...}} (ReAct)
      {"function": {"name": "...", "arguments": "..."}}  (OpenAI payload)

    Returns (name, arguments) or None if the text is not a tool call.
    """
    text = text.strip().lstrip("`").rstrip("`").strip()
    json_str, _ = _first_balanced_json(text)
    if json_str is None:
        return None
    try:
        obj = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None

    # Explicit "type" that is NOT a tool call → not a tool call.
    obj_type = obj.get("type")
    if isinstance(obj_type, str) and obj_type not in _TOOL_CALL_TYPE_VALUES:
        return None

    name = _resolve_tool_name(obj)
    if name is None:
        return None
    args = _resolve_tool_args(obj)
    if args is None:
        return None
    return name, args


def is_tool_call_json(text: str) -> bool:
    """True if ``text`` (or a JSON object inside it) is a tool call."""
    return extract_tool_call(text) is not None


def strip_tool_call_json(text: str) -> str:
    """Remove embedded tool-call JSON from a text string.

    Handles bare JSON, markdown-fenced blocks (```json), and JSON followed
    by punctuation (",", ".", "!"). Non-tool-call JSON (e.g. data the model
    is legitimately quoting) is left untouched.
    """
    if not text:
        return text

    # Remove fenced ```json ... ``` blocks that parse as tool calls.
    def _drop_fence(match: re.Match) -> str:
        block = match.group(1)
        return "" if is_tool_call_json(block) else match.group(0)

    text = re.sub(r"```(?:json)?\s*(.*?)```", _drop_fence, text, flags=re.DOTALL)

    # Remove bare (unfenced) tool-call JSON objects.
    while True:
        json_str, end = _first_balanced_json(text)
        if json_str is None:
            break
        if extract_tool_call(json_str) is not None:
            # Also swallow trailing punctuation right after the object.
            rest = text[end:]
            m = re.match(r"^[.,!;:]+", rest)
            if m:
                end += m.end()
            text = text[: text.find(json_str)] + text[end:]
        else:
            break
    # Clean up any leftover empty fences / stray backticks the JSON left behind.
    text = re.sub(r"```json\s*```", "", text)
    text = re.sub(r"```\s*```", "", text)
    return text.strip()


def _looks_like_tool_call_prefix(text: str) -> bool:
    """Streaming guard: could this (possibly partial) text become a tool call?

    Used to hold tokens back until we know whether they are a tool call or
    real prose. Bounded by the caller via ``StreamingTextFilter``.
    """
    stripped = text.strip().lstrip("`").strip()
    if stripped.startswith("```json"):
        return True
    if not stripped.startswith("{"):
        return False
    # An incomplete JSON object could still become a tool call — hold it until
    # we can tell (this is why single-char token feeds never leak).
    if "}" not in stripped or len(stripped) < 4:
        return True
    head = stripped[1:160].lower()
    return any(
        key in head
        for key in ('"type"', '"name"', '"function"', '"action"', '"thought"',
                    '"arguments"', '"parameters"', '"input"', '"params"')
    )


class StreamingTextFilter:
    """Streams text to the user while holding back anything that could be a
    tool-call JSON structure. Last line of defense at the SSE boundary.

    Usage:
        filt = StreamingTextFilter()
        for chunk in raw_tokens:
            safe = filt.process(chunk)
            if safe:
                emit_token(safe)
        tail = filt.flush()
        if tail:
            emit_token(tail)
    """

    MAX_HOLD = 512  # chars; beyond this we give up holding (prose starting with '{')

    def __init__(self) -> None:
        self._pending = ""

    def process(self, chunk: str) -> str:
        text = self._pending + chunk
        if _looks_like_tool_call_prefix(text):
            call = extract_tool_call(text)
            if call is not None:
                # The held text is a complete tool call → drop it, keep the rest.
                _, end = _first_balanced_json(text)
                self._pending = ""
                if end > 0:
                    return self.process(text[end:])
                return ""
            if len(text) <= self.MAX_HOLD:
                self._pending = text
                return ""
        # Not (or no longer) a tool call — emit everything.
        self._pending = ""
        return text

    def flush(self) -> str:
        pending, self._pending = self._pending, ""
        if not pending:
            return ""
        if extract_tool_call(pending) is not None:
            return ""  # was a tool call all along — never show it
        return pending


# ---------------------------------------------------------------------------
# Language detection (bilingual: Russian + English)
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Heuristic: 'ru' if the text contains a meaningful share of Cyrillic."""
    if not text:
        return "ru"
    cyrillic = sum(1 for ch in text if "\u0400" <= ch <= "\u04FF")
    if not cyrillic:
        return "en"
    return "ru" if cyrillic / max(len(text), 1) > 0.05 else "en"


# ---------------------------------------------------------------------------
# Activity events — coarse, user-safe status (never the raw tool name)
# ---------------------------------------------------------------------------

_EMAIL_TOOLS = {"send_email", "draft_email", "reply_to_email", "read_emails",
                "get_contact_info", "summarize_emails"}
_CALENDAR_TOOLS = {"create_event", "update_event", "delete_event", "list_events"}
_DOC_TOOLS = {"create_document", "create_presentation", "share_document"}
_BROWSER_TOOLS = {"browser_goto", "browser_click", "browser_fill", "browser_snapshot",
                  "browser_text", "browser_press"}
_DESKTOP_TOOLS = {"open_app", "close_app", "click", "type_text", "hotkey", "screenshot",
                  "scroll", "drag", "clipboard_get", "clipboard_set", "notify", "activate_app"}
_SAFARI_TOOLS = {"safari_goto", "safari_js", "safari_get_url", "safari_get_text"}
_MEMORY_TOOLS = {"save_to_obsidian", "remember", "log_daily_activity", "log_activity",
                 "get_daily_summary", "learn_from_web", "append_event"}
_MESSAGING_TOOLS = {"send_telegram", "send_whatsapp"}


def activity_for_tool(tool_name: str, language: str = "ru") -> tuple[str, str]:
    """Return a coarse (category, label) pair describing an in-flight tool call.

    Deliberately hides the tool name and arguments — the user only sees a
    generic human-readable status like ("computer", "Работаю на рабочем столе…").
    render_* tools return ("", "") because their A2UI component is shown.
    """
    if tool_name.startswith("render_"):
        return "", ""
    if tool_name in _BROWSER_TOOLS or tool_name in ("sync_cookies", "list_profiles"):
        return "computer", ("Работаю в браузере…" if language == "ru" else "Working in the browser…")
    if tool_name in _SAFARI_TOOLS:
        return "computer", ("Работаю в Safari…" if language == "ru" else "Working in Safari…")
    if tool_name in _DESKTOP_TOOLS or tool_name == "fol_command":
        return "computer", ("Работаю на рабочем столе…" if language == "ru" else "Working on the desktop…")
    if tool_name in _MEMORY_TOOLS:
        return "memory", ("Сохраняю в память…" if language == "ru" else "Saving to memory…")
    if tool_name in _EMAIL_TOOLS:
        return "productivity", ("Работаю с почтой…" if language == "ru" else "Working with email…")
    if tool_name in _CALENDAR_TOOLS:
        return "productivity", ("Работаю с календарём…" if language == "ru" else "Working with your calendar…")
    if tool_name in _DOC_TOOLS:
        return "productivity", ("Работаю с документами…" if language == "ru" else "Working with documents…")
    if tool_name == "search_web":
        return "web", ("Ищу в интернете…" if language == "ru" else "Searching the web…")
    if tool_name in _MESSAGING_TOOLS:
        return "computer", ("Отправляю сообщение…" if language == "ru" else "Sending a message…")
    return "other", ("Выполняю…" if language == "ru" else "Working…")


# ---------------------------------------------------------------------------
# Humanization — tools become short natural confirmations
# ---------------------------------------------------------------------------

def humanize_tool_call(
    tool_name: str,
    args: dict[str, Any] | None = None,
    language: str = "ru",
) -> str:
    """Turn an executed tool call into a natural-language confirmation.

    Mirrors the examples:
      open_app("Safari")            → "Открыл Safari, сэр."
      log_daily_activity(...)       → "Записал это в дневную активность."
    render_* tools return "" — their A2UI component is the response itself.
    """
    args = args or {}
    name_val = str(args.get("name") or args.get("app") or "").strip()
    url_val = str(args.get("url") or "").strip()
    contact_val = str(args.get("contact") or "").strip()

    if language == "ru":
        confirm: str | None = None
        if tool_name == "open_app" or tool_name == "activate_app":
            confirm = f"Открыл {name_val}." if name_val else "Открыл приложение."
        elif tool_name == "close_app":
            confirm = f"Закрыл {name_val}." if name_val else "Закрыл приложение."
        elif tool_name == "browser_goto":
            confirm = f"Открыл страницу {url_val}." if url_val else "Открыл страницу в браузере."
        elif tool_name == "safari_goto":
            confirm = f"Открыл {url_val} в Safari." if url_val else "Открыл страницу в Safari."
        elif tool_name == "screenshot":
            confirm = "Сделал снимок экрана."
        elif tool_name == "send_telegram":
            confirm = f"Отправил сообщение в Telegram{(' для ' + contact_val) if contact_val else ''}."
        elif tool_name == "send_whatsapp":
            confirm = f"Отправил сообщение в WhatsApp{(' для ' + contact_val) if contact_val else ''}."
        elif tool_name == "send_email":
            confirm = "Письмо отправлено."
        elif tool_name == "draft_email":
            confirm = "Черновик письма готов."
        elif tool_name == "reply_to_email":
            confirm = "Ответил на письмо."
        elif tool_name == "create_event":
            confirm = f"Создал событие в календаре{(' «' + str(args.get('title', '')) + '»') if args.get('title') else ''}."
        elif tool_name == "update_event":
            confirm = "Обновил событие в календаре."
        elif tool_name == "delete_event":
            confirm = "Удалил событие из календаря."
        elif tool_name == "list_events":
            confirm = "Показал ближайшие события календаря."
        elif tool_name == "create_document":
            confirm = "Создал документ."
        elif tool_name == "create_presentation":
            confirm = "Создал презентацию."
        elif tool_name == "share_document":
            confirm = "Открыл доступ к документу."
        elif tool_name == "search_web":
            confirm = "Поискал в интернете."
        elif tool_name == "save_to_obsidian" or tool_name == "remember":
            confirm = "Записал это в память."
        elif tool_name == "log_daily_activity" or tool_name == "log_activity":
            confirm = "Записал это в дневную активность."
        elif tool_name == "get_daily_summary":
            confirm = "Вот итоги дня."
        elif tool_name == "fol_command":
            confirm = "Выполнил команду."
        elif tool_name == "notify":
            confirm = "Отправил уведомление."
        elif tool_name == "clipboard_set":
            confirm = "Скопировал в буфер обмена."
        elif tool_name == "clipboard_get":
            confirm = "Прочитал буфер обмена."
        elif tool_name == "type_text":
            confirm = "Ввёл текст."
        elif tool_name == "sync_cookies":
            confirm = "Синхронизировал данные браузера."
        elif tool_name in ("list_profiles",):
            confirm = "Вот доступные профили браузера."
        elif tool_name.startswith("render_"):
            confirm = ""
        if confirm is not None:
            return confirm
        # Unknown tool — a NATURAL generic confirmation, never a bare "Готово.".
        return "Действие выполнено. Что-нибудь ещё?"

    # English
    if tool_name == "open_app" or tool_name == "activate_app":
        return f"Opened {name_val}." if name_val else "Opened the app."
    if tool_name == "close_app":
        return f"Closed {name_val}." if name_val else "Closed the app."
    if tool_name == "browser_goto":
        return f"Opened {url_val}." if url_val else "Opened the page."
    if tool_name == "safari_goto":
        return f"Opened {url_val} in Safari." if url_val else "Opened the page in Safari."
    if tool_name == "screenshot":
        return "Screenshot taken."
    if tool_name == "send_telegram":
        return f"Sent the message on Telegram{(' for ' + contact_val) if contact_val else ''}."
    if tool_name == "send_whatsapp":
        return f"Sent the message on WhatsApp{(' for ' + contact_val) if contact_val else ''}."
    if tool_name == "send_email":
        return "Email sent."
    if tool_name == "draft_email":
        return "Draft ready."
    if tool_name == "create_event":
        return "Event created."
    if tool_name == "search_web":
        return "Search complete."
    if tool_name == "save_to_obsidian" or tool_name == "remember":
        return "Saved to memory."
    if tool_name == "log_daily_activity" or tool_name == "log_activity":
        return "Logged it to your daily activity."
    if tool_name == "get_daily_summary":
        return "Here's your daily summary."
    if tool_name == "fol_command":
        return "Command executed."
    if tool_name == "notify":
        return "Notification sent."
    if tool_name == "sync_cookies":
        return "Browser data synced."
    if tool_name.startswith("render_"):
        return ""
    # Unknown tool — a NATURAL generic confirmation, never a bare "Done.".
    return "Action complete. Anything else?"


# ---------------------------------------------------------------------------
# Error humanization — never expose raw JSON or internal messages
# ---------------------------------------------------------------------------

def humanize_error(error: Any, language: str = "ru") -> str:
    """Convert a raw error (dict / JSON string / str) into human text.

    - Dict/JSON errors are mapped to friendly messages by known codes.
    - Plain, already-human sentences pass through untouched (idempotent,
      so the formatter can be applied more than once safely).
    - Raw JSON and internal details are never surfaced.
    """
    data: dict[str, Any]
    orig_msg = ""
    if isinstance(error, dict):
        data = error
        orig_msg = str(data.get("message") or data.get("detail") or data.get("error") or "")
    elif isinstance(error, str):
        stripped = error.strip()
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                data = {"message": stripped}
                orig_msg = stripped
        else:
            data = {"message": stripped}
            orig_msg = stripped
    else:
        data = {"message": str(error)}
        orig_msg = str(error)

    err_code = str(data.get("error", "") or "").lower()
    msg = orig_msg.lower()

    if "google_auth_required" in err_code or "auth_required" in err_code:
        return ("Мне нужен доступ к Google Calendar. Пожалуйста, авторизуйте аккаунт."
                if language == "ru"
                else "I need access to your Google account. Please authorize it.")
    if "oauth" in err_code or "oauth" in msg or "authorize" in msg or "auth missing" in msg:
        return ("Мне нужен доступ к Google Calendar. Пожалуйста, авторизуйте аккаунт."
                if language == "ru"
                else "I need access to your Google Calendar. Please authorize your account.")
    if "rate limit" in msg or "429" in msg:
        return ("Слишком много запросов — подождите немного и попробуйте снова."
                if language == "ru"
                else "Too many requests — please wait a moment and try again.")
    if "unreachable" in err_code or "unreachable" in msg:
        return ("Сейчас не могу связаться со службой. Попробуйте ещё раз через минуту."
                if language == "ru"
                else "I can't reach the service right now. Please try again in a moment.")
    if "timed out" in msg or "timeout" in msg:
        return ("Задача заняла слишком много времени. Попробуйте ещё раз."
                if language == "ru"
                else "That took too long. Please try again.")
    if "unknown tool" in msg:
        return ("Не смог выполнить это действие. Попробуйте сформулировать задачу иначе."
                if language == "ru"
                else "I couldn't complete that action. Try rephrasing your request.")
    if "empty command" in msg or ("missing" in msg and "field" in msg):
        return ("Не понял, что нужно сделать — повторите, пожалуйста."
                if language == "ru"
                else "I didn't catch that — could you repeat it?")

    # Already a plain, short, human sentence with no JSON / exception markers?
    # Pass it through — makes sanitization idempotent.
    # NOTE: bare exception class names (ConnectionError, TypeError, KeyError,
    # OSError, ...) and their messages must NOT pass through — raw exception
    # text never reaches the user.
    if (orig_msg and len(orig_msg) < 300
            and not re.search(r"[{\}\n\r]", orig_msg)
            and not re.search(r"(traceback|exception|\berror\b|\w+Error\b|\w+Exception\b|raise |file \"|line \d+)", orig_msg, re.I)):
        return orig_msg.strip()

    # Generic fallback — never dump raw JSON/internal stack traces.
    return ("Что-то пошло не так. Попробуйте ещё раз."
            if language == "ru"
            else "Something went wrong. Please try again.")


# ---------------------------------------------------------------------------
# SSE boundary — one sanitization pass for everything that reaches the UI
# ---------------------------------------------------------------------------

async def sanitize_event_stream(agent_events):
    """Wrap an agent-loop event generator and sanitize everything that
    reaches the user (the SSE boundary in the orchestrator):

      - ``tool_call`` / ``tool_result`` / ``tool_progress`` / ``_tool_use``
        events are dropped — tool calls are internal actions.
      - ``token`` text passes through a ``StreamingTextFilter`` so any JSON
        tool call that slipped through is held back and never shown.
      - ``error`` events are humanized (never raw JSON).
      - ``component`` / ``state`` / ``activity`` pass through unchanged.

    Yields (event_type, event_data) tuples safe to serialize to the UI.
    """
    token_filter = StreamingTextFilter()
    async for event_type, event_data in agent_events:
        if event_type in ("tool_call", "tool_result", "tool_progress", "_tool_use"):
            continue
        if event_type == "token":
            safe = token_filter.process(event_data.get("text", ""))
            if safe:
                yield ("token", {"text": safe})
            continue
        if event_type == "error":
            yield ("error", {"message": humanize_error(event_data)})
            continue
        yield (event_type, event_data)
    tail = token_filter.flush()
    if tail:
        yield ("token", {"text": tail})


# ---------------------------------------------------------------------------
# Final response — always a plain, non-empty string
# ---------------------------------------------------------------------------

# Bare confirmations that must NEVER be the user-facing final answer
# (they are tool/API state, not a response).
_TERSE_FINALS = frozenset({
    "done", "ok", "okay", "готово", "выполнено", "сделано", "принято",
    "успешно", "completed", "task completed", "success", "успех", "есть",
    "ок", "сделал", "выполнил", "всё", "все", "yes", "sure", "fine",
    "sir", "сэр", "madam", "мадам",
})


def _is_bare_confirmation(text: str) -> bool:
    """True when ``text`` is a bare confirmation like "Done." / "Готово."."""
    t = (text or "").strip()
    # A redacted API key marker is invisible for the check: "Done. <ключ
    # скрыт>" is still the bare confirmation "Done.".
    t = t.replace("<ключ скрыт>", "").replace("<redacted>", "")
    t = t.strip().rstrip(".!").strip().lower()
    if t in _TERSE_FINALS:
        return True
    t2 = re.sub(r"[\s,]+(?:sir|сэр)\s*$", "", t).strip().rstrip(".!").strip()
    return bool(t2) and t2 in _TERSE_FINALS


def _strip_json_fence(text: str) -> str:
    """Remove a ```json ... ``` fence so the payload can be inspected."""
    t = (text or "").strip()
    t = re.sub(r"^`{3}(?:json)?\s*", "", t)
    t = re.sub(r"`{3}\s*$", "", t)
    return t.strip()


def _looks_like_status_payload(text: str) -> bool:
    """True when ``text`` is a bare JSON status/error payload (fenced or not)."""
    t = _strip_json_fence(text)
    if not t.startswith("{"):
        return False
    json_str, _ = _first_balanced_json(t)
    if json_str is None:
        return False
    try:
        obj = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(obj, dict):
        return False
    if any(k in obj for k in ("name", "tool", "action", "thought")):
        return False
    return any(k in obj for k in ("status", "success", "ok", "result", "error", "detail", "message"))


def _extract_status_result(text: str) -> str | None:
    """Extract a meaningful natural-language field from a JSON status payload
    so its information is preserved instead of being discarded."""
    t = _strip_json_fence(text)
    if not t.startswith("{"):
        return None
    json_str, _ = _first_balanced_json(t)
    if json_str is None:
        return None
    try:
        obj = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    for key in ("result", "message", "text", "output"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip() and not _is_bare_confirmation(value):
            return value.strip()
    return None


def _strip_honorific(text: str) -> str:
    """Remove a trailing robotic honorific ("X, sir." / "X, сэр.") while
    keeping the sentence punctuation."""
    t = (text or "").strip()
    t2 = re.sub(r"[\s,]+(?:sir|сэр)\s*[.!]?\s*$", "", t, flags=re.IGNORECASE).strip()
    if t2 and t2 != t:
        if t2[-1] not in ".!?":
            t2 += "."
        return t2
    return t


# ---------------------------------------------------------------------------
# API-key redaction + non-requested code fences — never show secrets or raw
# implementation code as the final answer (stress-test findings #2/#3).
# ---------------------------------------------------------------------------

# OpenRouter (sk-or-v1-...) / OpenAI (sk-proj-...) style keys.
_API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")


def redact_api_keys(text: str) -> str:
    """Replace any API key that slipped into a response with a placeholder."""
    return _API_KEY_RE.sub("<ключ скрыт>", text)


_CODE_FENCE_RE = re.compile(r"```(?!json\b)[a-zA-Z0-9_+\-]*\s*(.*?)```", re.DOTALL)

_CODE_REQUEST_SIGNALS = (
    "код", "code", "скрипт", "script", "python", "swift", "bash",
    "javascript", "typescript", "html", "css", "sql", "regex",
    "алгоритм", "algorithm", "функцию", "function", "класс", "class",
    "api", "приложение", "app for", "напиши программу", "write a program",
)


def _user_wants_code(user_input: str) -> bool:
    lower = (user_input or "").lower()
    return any(signal in lower for signal in _CODE_REQUEST_SIGNALS)


def strip_code_fences(text: str, user_input: str = "") -> str:
    """Remove fenced code blocks (```lang ... ```) unless the user asked for
    code. Raw applescript/shell snippets are implementation detail."""
    if not text or _user_wants_code(user_input):
        return text
    cleaned = _CODE_FENCE_RE.sub("", text)
    return re.sub(r"```\s*```", "", cleaned).strip()


# ---------------------------------------------------------------------------
# LLM-unavailable / raw-error detection — technical state never reaches the
# user as the final answer ("All LLM backends are unavailable...",
# "Error: ...", "Failed to ...")
# ---------------------------------------------------------------------------

_LLM_UNAVAILABLE_MARKERS = (
    "all llm backends are unavailable", "configure an api key", "install mlx-lm",
    "configure an llm", "configure llm", "настройте llm", "настройте llm для полного ответа",
    "все llm-бэкенды недоступны", "ни один llm-бэкенд не доступен", "недоступны все llm",
)


def _is_llm_unavailable_text(text: str) -> bool:
    """True when ``text`` is an engine graceful-failure message (LLM backends
    all down / unconfigured). Technical state — never shown verbatim."""
    t = (text or "").strip().lower()
    return any(marker in t for marker in _LLM_UNAVAILABLE_MARKERS)


def _looks_like_error_text(text: str) -> bool:
    """True when ``text`` looks like a raw error sentence that must be
    humanized before reaching the user."""
    t = (text or "").strip().lower()
    return (
        t.startswith("error:")
        or t.startswith("ошибка:")
        or t.startswith("failed to")
        or t.startswith("не удалось")
        or re.search(r"(traceback|exception|\w+error\b|\w+exception\b|raise |file \"|line \d+)", t) is not None
    )


def _natural_final_fallback(language: str) -> str:
    """A natural, non-terse final fallback when nothing else produced text."""
    return (
        "Сделано. Могу помочь с чем-то ещё?"
        if language == "ru"
        else "All set. Anything else I can help with?"
    )


def format_final_response(
    text: str | None,
    executed_tools: list[tuple[str, dict[str, Any]]] | None = None,
    language: str = "ru",
    user_input: str | None = None,
) -> str:
    """Produce the user-facing final answer — the orchestrator's Final
    Response Layer.

    1. Strip any tool-call JSON from the model's text.
    2. Redact API keys and strip non-requested code fences.
    3. A bare confirmation ("Done.", "Готово.", "OK.", "Готово, сэр.") is
       never shown — if the tools that ran can explain the outcome, rebuild
       a natural confirmation from them.
    4. If nothing usable remains, return a natural non-terse fallback.
    5. Guaranteed to return a non-empty, non-terse plain string.
    """
    clean = strip_tool_call_json(text or "").strip()
    # Secrets and implementation code never reach the user.
    clean = redact_api_keys(clean)
    clean = strip_code_fences(clean, user_input or "")
    # Robotic honorifics ("X, sir." / "X, сэр.") are never part of the answer.
    clean = _strip_honorific(clean)
    # A JSON status/error payload ({"status": "ok"} / {"error": ...}) is
    # internal state — keep any useful natural-language field, otherwise
    # humanize/rebuild. Raw JSON never reaches the user.
    if _looks_like_status_payload(clean):
        payload_result = _extract_status_result(clean)
        if payload_result:
            return redact_api_keys(strip_code_fences(payload_result, user_input or ""))
        return humanize_error(clean, language)
    # Raw error sentences ("Error: ...", "Failed to ...", tracebacks) are
    # humanized, never shown verbatim.
    if _looks_like_error_text(clean):
        return humanize_error(clean, language)
    # Engine graceful-failure messages ("All LLM backends are unavailable...")
    # are technical state — replace with a friendly message.
    if _is_llm_unavailable_text(clean):
        return (
            "Сейчас не могу сформулировать полный ответ — сервис временно недоступен. Попробуйте ещё раз через минуту."
            if language == "ru"
            else "I can't give a full answer right now — the service is temporarily unavailable. Please try again in a minute."
        )
    if clean and not _is_bare_confirmation(clean):
        return clean

    for tool_name, args in reversed(list(executed_tools or [])):
        if tool_name.startswith("render_"):
            continue
        confirm = humanize_tool_call(tool_name, args, language)
        if confirm and not _is_bare_confirmation(confirm):
            return confirm
    return _natural_final_fallback(language)
