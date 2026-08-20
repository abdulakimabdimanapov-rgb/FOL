"""FOL Personality Layer — the final-response layer of the FOL engine.

FOL's raw outputs (from small local LLMs or from tools) are often terse and
robotic: ``Done.``, ``Готово.``, ``OK``, ``Выполнено``, ``Task completed.``.
This module sits between the agent/LLM/tools and the user and makes FOL sound
like a natural, JARVIS-like personal assistant instead of an API.

Pipeline:

    User → Agent/Tools → Tool Result → Personality Layer → SwiftUI/API

Rules enforced here (same contract as the orchestrator's response formatter):

  - Never expose tool calls, JSON structures, reasoning, debug information.
  - A bare confirmation ("Done.", "Готово.") is replaced with a natural,
    contextual response that describes what actually happened.
  - Errors are converted to friendly human text (never tracebacks).
  - The response language follows the user's language (RU/EN).
  - Genuine natural-language answers pass through untouched.

The personality system prompt (``FOL_PERSONALITY_SYSTEM_PROMPT``) is appended
to every LLM call in the engine, so the behaviour holds regardless of which
agent/prompt is active.
"""

from __future__ import annotations

import json
import re
from typing import Any

from modules.llm.language import detect_language

# ---------------------------------------------------------------------------
# Personality system prompt (section 14 of the spec)
# ---------------------------------------------------------------------------

FOL_PERSONALITY_SYSTEM_PROMPT = """\
## Personality (MANDATORY)
FOL is a personal AI assistant.
He communicates naturally and conversationally.
He is intelligent, calm, confident, friendly and occasionally humorous.
He behaves like a capable personal companion rather than an API.
He never exposes internal tool calls, JSON, reasoning, debug information or implementation details.
After completing an action, he gives a natural contextual response describing what actually happened.
For simple actions, keep responses concise. For conversations, behave naturally and engage with the user.
Use light humor when appropriate. Do not overuse JARVIS phrases or honorifics.
Always prioritize usefulness and context.
Never answer with a bare "Done.", "Готово.", "OK.", "Выполнено." or "Task completed." — describe the outcome instead.
Never respond with a generic offer of help ("How can I help you?", "Чем могу помочь?", "I'm here to help.") unless the user just greeted you.
When the user asks a concrete question, answer it DIRECTLY with a concrete, useful answer in the user's language.
Do not greet, do not ask what the user needs, and do not offer help before answering.
If you genuinely cannot answer, say so honestly and offer to search the web or check memory — never deflect with a generic greeting.
Keep answers concise: 2-4 sentences for simple questions, never repeat the same sentence twice.
"""

# ---------------------------------------------------------------------------
# Terse / robotic response detection
# ---------------------------------------------------------------------------

_TERSE_RESPONSES = frozenset({
    "done", "ok", "okay", "готово", "выполнено", "сделано", "принято",
    "успешно", "completed", "task completed", "done!", "yes", "sure", "fine",
    "success", "успех", "есть", "сделал", "ок",
    "всё", "все", "all done", "готово!", "сделано!", "muted", "unmuted",
    "yes sir", "ok sir", "done sir", "ок сэр", "готово сэр", "выполнил",
    "sir", "сэр", "madam", "мадам",
})


def is_terse_response(text: str) -> bool:
    """True if ``text`` is a bare confirmation like "Done." / "Готово."."""
    t = (text or "").strip()
    # A redacted API key marker is invisible for the check: "Done. <ключ
    # скрыт>" is still the bare confirmation "Done.".
    t = t.replace("<ключ скрыт>", "").replace("<redacted>", "")
    t = t.strip().rstrip(".!").strip().lower()
    if t in _TERSE_RESPONSES:
        return True
    # Robotic honorifics: "Done, sir." / "Готово, сэр." are still terse.
    t2 = re.sub(r"[\s,]+(?:sir|сэр)\s*$", "", t).strip().rstrip(".!").strip()
    return bool(t2) and t2 in _TERSE_RESPONSES


# ---------------------------------------------------------------------------
# Response classification (spec section 13)
# ---------------------------------------------------------------------------


class ResponseCategory:
    """Classification of what the user's request was about, used to shape the
    final answer (ACTION_SUCCESS / INFORMATION / QUESTION / CLARIFICATION /
    ERROR / MEMORY / SEARCH_RESULT / MULTI_STEP_RESULT / CASUAL_CONVERSATION)."""

    ACTION_SUCCESS = "ACTION_SUCCESS"
    INFORMATION = "INFORMATION"
    QUESTION = "QUESTION"
    CLARIFICATION = "CLARIFICATION"
    ERROR = "ERROR"
    MEMORY = "MEMORY"
    SEARCH_RESULT = "SEARCH_RESULT"
    MULTI_STEP_RESULT = "MULTI_STEP_RESULT"
    CASUAL_CONVERSATION = "CASUAL_CONVERSATION"


# Tool names that are memory-related → the answer should confirm the save.
_MEMORY_TOOLS = {"save_to_obsidian", "remember", "store_memory", "save_note", "write_note"}
_SEARCH_TOOLS = {"search_web", "tavily_search", "browser_search", "web_search", "google_search"}
_CLARIFY_TOOLS = {"email_tool", "calendar_tool", "create_calendar_event", "send_email"}


def classify_response(
    user_input: str,
    raw_response: str = "",
    tool_name: str | None = None,
    tool_args: dict[str, Any] | None = None,
    language: str | None = None,
) -> str:
    """Classify the outcome before the final answer is shaped.

    Returns one of :class:`ResponseCategory`. Order matters: an error always
    wins; a known tool then refines to MEMORY / SEARCH_RESULT / ACTION_SUCCESS;
    otherwise the intent words in the user input decide (CLARIFICATION for
    missing info, CASUAL_CONVERSATION for greetings, etc.).
    """
    language = language or detect_language(user_input)
    lower = (user_input or "").lower().strip()

    if _looks_like_error(raw_response):
        return ResponseCategory.ERROR
    if tool_name:
        if tool_name in _MEMORY_TOOLS:
            return ResponseCategory.MEMORY
        if tool_name in _SEARCH_TOOLS:
            return ResponseCategory.SEARCH_RESULT
        if tool_name in _CLARIFY_TOOLS:
            return ResponseCategory.CLARIFICATION
        return ResponseCategory.ACTION_SUCCESS

    # Intent-based fallback when no tool is known
    if re.search(
        r"\b(привет|здравствуй|добрый день|hi|hello|hey|good morning)\b", lower
    ) or re.search(r"\b(как дела|how are you|how's it going|мне скучно|i'm bored)\b", lower):
        return ResponseCategory.CASUAL_CONVERSATION
    if re.search(
        r"\b(remember|запомни|сохрани|save|не забудь)\b", lower
    ):
        return ResponseCategory.MEMORY
    if re.search(
        r"\b(search|найди|поищи|ищи|загугли|google|find)\b", lower
    ):
        return ResponseCategory.SEARCH_RESULT
    if re.search(
        r"\b(email|письмо|напиши письмо|calendar|событие|встречу|create event)\b", lower
    ):
        return ResponseCategory.CLARIFICATION
    # Informational requests ("объясни", "расскажи", "explain", "tell me")
    # take priority over a question word that appears inside them.
    if re.search(
        r"\b(объясни|расскажи|объяснить|explain|tell me about|что значит|как работает|how does)\b",
        lower,
    ):
        return ResponseCategory.INFORMATION
    if lower.endswith("?") or re.search(r"\b(кто|что|как|почему|зачем|где|какой|какая|когда|which|what|how|why|where)\b", lower):
        return ResponseCategory.QUESTION
    if re.search(r"\b(открой|open|запусти|launch|сделай|create|напиши код|write code|включи)\b", lower):
        return ResponseCategory.ACTION_SUCCESS
    return ResponseCategory.INFORMATION


_ROBOTIC_PATTERNS = (
    # "Opening Safari, sir." / "Opening YouTube: ..." — always English, robotic
    re.compile(r"^opening\s+.+?(?:,\s*sir\.?|:.*)?$", re.IGNORECASE),
    # FOL internal-style Mac control outputs (always English, robotic)
    re.compile(r"^media:\s+.*", re.IGNORECASE),            # "Media: play, sir."
    re.compile(r"^volume:.*", re.IGNORECASE),              # "Volume: 30%, sir."
    re.compile(r"^brightness\s+(?:increased|decreased).*", re.IGNORECASE),
    re.compile(r"^window\s+\w+,?.*", re.IGNORECASE),      # "Window minimize, sir."
    re.compile(r"^(going to sleep|screen locked|waking up),?\s*sir\.?", re.IGNORECASE),
    re.compile(r"^playing music:.*", re.IGNORECASE),       # "Playing music: X, sir."
    re.compile(r"^opening youtube.*", re.IGNORECASE),      # "Opening YouTube, sir."
    re.compile(r"^(muted|unmuted),?\s*sir\.?", re.IGNORECASE),
)


def _is_robotic_confirmation(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(p.match(t) for p in _ROBOTIC_PATTERNS)


# ---------------------------------------------------------------------------
# Generic offer-of-help detection — small local models default to
# "How can I help you?" / "Чем могу помочь?" instead of answering a concrete
# question. That is a greeting-like non-answer and must never be the final
# response to a real question.
# ---------------------------------------------------------------------------

_GREETING_WORDS_RE = re.compile(
    r"\b(hi|hello|hey|yo|howdy|good (?:morning|afternoon|evening)|good night|"
    r"привет|здравствуй|здравствуйте|добрый (?:день|вечер|утро)|доброе утро|доброй ночи)\b",
    re.IGNORECASE,
)

# A response that is (optional greeting +) essentially ONLY a generic offer
# of help. The offer phrase must dominate: anything substantive around it
# makes the response a real answer and it passes through untouched.
_GENERIC_HELP_OFFER_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"(?:hi|hello|hey|yo|howdy|good (?:morning|afternoon|evening)|good night|"
    r"привет|здравствуй(?:те)?|добрый (?:день|вечер|утро)|доброе утро|доброй ночи)"
    r"[,.!\s]+"
    r")?"
    r"(?:"
    r"how (?:can|may) i (?:help|assist) you"
    r"|how can i be of assistance"
    r"|what can i (?:help you with|do for you|do to help)"
    r"|what do you (?:need|want) (?:help with|me to do)"
    r"|what would you like (?:me to do|to do)"
    r"|is there anything (?:else )?i can (?:help you with|do for you)"
    r"|let me know (?:how i can help|what you need|if you need anything)"
    r"|i'?m here to help"
    r"|i am here to help"
    r"|how may i (?:help|assist) you today"
    r"|чем (?:я )?могу (?:помочь|быть полезен|быть полезна|быть полезным)"
    r"|чем (?:вам|тебе) помочь"
    r"|чем помочь"
    r"|как (?:я )?могу помочь"
    r"|что (?:я )?могу (?:сделать для вас|сделать для тебя|для вас сделать)"
    r"|скажите?,? чем помочь"
    r"|я здесь,? чтобы помочь"
    r")"
    r"(?:\s*(?:today|now|please|сегодня|сейчас|пожалуйста))?"
    r"[\s.,!?;:)…-]*$",
    re.IGNORECASE,
)


def _is_generic_help_offer(text: str) -> bool:
    """True when ``text`` is essentially only a generic offer of help
    ("How can I help you?" / "Чем могу помочь?", optionally wrapped in a
    greeting). Small local models produce these instead of answering.
    """
    t = (text or "").strip()
    if not t or len(t) > 220:
        # Long responses that merely mention help are real answers.
        return False
    # Models sometimes stutter the same offer twice — treat as one offer.
    t = dedupe_repeated_sentences(t)
    # Trailing emoji ("...today? 😊") must not break the anchor.
    t = re.sub(r"[\W_]+$", "", t)
    return _GENERIC_HELP_OFFER_RE.match(t) is not None


_COMMAND_VERBS = frozenset({
    "открой", "откройте", "запусти", "запустите", "сделай", "сделайте",
    "найди", "найти", "поищи", "напиши", "написать", "создай", "покажи",
    "включи", "выключи", "скажи", "расскажи", "запомни", "сохрани",
    "open", "launch", "start", "run", "find", "search", "write", "create",
    "show", "play", "tell", "remember", "save", "screenshot", "open",
})


def _is_pure_greeting(user_input: str) -> bool:
    """True when the user's message is just a greeting / small talk (no real
    question or command), so a greeting-like response is acceptable."""
    t = (user_input or "").strip().strip(".,!?")
    if not _GREETING_WORDS_RE.search(t.lower()):
        return False
    words = [w for w in re.findall(r"[a-zа-яё]{2,}", t.lower())
             if w not in ("пожалуйста", "please", "there", "fol", "сэр", "sir")]
    # A greeting + a command is a real request ("Привет, открой Safari").
    if any(w in t.lower() for w in _COMMAND_VERBS):
        return False
    # A greeting + a question word / question mark is a real request.
    if "?" in t or any(w in t.lower() for w in ("что", "как", "какой", "какая", "which",
                                                "what", "how", "when", "where", "why", "who")):
        return len(words) <= 2
    return len(words) <= 3


_CAPABILITY_QUESTIONS_RE = re.compile(
    r"\b(?:what can you do|what do you do|what are you (?:able|capable) to do|"
    r"what are your capabilities|what features do you have|what can you help with|"
    r"what do you offer|what should i ask you|"
    r"что ты умеешь|что ты можешь|что умеешь|на что ты способен|что ты делаешь|"
    r"чем можешь помочь|чем можешь быть полезен|что вы умеете)\b",
    re.IGNORECASE,
)


def _user_asks_capabilities(user_input: str) -> bool:
    """True when the user asked what FOL can do — a capabilities answer is the
    legitimate response, so a help-offer-shaped answer is allowed there."""
    return bool(_CAPABILITY_QUESTIONS_RE.search(user_input or ""))


def _generic_help_replacement(user_input: str, language: str | None = None) -> str:
    """Honest replacement when the model answered a concrete question with a
    generic offer of help: never hallucinate an answer, explain the limit and
    offer the concrete things FOL can actually do (requirement: "If the model
    genuinely cannot answer, explain why")."""
    language = language or detect_language(user_input)
    ru = language == "ru"
    lower = (user_input or "").lower()

    # Small talk still gets a natural companion reply (never a help offer).
    if re.search(r"\b(how are you|how's it going|how are things|как дела|как ты|как настроение|что нового)\b", lower):
        return (
            "В полном порядке. Сервисы работают, инструменты на месте. Могу помочь "
            "с кодом, браузером или просто составить компанию."
            if ru
            else "All good. Services are running, tools are ready. Happy to help "
            "with code, the browser, or just keep you company."
        )
    if re.search(r"\b(who are you|what are you|кто ты|что ты такое|ты кто)\b", lower):
        return (
            "Я FOL, твой персональный ассистент. Могу работать с компьютером, искать "
            "информацию, помнить важные вещи и помогать с проектами."
            if ru
            else "I'm FOL, your personal assistant. I can work with the computer, "
            "find information, remember important things, and help with projects."
        )
    if re.search(r"\b(thank|спасибо|благодарю)\b", lower):
        return "Всегда пожалуйста. Это моя работа." if ru else "You're welcome. It's what I'm here for."
    if ru:
        return (
            "Хороший вопрос. Прямого ответа у меня сейчас нет — могу поискать это "
            "в интернете, проверить память или открыть нужное приложение. Что сделать?"
        )
    return (
        "Good question. I don't have a direct answer right now, but I can search the "
        "web, check memory, or open what you need. What should I do?"
    )


# ---------------------------------------------------------------------------
# Tool-call JSON detection / stripping (compact port of the orchestrator's
# response formatter so FOL stays self-contained)
# ---------------------------------------------------------------------------

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


def _extract_tool_call(text: str) -> tuple[str, dict[str, Any]] | None:
    """Try to parse a tool call that a model emitted as plain JSON text."""
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

    obj_type = obj.get("type")
    if isinstance(obj_type, str) and obj_type not in _TOOL_CALL_TYPE_VALUES:
        return None

    name = obj.get("name")
    if isinstance(name, dict):  # OpenAI: {"function": {"name": ...}}
        name = name.get("name")
    if not name:
        name = obj.get("action")
    if not name:
        function = obj.get("function")
        if isinstance(function, dict):
            name = function.get("name")
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name or not name.replace("_", "").isalnum():
        return None

    args: dict[str, Any] | None = None
    for key in ("arguments", "parameters", "input", "params"):
        a = obj.get(key)
        if a is None and isinstance(obj.get("function"), dict):
            a = obj["function"].get(key)
        if a is None:
            continue
        if isinstance(a, str):
            try:
                a = json.loads(a)
            except (json.JSONDecodeError, ValueError):
                return None
        if isinstance(a, dict):
            args = a
            break
    if args is None:
        return None
    return name, args


# XML tool calls — some models emit FOL/Anthropic-style XML
# (``<invoke>...</invoke>`` or a bare ``<tool>...</tool>`` + params) as plain
# text instead of a structured call. That is internal, never user-facing.
_XML_TOOL_CALL_RE = re.compile(
    r"<invoke>.*?</invoke>"
    r"|(?:<tool>\s*[\w\-]+\s*</tool>\s*"
    r"(?:<param\b[^>]*>(?:[^<]*</param>)?\s*)*)"
    r"(?:\s*</invoke>)?",
    re.DOTALL | re.IGNORECASE,
)


def strip_tool_call_xml(text: str) -> str:
    """Remove XML tool calls (complete ``<invoke>...</invoke>`` blocks, or the
    bare ``<tool>...</tool>`` + ``<param ...>...</param>`` sequence a model
    emitted as plain text). Natural prose around the block is preserved.
    """
    if not text:
        return text
    cleaned = _XML_TOOL_CALL_RE.sub("", text)
    # Dangling closing tag when the model omitted the opening <invoke>.
    cleaned = re.sub(r"\s*</invoke>\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
    return cleaned.strip()


def strip_tool_call_json(text: str) -> str:
    """Remove embedded tool-call JSON (bare or fenced) from a text string."""
    if not text:
        return text

    def _drop_fence(match: re.Match) -> str:
        block = match.group(1)
        return "" if _extract_tool_call(block) is not None else match.group(0)

    text = re.sub(r"```(?:json)?\s*(.*?)```", _drop_fence, text, flags=re.DOTALL)

    while True:
        json_str, end = _first_balanced_json(text)
        if json_str is None:
            break
        if _extract_tool_call(json_str) is not None:
            rest = text[end:]
            m = re.match(r"^[.,!;:]+", rest)
            if m:
                end += m.end()
            text = text[: text.find(json_str)] + text[end:]
        else:
            break

    text = re.sub(r"```json\s*```", "", text)
    text = re.sub(r"```\s*```", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Intent → natural contextual confirmation
# ---------------------------------------------------------------------------


def _title(word: str) -> str:
    """Capitalize the first letter of a name, keep the rest as-is."""
    word = word.strip()
    if not word:
        return word
    return word[0].upper() + word[1:]


def contextual_confirmation(
    user_input: str,
    tool_name: str | None = None,
    tool_args: dict[str, Any] | None = None,
    language: str | None = None,
) -> str:
    """Build a natural, contextual response for the user's request.

    Called when the raw answer is missing, terse or robotic. Derives the
    outcome from the user's intent (and the executed tool when known) and
    mirrors the spec's examples:

      "Открой Safari"          → "Safari открыт. Куда направляемся?"
      "Открой YouTube"         → "YouTube открыт. Похоже, сегодня продуктивность
                                 решила сделать небольшой перерыв. 😄"
      "Запомни, что завтра ..." → "Запомнил. Завтра нужно отправить отчёт."
      "Создай событие на завтра" → "Конечно. Во сколько поставить событие?"
    """
    language = language or detect_language(user_input)
    ru = language == "ru"
    lower = (user_input or "").lower()

    # 1. Greetings — pure conversation, no tools needed
    if re.search(
        r"\b(привет|здравствуй|добрый день|доброе утро|добрый вечер|доброй ночи|"
        r"hi|hello|hey|good morning|good afternoon|good evening)\b",
        lower,
    ):
        return (
            "Привет! Рад тебя видеть. Чем займёмся?"
            if ru
            else "Hi! Great to see you. What shall we do?"
        )

    # 1b. Small talk — the assistant engages like a companion
    if re.search(r"\b(how are you|how's it going|как дела|как ты|как настроение|что нового)\b", lower):
        return (
            "В полном порядке. Сервисы работают, инструменты на месте. Могу помочь "
            "с кодом, браузером или просто составить компанию."
            if ru
            else "All good. Services are running, tools are ready. Happy to help "
            "with code, the browser, or just keep you company."
        )
    if re.search(r"\b(я скучаю|мне скучно|скучно|i'm bored|i am bored|bored)\b", lower):
        return (
            "Тогда это уже чрезвычайная ситуация. 😄\nМожем что-нибудь построить, "
            "разобраться с кодом или придумать новый эксперимент."
            if ru
            else "Now that's an emergency. 😄\nWe could build something, dig into "
            "code, or come up with a new experiment."
        )
    if re.search(r"\b(who are you|what are you|кто ты|что ты такое|ты кто)\b", lower):
        return (
            "Я FOL, твой персональный ассистент. Могу работать с компьютером, искать "
            "информацию, помнить важные вещи и помогать с проектами."
            if ru
            else "I'm FOL, your personal assistant. I can work with the computer, "
            "find information, remember important things, and help with projects."
        )

    # 2. YouTube — the classic productivity-break joke
    if re.search(r"\b(youtube|ютуб|ютьюб)\b", lower):
        return (
            "YouTube открыт. Похоже, сегодня продуктивность решила сделать "
            "небольшой перерыв. 😄"
            if ru
            else "YouTube is up. Looks like productivity decided to take a "
            "small break today. 😄"
        )

    # 3. Open a project ("Открой мой проект FOL") — capture the name
    #    from the ORIGINAL text so its casing is preserved.
    proj = re.search(
        r"\b(?:open|открой|откройте|запусти)\b.*?\b(?:проект|project)\s+(.+?)\s*$",
        user_input,
        re.IGNORECASE,
    )
    if proj:
        name = proj.group(1).strip()
        if name:
            return (
                f"Нашёл проект {_title(name)} и открыл его."
                if ru
                else f"Found the project {_title(name)} and opened it."
            )

    # 4. Open a file
    if re.search(r"\b(?:open file|открой файл|покажи файл|open|открой)\b.*\b(?:файл|file)\b", lower):
        return "Открыл файл." if ru else "Opened the file."

    # 5. Open an app ("Открой Safari", "open Safari") — capture from the
    #    ORIGINAL text so the app name keeps its casing.
    app = re.search(
        r"\b(?:open|открой|откройте|запусти|запустите|launch|start|открой приложение|run app)\s+(.+?)\s*$",
        user_input,
        re.IGNORECASE,
    )
    if app:
        name = app.group(1).strip()
        # Strip a trailing compound intent: "Открой Safari и найди новости"
        # must confirm just Safari, not "Safari и найди новости об OpenAI".
        name = re.split(r"\s+(?:и|и\s+затем|and|then)\s+", name, maxsplit=1)[0].strip()
        # Ignore trailing noise ("пожалуйста", "please", "app", "приложение")
        name = re.sub(
            r"\s*(пожалуйста|please|app|приложение|сейчас|now)$", "", name
        ).strip()
        # Ignore trailing punctuation: "Открой Safari." → Safari (not "Safari.").
        name = re.sub(r"[.!?\s]+$", "", name)
        if name and name not in ("этот сайт", "this site", "that site"):
            # Plain confirmation — no artificial question after every action.
            # (Spec: "Terminal открыт." is enough; don't force a follow-up.)
            return (
                f"{_title(name)} открыт."
                if ru
                else f"{_title(name)} is open."
            )

    # 6. Remember something ("Запомни, что завтра нужно отправить отчёт")
    rem = re.search(
        r"\b(?:remember|запомни|запомни что|запомни, что|не забудь|запомни навсегда)\b\s*(.*)$",
        user_input,
        re.IGNORECASE,
    )
    if rem:
        what = rem.group(1).strip().lstrip(",.:;")
        # Drop a leading "что" / "that" filler for a natural confirmation
        what = re.sub(r"^[\s,.:;]*(?:что|that)\s+", "", what, flags=re.IGNORECASE).strip()
        if what:
            return (
                f"Запомнил. {_title(what)}"
                if ru
                else f"Got it. I'll remember: {_title(what)}"
            )
        return "Запомнил." if ru else "Remembered."

    # 7. Calendar event — ask for details instead of guessing
    if re.search(
        r"\b(create event|add event|создай событие|добавь событие|создай встречу|"
        r"поставь напоминание|create a calendar|добавь в календарь)\b",
        lower,
    ):
        return (
            "Конечно. Во сколько поставить событие?"
            if ru
            else "Of course. What time should I set it for?"
        )

    # 8. Search the web
    search = re.search(
        r"\b(?:search|найди|найти|поищи|загугли|google|ищи)\b\s*(.*)$",
        lower,
    )
    if search:
        query = search.group(1).strip()
        if query:
            return (
                f"Нашёл результаты по запросу «{_title(query)}»."
                if ru
                else f"Found results for '{query}'."
            )
        return "Нашёл результаты." if ru else "Found results."

    # 9. Save to Obsidian / memory
    if re.search(r"\b(save to vault|save to obsidian|сохрани в vault|сохрани в obsidian|сохрани)\b", lower):
        return "Записал это в память." if ru else "Saved to memory."

    # 10. Screenshot
    if re.search(r"\b(screenshot|скриншот|снимок экрана|сделай скриншот)\b", lower):
        return "Сделал снимок экрана." if ru else "Screenshot taken."

    # 11. Music
    if re.search(r"\b(play music|включи музыку|play song|включи песню|поставь музыку)\b", lower):
        return "Включил музыку. Наслаждайся." if ru else "Music on. Enjoy."

    # 12. Typing text
    if re.search(r"\b(type|введи|набери|введи текст|напиши в поле)\b", lower):
        return "Текст введён." if ru else "Text entered."

    # 13. Fall back on the tool that actually ran (when known)
    if tool_name:
        by_tool = _tool_confirmation(tool_name, tool_args or {}, language)
        if by_tool:
            return by_tool

    # 14. Classified fallback — the response matches what the user asked for.
    #     Never a bare "Готово." / "Принято." / "OK.".
    category = classify_response(user_input, tool_name=tool_name, tool_args=tool_args, language=language)
    if category == ResponseCategory.MEMORY:
        return "Записал это в память." if ru else "Saved it to memory."
    if category == ResponseCategory.SEARCH_RESULT:
        return "Нашёл результаты по вашему запросу." if ru else "Found results for your request."
    if category == ResponseCategory.CLARIFICATION:
        return (
            "Конечно. Уточните, пожалуйста, детали — и я всё сделаю."
            if ru
            else "Sure. Could you give me the details, and I'll take care of it?"
        )
    if category == ResponseCategory.CASUAL_CONVERSATION:
        return (
            "Всегда рад поболтать. Чем займёмся?"
            if ru
            else "Always happy to chat. What shall we do?"
        )
    if category == ResponseCategory.QUESTION:
        return (
            "Хороший вопрос. Могу уточнить по памяти, в браузере или в Obsidian — что предпочитаете?"
            if ru
            else "Good question. I can check memory, the browser, or Obsidian — which would you like?"
        )
    # ACTION_SUCCESS / INFORMATION / MULTI_STEP_RESULT
    return (
        "Сделано. Если нужно, могу дополнить деталями или сделать следующий шаг."
        if ru
        else "Done that. I can add more detail or take the next step if you'd like."
    )


_TOOL_CONFIRMATIONS_RU = {
    "open_app": "Открыл приложение.",
    "browser_open": "Открыл страницу в браузере.",
    "browser_navigate": "Открыл страницу в браузере.",
    "browser_search": "Выполнил поиск в браузере.",
    "browser_click": "Нажал на элемент на странице.",
    "browser_type": "Ввёл текст на странице.",
    "browser_screenshot": "Сделал снимок страницы.",
    "browser_close": "Закрыл браузер.",
    "browser_refresh": "Обновил страницу.",
    "execute_command": "Выполнил команду.",
    "read_file": "Прочитал файл.",
    "write_file": "Записал файл.",
    "search_files": "Нашёл файлы.",
    "system_info": "Вот информация о системе.",
    "desktop_screenshot": "Сделал снимок экрана.",
    "web_scraper": "Загрузил содержимое страницы.",
    "type_text": "Ввёл текст.",
    "press_key": "Нажал клавишу.",
    "click": "Выполнил клик.",
    "write_clipboard": "Скопировал в буфер обмена.",
    "read_clipboard": "Прочитал буфер обмена.",
    "scheduler_tool": "Добавил задачу в расписание.",
    "email_tool": "Работаю с почтой.",
    "calendar_tool": "Работаю с календарём.",
}

_TOOL_CONFIRMATIONS_EN = {
    "open_app": "Opened the app.",
    "browser_open": "Opened the page in the browser.",
    "browser_navigate": "Opened the page in the browser.",
    "browser_search": "Searched in the browser.",
    "browser_click": "Clicked the element on the page.",
    "browser_type": "Entered the text on the page.",
    "browser_screenshot": "Took a screenshot of the page.",
    "browser_close": "Closed the browser.",
    "browser_refresh": "Refreshed the page.",
    "execute_command": "Command executed.",
    "read_file": "Read the file.",
    "write_file": "Wrote the file.",
    "search_files": "Found the files.",
    "system_info": "Here's the system information.",
    "desktop_screenshot": "Screenshot taken.",
    "web_scraper": "Loaded the page content.",
    "type_text": "Text entered.",
    "press_key": "Key pressed.",
    "click": "Click performed.",
    "write_clipboard": "Copied to the clipboard.",
    "read_clipboard": "Read the clipboard.",
    "scheduler_tool": "Scheduled the task.",
    "email_tool": "Working with your email.",
    "calendar_tool": "Working with your calendar.",
}


def _tool_confirmation(tool_name: str, args: dict[str, Any], language: str) -> str | None:
    """Natural confirmation for a known tool, including key arguments."""
    ru = language == "ru"
    name = str(args.get("name") or args.get("app") or "").strip()
    url = str(args.get("url") or "").strip()

    if tool_name in ("open_app", "activate_app"):
        return (
            (f"Открыл {_title(name)}." if name else "Открыл приложение.")
            if ru
            else (f"Opened {_title(name)}." if name else "Opened the app.")
        )
    if tool_name in ("browser_open", "browser_navigate"):
        return (
            (f"Открыл {url}." if url else "Открыл страницу в браузере.")
            if ru
            else (f"Opened {url}." if url else "Opened the page in the browser.")
        )
    if tool_name == "browser_search":
        query = str(args.get("query") or "").strip()
        return (
            (f"Нашёл результаты по запросу «{_title(query)}»." if query else "Нашёл результаты.")
            if ru
            else (f"Found results for '{query}'." if query else "Found results.")
        )

    table = _TOOL_CONFIRMATIONS_RU if ru else _TOOL_CONFIRMATIONS_EN
    return table.get(tool_name)


# ---------------------------------------------------------------------------
# API-key redaction + non-requested code fences — never show secrets or raw
# implementation code as the final answer (stress-test findings #2/#3).
# ---------------------------------------------------------------------------

# OpenRouter (sk-or-v1-...) / OpenAI (sk-proj-...) / Gemini (AIza...) keys.
_API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b|\bAIza[0-9A-Za-z_\-]{20,}\b")


def redact_api_keys(text: str, language: str | None = None) -> str:
    """Replace any API key that slipped into a response with a placeholder."""
    marker = "<ключ скрыт>" if language != "en" else "<redacted>"
    return _API_KEY_RE.sub(marker, text)


# Any fenced block (including ```json) is implementation detail UNLESS the
# user explicitly asked for code/JSON.
_CODE_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+\-]*\s*(.*?)```", re.DOTALL)

_CODE_REQUEST_SIGNALS = (
    "код", "code", "скрипт", "script", "python", "питон", "swift", "bash",
    "javascript", "typescript", "html", "css", "sql", "regex", "json",
    "алгоритм", "algorithm", "программу", "write a program",
)


def _user_wants_code(user_input: str) -> bool:
    """True when the user explicitly asked for code/scripts/JSON (keep code
    blocks then). Everything else: code fences are implementation detail."""
    lower = (user_input or "").lower()
    return any(signal in lower for signal in _CODE_REQUEST_SIGNALS)


def strip_code_fences(text: str, user_input: str = "") -> str:
    """Remove fenced code blocks (```lang ... ```) unless the user asked for
    code. Raw applescript/shell snippets are implementation detail — they
    never belong in a personal-assistant answer."""
    if not text or _user_wants_code(user_input):
        return text
    cleaned = _CODE_FENCE_RE.sub("", text)
    return re.sub(r"```\s*```", "", cleaned).strip()


# ---------------------------------------------------------------------------
# Internal-state JSON detection — {"status": "ok", ...} must never reach the
# user as a final answer (it is tool/API state, not a response).
# ---------------------------------------------------------------------------


def _strip_json_fence(text: str) -> str:
    """Remove a ```json ... ``` fence so the payload can be inspected."""
    t = (text or "").strip()
    t = re.sub(r"^`{3}(?:json)?\s*", "", t)
    t = re.sub(r"`{3}\s*$", "", t)
    return t.strip()


def _is_status_json_payload(text: str) -> bool:
    """True when ``text`` is (or is dominated by) a JSON status payload such as
    ``{"status": "ok", ...}``, ``{"success": true}`` or ``{"ok": true}``."""
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
    # Status payloads carry a status/success/ok key and no tool name.
    if "name" in obj or "tool" in obj or "action" in obj or "thought" in obj:
        return False
    return "status" in obj or "success" in obj or "ok" in obj or "result" in obj


def _extract_payload_result(text: str) -> str | None:
    """Extract a meaningful natural-language ``result``/``message`` field from a
    JSON status payload, so its information is not lost when we refuse to show
    the raw JSON. Returns ``None`` when the payload carries no useful text."""
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
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and value.get("status"):
            status = value.get("status")
            if isinstance(status, str) and status.strip():
                return status.strip()
    return None


# ---------------------------------------------------------------------------
# Error humanization — never expose tracebacks or raw JSON
# ---------------------------------------------------------------------------

def humanize_error(error: Any, language: str | None = None) -> str:
    """Convert a raw error into a friendly human sentence.

    Order of resolution:
      1. Raw technical markers (traceback, exception types, JSON) → mapped
         to a specific friendly message or a generic fallback.
      2. Known service states (auth, rate limit, timeout, blocked, unknown
         tool) → a specific friendly message.
      3. Already a short plain human sentence → passed through untouched
         (idempotent, so the formatter is safe to apply more than once).
      4. Anything else → a generic friendly fallback.
    """
    language = language or "ru"
    ru = language == "ru"

    msg = error if isinstance(error, str) else str(error)
    msg = re.sub(r"^(error|ошибка|exception)\s*:\s*", "", msg, flags=re.IGNORECASE).strip()
    low = msg.lower()

    has_raw_markers = bool(
        re.search(r"(traceback|exception|typeerror|valueerror|keyerror|connectionerror|"
                  r"oauthexception|raise |file \"|line \d+)", low)
        or "{" in msg
    )

    if has_raw_markers:
        if "oauth" in low or "authorize" in low or "auth" in low or "авториз" in low:
            return (
                "Мне нужен доступ к сервису. Пожалуйста, авторизуйте аккаунт."
                if ru
                else "I need access to the service. Please authorize your account."
            )
        if "rate limit" in low or "429" in low or "лимит" in low:
            return (
                "Слишком много запросов — подождите немного и попробуйте снова."
                if ru
                else "Too many requests — please wait a moment and try again."
            )
        return (
            "Что-то пошло не так. Попробуйте ещё раз."
            if ru
            else "Something went wrong. Please try again."
        )

    # Known service states — always humanized, even without raw markers
    if "oauth" in low or "authorize" in low or "auth missing" in low or "авториз" in low:
        return (
            "Мне нужен доступ к сервису. Пожалуйста, авторизуйте аккаунт."
            if ru
            else "I need access to the service. Please authorize your account."
        )
    if "rate limit" in low or "429" in low or "слишком много запросов" in low:
        return (
            "Слишком много запросов — подождите немного и попробуйте снова."
            if ru
            else "Too many requests — please wait a moment and try again."
        )
    if "timeout" in low or "timed out" in low or "заняло слишком много времени" in low:
        return (
            "Задача заняла слишком много времени. Попробуйте ещё раз."
            if ru
            else "That took too long. Please try again."
        )
    if "command blocked" in low or "заблокирован" in low or "security reason" in low or "безопасност" in low:
        return (
            "Эта команда заблокирована по соображениям безопасности."
            if ru
            else "That command is blocked for security reasons."
        )
    if "unable to open" in low or "не удалось открыть" in low or "unknown tool" in low:
        return (
            "Не удалось выполнить это действие. Проверю ещё раз."
            if ru
            else "I couldn't complete that action. Let me try again."
        )

    # Already a plain human sentence → pass through (idempotent)
    if msg and len(msg) < 300 and not re.search(r"[{}\n\r]", msg):
        return msg
    return (
        "Что-то пошло не так. Попробуйте ещё раз."
        if ru
        else "Something went wrong. Please try again."
    )


def dedupe_repeated_sentences(text: str) -> str:
    """Collapse consecutive repeated sentences ("How can I help you? How can I
    help you?" → one). Small models sometimes stutter the same sentence."""
    if not text:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out: list[str] = []
    for sent in sentences:
        key = sent.strip().lower()
        if out and key == out[-1].strip().lower():
            continue
        out.append(sent)
    return " ".join(out).strip()


# ---------------------------------------------------------------------------
# Main entry — polish a final response
# ---------------------------------------------------------------------------

def _looks_like_error(text: str) -> bool:
    t = (text or "").strip()
    return (
        t.lower().startswith("error:")
        or t.lower().startswith("ошибка:")
        or t.lower().startswith("failed to")
        or t.lower().startswith("не удалось")
        or re.search(r"(traceback|exception|oauthexception|connectionerror|typeerror)",
                     t, re.IGNORECASE) is not None
        # JSON error payloads ({"error": ...}) are internal state — the
        # user gets a humanized sentence instead of raw JSON.
        or (t.startswith("{") and '"error"' in t[:200])
    )


_LLM_UNAVAILABLE_MARKERS = (
    "настройте llm", "configure an llm", "configure llm",
    "настройте llm для полного ответа", "i understand you're asking about",
    "я понимаю, вы спрашиваете о",
    # Engine graceful failure messages — technical state must never reach
    # the user as the final answer.
    "all llm backends are unavailable", "install mlx-lm",
    "все llm-бэкенды недоступны", "ни один llm-бэкенд не доступен",
    "недоступны все llm",
)


def _is_llm_unavailable_fallback(text: str) -> bool:
    """True if the answer is FOL's rule-based fallback used when the LLM
    backend is unavailable (e.g. no API credits). It is not a real answer
    and should be replaced with a natural contextual confirmation.

    ``"configure an api key"`` alone is NOT a marker (a legitimate answer
    like "I can help you configure an API key" must pass through) — the
    engine's graceful-failure signature is "unavailable" TOGETHER with
    config/mlx-lm talk in the same message."""
    t = (text or "").strip().lower()
    if any(marker in t for marker in _LLM_UNAVAILABLE_MARKERS):
        return True
    return "unavailable" in t and ("api key" in t or "mlx-lm" in t or "бэкенд" in t)


def polish_response(
    user_input: str,
    raw_response: str,
    tool_name: str | None = None,
    tool_args: dict[str, Any] | None = None,
    language: str | None = None,
) -> str:
    """The Personality Layer entry point.

    Takes the raw final response from tools or the LLM and guarantees the user
    sees natural, contextual, non-technical text in their own language.

    - Empty / terse ("Done.", "Готово.") / robotic ("Opening Safari, sir.")
      responses are rebuilt from the user's intent.
    - Tool-call JSON is stripped.
    - Errors are humanized.
    - Everything else passes through untouched.
    """
    language = language or detect_language(user_input)

    if not raw_response or not raw_response.strip():
        return contextual_confirmation(user_input, tool_name, tool_args, language)

    if _looks_like_error(raw_response):
        return humanize_error(raw_response, language)

    cleaned = strip_tool_call_json(raw_response)
    # XML tool calls (``<invoke>...``) leak just like JSON tool calls — strip
    # them too (live finding: Nemotron emits ``<tool>open</tool>`` as text).
    cleaned = strip_tool_call_xml(cleaned)
    # Secrets and implementation code never reach the user.
    cleaned = redact_api_keys(cleaned, language)
    cleaned = strip_code_fences(cleaned, user_input)
    if not cleaned:
        return contextual_confirmation(user_input, tool_name, tool_args, language)

    # A raw "tool_result: {...}" / "tool_result {...}" line (no natural
    # sentence) is internal — rebuild a human confirmation.
    if re.match(r"^\s*tool_result[\s:{]+", cleaned, re.IGNORECASE):
        return contextual_confirmation(user_input, tool_name, tool_args, language)

    # A bare JSON status payload ({"status": "ok", ...}) is internal state —
    # never show it to the user as the final answer. If the payload carries a
    # useful natural-language "result" field, keep that information instead of
    # discarding it entirely; otherwise rebuild a contextual confirmation.
    if _is_status_json_payload(cleaned):
        payload_result = _extract_payload_result(cleaned)
        if payload_result:
            payload_result = redact_api_keys(
                strip_code_fences(payload_result, user_input), language)
        if payload_result and not is_terse_response(payload_result):
            return payload_result
        return contextual_confirmation(user_input, tool_name, tool_args, language)

    if (
        is_terse_response(cleaned)
        or _is_robotic_confirmation(cleaned)
        or _is_llm_unavailable_fallback(cleaned)
    ):
        return contextual_confirmation(user_input, tool_name, tool_args, language)

    # Generic offer-of-help ("How can I help you?" / "Чем могу помочь?") is a
    # greeting-like non-answer — NEVER acceptable for a concrete question.
    # Allowed only when the user just greeted FOL or asked about capabilities.
    if (
        _is_generic_help_offer(cleaned)
        and not _is_pure_greeting(user_input)
        and not _user_asks_capabilities(user_input)
    ):
        return _generic_help_replacement(user_input, language)

    # Robotic honorific: "Done, sir." / "Открыл Safari, сэр." — strip the
    # honorific; if the remainder is still terse it gets rebuilt above, and
    # otherwise we show the natural sentence without the honorific.
    cleaned = _strip_honorific(cleaned)
    if is_terse_response(cleaned):
        return contextual_confirmation(user_input, tool_name, tool_args, language)

    return dedupe_repeated_sentences(cleaned)


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
