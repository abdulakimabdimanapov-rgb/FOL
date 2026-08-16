"""Text normalization utilities for user input preprocessing.

Zero-dependency module (stdlib only). Contains:
- normalize_user_input() — cleans whitespace, expands Russian shorthands,
                           corrects phonetic typos, handles Latin→Cyrillic transliteration
- _RU_TYPO_MAP — common Russian phonetic substitution pairs
- _CMD_ALIASES — Russian shorthand/abbreviation expansion
- _TRANSLITERATION_MAP — Latin-script Russian words → Cyrillic

Extracted from orchestrator/server.py so tests can import without heavy deps.
"""

from __future__ import annotations

import re as _re

# ---------------------------------------------------------------------------
# Common Russian typos and phonetic substitutions
# ---------------------------------------------------------------------------

_RU_TYPO_MAP: dict[str, str] = {
    'о': 'а', 'а': 'о',
    'е': 'и', 'и': 'е',
    'с': 'з', 'з': 'с',
    'т': 'д', 'д': 'т',
    'п': 'б', 'б': 'п',
    'к': 'г', 'г': 'к',
    'ш': 'щ', 'щ': 'ш',
    'ч': 'ц', 'ц': 'ч',
    'ы': 'и', 'и': 'ы',
    'у': 'ю', 'ю': 'у',
    'я': 'и',
}

# ---------------------------------------------------------------------------
# Russian shorthand / abbreviation expansion
# ---------------------------------------------------------------------------

_CMD_ALIASES: dict[str, str] = {
    'прив': 'привет',
    'здрав': 'здравствуй',
    'спс': 'спасибо',
    'пж': 'пожалуйста',
    'пжлст': 'пожалуйста',
    'плз': 'пожалуйста',
    'норм': 'нормально',
    'ок': 'окей',
    'окей': 'окей',
    'щас': 'сейчас',
    'сек': 'секунду',
    'мож': 'можешь',
    'сдел': 'сделай',
    'напиш': 'напиши',
    'откр': 'открой',
    'закр': 'закрой',
    'помощ': 'помоги',
    'скаж': 'скажи',
    'покаж': 'покажи',
    'отправ': 'отправь',
    'найд': 'найди',
    'провер': 'проверь',
}

# ---------------------------------------------------------------------------
# Latin → Cyrillic transliteration for Russian words typed in Latin script
# (Self-contained copy — also defined in agents.router)
# ---------------------------------------------------------------------------

_TRANSLITERATION_MAP: dict[str, str] = {
    'privet': 'привет',
    'spasibo': 'спасибо',
    'pozhaluysta': 'пожалуйста',
    'pzhalsta': 'пожалуйста',
    'zdravstvuy': 'здравствуй',
    'zdravstvuite': 'здравствуйте',
    'poka': 'пока',
    'davay': 'давай',
    'davai': 'давай',
    'nayti': 'найти',
    'naydi': 'найди',
    'napisat': 'написать',
    'sdelat': 'сделать',
    'sdelay': 'сделай',
    'ponyat': 'понять',
    'ponyal': 'понял',
    'delat': 'делать',
    'dumat': 'думать',
    'govorit': 'говорить',
    'rabotat': 'работать',
    'smotret': 'смотреть',
    'pisat': 'писать',
    'chitat': 'читать',
    'prochitat': 'прочитать',
    'proverit': 'проверить',
    'provery': 'проверь',
    'sozdat': 'создать',
    'sozday': 'создай',
    'dobavit': 'добавить',
    'dobav': 'добавь',
    'nuzhno': 'нужно',
    'mozhno': 'можно',
    'hotel': 'хотел',
    'hochesh': 'хочешь',
    'znat': 'знать',
    'znaesh': 'знаешь',
    'ponimaesh': 'понимаешь',
    'chelovek': 'человек',
    'rabota': 'работа',
    'vremya': 'время',
    'programma': 'программа',
    'sistema': 'система',
    'vopros': 'вопрос',
    'otvet': 'ответ',
    'seychas': 'сейчас',
    'uzhe': 'уже',
    'teper': 'теперь',
    'esche': 'еще',
    'posle': 'после',
    'potomu': 'потому',
    'pochemu': 'почему',
    'kogda': 'когда',
    'vsegda': 'всегда',
    'horosho': 'хорошо',
    'ploho': 'плохо',
    'ochen': 'очень',
    'bolshe': 'больше',
    'menshe': 'меньше',
    'luchshe': 'лучше',
    'interesno': 'интересно',
    'arhitektor': 'архитектор',
    'arhitektura': 'архитектура',
    'code': 'код',
    'kod': 'код',
    'prover': 'проверь',
    'rewu': 'ревью',      # non-standard but phonetically recognizable variant
    'revyu': 'ревью',
    'zapomni': 'запомни',
    'sokhrani': 'сохрани',
    'zametka': 'заметка',
    'zametku': 'заметку',
    'naydite': 'найдите',
    'poisk': 'поиск',
    'ischi': 'ищи',
    'informatsiya': 'информация',
    'obyasni': 'объясни',
    'rasskazhi': 'расскажи',
}

# ---------------------------------------------------------------------------
# normalize_user_input
# ---------------------------------------------------------------------------


def normalize_user_input(text: str) -> str:
    """Normalize user input for typo-tolerant matching.
    
    - Strips leading/trailing whitespace
    - Collapses multiple spaces
    - Handles common typos (Russian keyboard layout, phonetic substitutions)
    - Normalizes repeated letters
    - Expands Russian shorthands (спс→спасибо, пж→пожалуйста, etc.)
    - Transilterates Latin-script Russian words (privet→привет)
    """
    # Try transliteration first (Latin-script Russian → Cyrillic)
    # Only apply if text has no Cyrillic chars yet (avoid double-conversion)
    has_cyrillic = any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in text)
    if not has_cyrillic:
        words = text.split()
        converted = False
        for i, word in enumerate(words):
            clean = word.strip('.,!?;:\'"()[]{}')
            if clean.lower() in _TRANSLITERATION_MAP:
                replacement = _TRANSLITERATION_MAP[clean.lower()]
                if clean and clean[0].isupper():
                    replacement = replacement.capitalize()
                words[i] = word.replace(clean, replacement)
                converted = True
        if converted:
            text = ' '.join(words)

    # Strip and collapse whitespace
    text = text.strip()
    text = _re.sub(r'\s+', ' ', text)

    # Remove excessive repeated letters (but keep at least 2 for emphasis)
    text = _re.sub(r'(.)\1{3,}', r'\1\1', text)

    # Normalize common punctuation around words
    text = _re.sub(r'([!?.,;:])\1+', r'\1', text)

    # Apply phonetic typo substitutions for Russian words
    words = text.split()
    for i, word in enumerate(words):
        clean_word = word.strip('.,!?;:\'"()[]{}')
        if len(clean_word) < 2:
            continue

        # Try command aliases first (abbreviations → full words)
        lower_word = clean_word.lower()
        if lower_word in _CMD_ALIASES:
            replacement = _CMD_ALIASES[lower_word]
            if word[0].isupper():
                replacement = replacement.capitalize()
            words[i] = word.replace(clean_word, replacement)
            continue

        # Apply phonetic substitutions for common Russian typos
        corrected = list(lower_word)
        for j, ch in enumerate(corrected):
            mapped = _RU_TYPO_MAP.get(ch)
            if mapped and len(clean_word) >= 4:
                corrected[j] = mapped

        corrected_word = ''.join(corrected)
        if corrected_word in _CMD_ALIASES:
            replacement = _CMD_ALIASES[corrected_word]
            if word[0].isupper():
                replacement = replacement.capitalize()
            words[i] = word.replace(clean_word, replacement)

    return ' '.join(words)
