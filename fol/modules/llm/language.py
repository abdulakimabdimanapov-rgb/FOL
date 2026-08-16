"""Language detection utility — detects whether user input is Russian or English."""

from __future__ import annotations

import re
import unicodedata


# Cyrillic Unicode range (Russian letters: U+0400–U+04FF)
_CYRILLIC_RANGE = re.compile(r"[\u0400-\u04FF]")

# Latin Unicode range
_LATIN_RANGE = re.compile(r"[a-zA-Z]")

# Common Russian words (for boosted detection)
_RUSSIAN_WORDS = frozenset({
    "привет", "пожалуйста", "спасибо", "помощь", "сделай", "открой",
    "закрой", "запусти", "выполни", "найди", "прочитай", "напиши",
    "покажи", "что", "как", "где", "когда", "почему", "кто",
    "да", "нет", "можешь", "нужно", "хочу", "может", "быть",
    "этот", "тот", "весь", "мой", "твой", "наш", "ваш",
    "и", "а", "но", "или", "не", "ни", "да", "нет",
    "в", "на", "из", "за", "по", "к", "о", "у", "с",
    "то", "так", "уже", "ещё", "еще", "очень", "тоже", "также",
    "сейчас", "потом", "потом", "вчера", "сегодня", "завтра",
    "который", "какой", "такой", "чей", "сколько",
    "говори", "скажи", "скажи", "расскажи", "объясни",
    "сверни", "разверни", "сделай", "включи", "выключи",
    "здравствуй", "пока", "спокойной", "ночи",
})

# Common English words (for boosted detection)
_ENGLISH_WORDS = frozenset({
    "hello", "hi", "hey", "please", "thank", "thanks", "help",
    "make", "do", "open", "close", "run", "find", "read",
    "write", "show", "what", "how", "where", "when", "why", "who",
    "yes", "no", "can", "you", "need", "want", "maybe",
    "this", "that", "all", "my", "your", "our", "their",
    "and", "but", "or", "not", "nor", "is", "are", "was",
    "the", "a", "an", "in", "on", "at", "to", "for", "of",
    "it", "so", "just", "also", "very", "too", "now",
    "then", "yesterday", "today", "tomorrow",
    "which", "what", "such", "whose", "how",
    "speak", "say", "tell", "explain",
    "minimize", "maximize", "switch", "launch",
    "goodbye", "bye", "good", "night", "morning",
})

# Language header markers
_LANG_HEADER = re.compile(
    r"^\s*(?:lang(?:uage)?|язык|ответь на|respond in|пиши на|говори на)\s*[:=]\s*(ru|en|rus|eng|русск|англ)",
    re.IGNORECASE,
)


def detect_language(text: str) -> str:
    """Detect the dominant language of the input text.

    Returns ``"ru"`` for Russian, ``"en"`` for English.
    Defaults to ``"en"`` when detection is ambiguous.
    """
    if not text or not text.strip():
        return "en"

    cleaned = text.strip()

    # 1. Explicit language header  (e.g. "lang: ru" or "язык: русский")
    header_match = _LANG_HEADER.match(cleaned)
    if header_match:
        token = header_match.group(1).lower()
        if token in ("ru", "rus", "русск", "русский"):
            return "ru"
        return "en"

    # 2. Count script characters
    cyrillic_count = len(_CYRILLIC_RANGE.findall(cleaned))
    latin_count = len(_LATIN_RANGE.findall(cleaned))
    total_alpha = cyrillic_count + latin_count

    if total_alpha == 0:
        return "en"

    cyrillic_ratio = cyrillic_count / total_alpha

    # Strong Cyrillic majority → Russian
    if cyrillic_ratio > 0.4:
        return "ru"

    # Strong Latin majority → English
    if cyrillic_ratio < 0.1:
        return "en"

    # 3. Ambiguous zone (10-40% Cyrillic) — use word matching
    words = set(re.findall(r"[a-zа-яё]+", cleaned.lower()))
    ru_hits = len(words & _RUSSIAN_WORDS)
    en_hits = len(words & _ENGLISH_WORDS)

    if ru_hits > en_hits:
        return "ru"
    if en_hits > ru_hits:
        return "en"

    # 4. Still ambiguous — fall back to script ratio
    return "ru" if cyrillic_ratio >= 0.25 else "en"


def get_lang_name(code: str) -> str:
    """Return a human-readable language name."""
    return "Russian" if code == "ru" else "English"


def get_lang_prompt_hint(code: str) -> str:
    """Return an instruction snippet for the LLM to enforce response language."""
    if code == "ru":
        return (
            "ВАЖНО: Пользователь пишет на русском. "
            "Ты ОБЯЗАН ответить ТОЛЬКО на русском языке. "
            "Не используй английский в ответе."
        )
    return (
        "IMPORTANT: The user is writing in English. "
        "You MUST respond ONLY in English. "
        "Do not use Russian in your response."
    )
