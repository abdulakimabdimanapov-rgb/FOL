"""Task Router — classifies user requests and routes to the right agent.

Uses a lightweight keyword/pattern matching approach to classify tasks
without an extra LLM call. Falls back to general purpose if uncertain.

Supports fuzzy matching for typo-tolerant routing (uses difflib).
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from enum import Enum


class AgentType(str, Enum):
    """Agent categories that match user task types."""
    ARCHITECT = "architect"       # System design, planning, architecture decisions
    CODER = "coder"               # Code generation, implementation
    REVIEWER = "reviewer"         # Code review, debugging, quality analysis
    RESEARCHER = "researcher"     # Web research, information gathering
    MEMORY = "memory"             # Memory management, Obsidian notes, organization
    GENERAL = "general"           # Default — all-purpose assistant


# Latin-script Russian words → Cyrillic (transliteration)
# Imported from utils.text_normalizer to avoid duplicating ~80 key-value pairs.
# Single source of truth: common Latin→Cyrillic mappings live in text_normalizer.py.
from utils.text_normalizer import _TRANSLITERATION_MAP  # type: ignore[import-untyped]

# Greetings and casual phrases — return GENERAL immediately, bypass all routing
_GREETINGS: list[str] = [
    # English
    "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
    "how are you", "how's it going", "what's up", "sup",
    # Russian
    "привет", "здравствуй", "здравствуйте", "хай", "хей",
    "как дела", "как ты", "как вы", "как жизнь", "как поживаешь",
    "доброе утро", "добрый день", "добрый вечер",
    "че как", "норм", "ок",
]


# Routing patterns: (keywords, agent_type)
# Ordered by specificity — first match wins
# Includes both English AND Russian keywords for bilingual support.
# Russian keywords use common forms (imperative, infinitive) for maximum coverage.
#
# IMPORTANT: REVIEWER comes before CODER so that mixed commands like
# "ревью код" or "review this code" correctly route to REVIEWER.
# (Previously CODER was first, causing "код" to capture everything.)
_ROUTES: list[tuple[list[str], AgentType]] = [
    # --- Architect ---
    ([
        # English
        "architecture", "architect", "design pattern", "system design",
        "component diagram", "data flow", "technical decision",
        "how should i structure", "what architecture", "plan the",
        "milestone", "roadmap", "technical spec", "specification",
        # Русский
        "архитектур", "спроектир", "проектирован", "дизайн",
        "схема", "поток данных", "архитектура", "план",
        "структур", "компонент", "диаграмм", "миграци",
        "как спроектировать", "какую архитектур", "техническое задание",
        "тз", "туду", "roadmap", "майлстоун",
    ], AgentType.ARCHITECT),

    # --- Reviewer (before Coder!) ---
    ([
        # English
        "review", "code review", "review this", "check my code",
        "check", "check this", "is this correct", "potential issue",
        "security audit", "vulnerability", "code quality",
        "best practices", "does this look good", "review the", "audit",
        # Русский
        "провер", "ревью", "код-ревью", "код ревью",
        "качеств", "безопасност", "уязвим", "аудит",
        "правильно ли", "потенциальн", "проблем", "баг",
        "как тебе", "посмотр", "оцен", "рецензи",
    ], AgentType.REVIEWER),

    # --- Coder ---
    ([
        # English
        "implement", "write code", "create function", "build a",
        "add feature", "code this", "generate code", "implement a",
        "fix this bug", "debug this", "refactor this", "optimize this",
        "write tests", "unit test", "create class", "make a", "script",
        "pull request", "merge request", "code change", "commit",
        # Русский
        "напиш", "код", "программ", "функци", "класс",
        "сдел", "создай", "добав", "реализуй", "рефактор",
        "исправ", "почин", "баг", "ошибк", "отлад",
        "оптимизир", "тест", "юнит", "модуль", "скрипт",
        "фич", "фичу", "алгоритм", "реализоват", "проверь код",
        "напиши код", "сделай функцию", "создай класс", "добавь функцию",
    ], AgentType.CODER),

    # --- Researcher ---
    ([
        # English
        "search", "find", "research", "look up", "google",
        "what is", "who is", "tell me about", "how does",
        "explain", "latest news", "current", "compare",
        "difference between", "summary of", "investigate",
        "learn about", "information on", "documentation for",
        # Русский
        "найд", "поищ", "ищи", "гугл", "погугл", "исслед",
        "узнай", "расскаж", "объясн", "что такое", "кто такой",
        "новост", "последн", "сравн", "разниц", "суммар",
        "документаци", "информаци", "прочитай", "посмотр",
        "найди информаци", "поищи в", "найди в",
    ], AgentType.RESEARCHER),

    # --- Memory ---
    ([
        # English
        "remember", "save this", "store", "note", "obsidian",
        "memory", "remind me", "don't forget", "create a note",
        "write to", "log this", "journal", "daily note",
        "add to", "organize", "consolidate", "summarize this",
        "what do you know about me", "recall",
        # Русский
        "запомн", "сохран", "заметк", "obsidian",
        "памят", "напомн", "не забудь", "создай заметк",
        "запиш", "дневник", "ежедневн", "добавь в",
        "организуй", "структурир", "итог", "подведи",
        "что ты знаешь", "вспомн", "лог", "журнал",
    ], AgentType.MEMORY),
]

# Flattened list of all keywords for fuzzy matching
_ALL_KEYWORDS: list[str] = []
for keywords, _ in _ROUTES:
    _ALL_KEYWORDS.extend(keywords)

# Single-word keywords ONLY — used by _fuzzy_classify.
# Multi-word phrases ("what is", "write code") are excluded because a
# short single word like "what" fuzzy-matches them (SequenceMatcher ratio
# 0.727 for "what" vs "what is") and misroutes casual questions to
# RESEARCHER. Multi-word phrases are still matched exactly via substring
# in _classify_by_keywords, so excluding them here loses no coverage.
_FUZZY_KEYWORDS: list[str] = [kw for kw in _ALL_KEYWORDS if ' ' not in kw]


def _is_greeting(task: str) -> bool:
    """Check if the task is a greeting/casual phrase — return GENERAL immediately.
    
    Uses word boundaries for single-word greetings (e.g. "hi" won't match "this").
    Multi-word phrases match as substrings (e.g. "how are you").
    """
    task_lower = task.lower().strip()
    for greeting in _GREETINGS:
        if ' ' in greeting:
            # Multi-word phrase: substring match is safe
            if greeting in task_lower:
                return True
        else:
            # Single word: use word boundary to avoid "hi" matching "this"
            if re.search(r'\b' + re.escape(greeting) + r'\b', task_lower):
                return True
    return False


def _apply_transliteration(text: str) -> str:
    """Convert Latin-script Russian words to Cyrillic.
    
    Only applies if the text contains no Cyrillic characters
    (detected by presence of Latin-only Russian words). This prevents
    double-conversion of already-Cyrillic text.
    """
    has_cyrillic = any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in text)
    if has_cyrillic:
        return text
    
    # Split on ORIGINAL text (not lowered) so we can check case per word
    words = text.split()
    converted = []
    for word in words:
        clean = word.strip('.,!?;:\'"()[]{}')
        lower_clean = clean.lower()
        if lower_clean in _TRANSLITERATION_MAP:
            replacement = _TRANSLITERATION_MAP[lower_clean]
            # Preserve original case for first char using the ORIGINAL word
            if clean and clean[0].isupper():
                replacement = replacement.capitalize()
            converted.append(word.replace(clean, replacement))
        else:
            converted.append(word)
    
    return ' '.join(converted)


def _classify_by_keywords(task: str) -> AgentType | None:
    """Try to classify the task using keyword matching (fast, no LLM call)."""
    task_lower = task.lower()

    for keywords, agent_type in _ROUTES:
        for kw in keywords:
            if kw in task_lower:
                return agent_type

    return None


def _fuzzy_classify(task: str) -> AgentType | None:
    """Fuzzy classification: matches keywords with typos using difflib.
    
    For each word in the task, try to find a close match against all
    routing keywords. If found, return the corresponding agent type.
    """
    words = task.lower().split()
    
    for word in words:
        clean = word.strip('.,!?;:\'"()[]{}')
        if len(clean) < 3:
            continue
        
        # Try to fuzzy match this word against single-word keywords only.
        # Multi-word keywords are matched exactly (substring) in
        # _classify_by_keywords — fuzzy-matching them here creates false
        # positives like "what" → "what is" → RESEARCHER.
        matches = difflib.get_close_matches(clean, _FUZZY_KEYWORDS, n=1, cutoff=0.72)
        if not matches:
            continue
        
        matched_keyword = matches[0]
        # Find which agent this keyword belongs to
        for keywords, agent_type in _ROUTES:
            if matched_keyword in keywords:
                return agent_type
    
    return None


def _detect_language(text: str) -> str:
    """Detect whether text is Russian, English, or mixed.
    
    Returns: 'ru', 'en', or 'mixed'
    """
    if not text.strip():
        return 'en'
    
    ru_chars = 0
    en_chars = 0
    
    for ch in text:
        if 'а' <= ch.lower() <= 'я' or ch.lower() == 'ё':
            ru_chars += 1
        elif 'a' <= ch.lower() <= 'z':
            en_chars += 1
    
    total = ru_chars + en_chars
    if total == 0:
        return 'en'
    
    ru_ratio = ru_chars / total
    
    if ru_ratio > 0.8:
        return 'ru'
    elif ru_ratio < 0.2:
        return 'en'
    else:
        return 'mixed'


def _bilingual_route(task: str) -> AgentType | None:
    """Handle bilingual (mixed Russian-English) commands.
    
    Many Russian-English bilingual speakers mix languages mid-sentence.
    E.g.: "напиши код для sorting algorithm" or "check my code пожалуйста"
    
    This parses both the Russian and English parts separately and
    merges their routing signals.
    """
    lang = _detect_language(task)
    
    if lang != 'mixed':
        return None  # Not mixed, normal routing handles it
    
    # For mixed language, try routing on English words AND Russian words separately
    # Pick the most specific result
    english_task = ' '.join(
        w for w in task.split() 
        if all('a' <= c.lower() <= 'z' for c in w if c.isalpha())
    )
    russian_task = ' '.join(
        w for w in task.split()
        if all('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in w if c.isalpha())
    )
    
    # Try routing on each language part separately
    results = []
    for partial_task in [english_task, russian_task]:
        if len(partial_task.split()) < 1:
            continue
        result = _classify_by_keywords(partial_task)
        if result and result != AgentType.GENERAL:
            results.append(result)
        # Also try fuzzy
        fuzzy = _fuzzy_classify(partial_task)
        if fuzzy and fuzzy != AgentType.GENERAL:
            results.append(fuzzy)
    
    if not results:
        return None
    
    # Majority vote with English preference for tie-breaking
    counts = Counter(results)
    top_result = counts.most_common(1)[0]
    
    # If there's a tie (same count for top two), prefer English result
    if len(counts) >= 2:
        top_two = counts.most_common(2)
        if top_two[0][1] == top_two[1][1]:
            # Tie — try English-only exact match
            en_exact = _classify_by_keywords(english_task)
            if en_exact:
                return en_exact
    
    return top_result[0]


def route_task(task: str, conversation_history: list | None = None) -> AgentType:
    """Classify a task and return the best agent type.
    
    Supports:
    - Transliteration (Latin 'privet' → Cyrillic 'привет')
    - Greeting detection (привет, как дела → GENERAL)
    - English commands (original)
    - Russian commands (full Russian keywords)
    - Mixed Russian-English commands (bilingual detection)
    - Typo-tolerant routing (fuzzy matching)
    - Conversation history heuristic
    
    Falls back to GENERAL if uncertain.
    """
    # 0. Apply transliteration (Latin Russian → Cyrillic) before any matching
    task = _apply_transliteration(task)

    # 1. Check for greetings/casual phrases first
    if _is_greeting(task):
        return AgentType.GENERAL

    # 2. Try bilingual routing first (mixed Russian-English commands)
    bilingual_result = _bilingual_route(task)
    if bilingual_result is not None:
        return bilingual_result

    # 3. Try exact keyword classification (handles both EN and RU keywords)
    result = _classify_by_keywords(task)
    if result is not None:
        return result

    # 4. Try fuzzy matching (handles typos in both languages!)
    result = _fuzzy_classify(task)
    if result is not None:
        return result

    # 5. If we have conversation history, check if the previous assistant
    #    response suggests a direction (e.g., architect proposed a plan)
    if conversation_history:
        for msg in reversed(conversation_history[-4:]):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content:
                    # If assistant started something, continue with relevant agent
                    # Simple heuristic: check the last assistant message for keywords
                    return _classify_by_keywords(content) or AgentType.GENERAL

    # 6. Default fallback
    return AgentType.GENERAL
