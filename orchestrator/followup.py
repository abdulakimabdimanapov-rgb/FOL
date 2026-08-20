"""Follow-up resolution helpers.

Conservative heuristic rewrites to expand pronouns and short follow-up
queries into self-contained prompts using recent conversation context.

This module never removes user text; it only prepends or rewrites when a
clear referent can be inferred from the last assistant turn. Keep rules
minimal to avoid accidental misinterpretation.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from orchestrator import response_formatter


_PRONOUN_PATTERNS = [
    r"\bэто\b",
    r"\bтам\b",
    r"\bон\b",
    r"\bона\b",
    r"\bони\b",
    r"\bещё\b",
    r"\bа теперь\b",
    r"\bпродолжай\b",
    r"\bсделай так же\b",
    r"\bкакой из них\b",
    r"\bпервый\b",
    r"\bпоследний\b",
]

# Greetings / small-talk that must never be rewritten into a follow-up.
_NON_FOLLOWUP = [
    r"\bпривет\b",
    r"\bкак дела\b",
    r"\bhello\b",
    r"\bhi\b",
    r"\bспасибо\b",
    r"\bспс\b",
    r"\bпока\b",
    r"\bкто ты\b",
    r"\bчто ты умеешь\b",
]

# Command verbs — a message starting with one is a NEW command, not a follow-up.
_COMMAND_VERBS = [
    "напиш", "открой", "создай", "найди", "сохран", "запомн", "удали",
    "сделай", "проверь", "переведи", "отправ", "запусти", "поищ", "ищи",
    "прочитай", "откр", "выполни", "закрой", "установи",
]


def _contains_pronoun(text: str) -> bool:
    t = text.lower()
    for p in _PRONOUN_PATTERNS:
        if re.search(p, t):
            return True
    return False


def _last_assistant_text(recent: Iterable[dict[str, Any]]) -> str | None:
    """Extract the last assistant textual content from conversation history."""
    # recent is list of {'role': role, 'content': ...}
    for msg in reversed(list(recent)):
        if msg.get("role") == "assistant":
            content = msg.get("content")
            # content might be string or list of blocks
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # prefer text blocks
                pieces = []
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        pieces.append(b.get("text", ""))
                if pieces:
                    return " ".join(pieces)
                # fallback: serialize minimally
                try:
                    return str(content)
                except Exception:
                    return None
    return None


def _is_short_question(text: str) -> bool:
    """True for a short question without pronouns ("Какая самая важная?")
    that almost certainly refers to the previous assistant result."""
    t = text.strip()
    if not t.endswith("?"):
        return False
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) > 6:
        return False
    low = t.lower()
    if any(re.search(p, low) for p in _NON_FOLLOWUP):
        return False
    if any(v in low for v in _COMMAND_VERBS):
        return False
    return True


def resolve_followup(message: str, recent_history: Iterable[dict[str, Any]]) -> tuple[str, bool]:
    """Return (possibly_rewritten_message, was_rewritten).

    Conservative behavior: if `message` appears to be a short follow-up
    referencing a prior assistant result (pronouns, short questions), and
    there is a non-empty last assistant text, rewrite by making the referent
    explicit. Otherwise return the original message.
    """
    if not message:
        return message, False
    if not (_contains_pronoun(message) or _is_short_question(message)):
        return message, False

    last = _last_assistant_text(recent_history)
    if not last:
        return message, False

    # Sanitize last assistant text (strip tool-call JSON)
    try:
        safe = response_formatter.strip_tool_call_json(last)
    except Exception:
        safe = last
    safe = safe.strip()
    if not safe:
        return message, False

    # Truncate to a conservative length
    if len(safe) > 400:
        safe = safe[:400].rsplit(" ", 1)[0] + "..."

    # If message starts with a verb that expects an object (e.g. "сохрани это"),
    # insert the referent before the object.
    low = message.strip()
    # Common Russian patterns. Use a callable replacement: the verb is captured
    # in group 1 and re-inserted verbatim (a plain f-string "\1" would render
    # as the \x01 control character, corrupting the message).
    patterns = [
        r"^(сохрани|запиши|сбей|сохрани это|запомни)\b",
    ]
    for pat in patterns:
        if re.search(pat, low, flags=re.IGNORECASE):
            new = re.sub(pat, lambda m: f"{m.group(1)} \"{safe}\"", low, flags=re.IGNORECASE)
            return new, True

    # Fallback: prepend context
    new = f"Относительно предыдущего результата: \"{safe}\". {message}"
    return new, True
