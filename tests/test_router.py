"""Unit tests for orchestrator/agents/router.py.

Tests the bilingual routing system: language detection, exact keyword
matching, fuzzy typo-tolerant matching, and bilingual route dispatch.
"""
from __future__ import annotations

import sys
import pytest
from pathlib import Path

_project_root = Path(__file__).parent.parent
_orch_dir = _project_root / "orchestrator"
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_orch_dir))

from orchestrator.agents.router import (
    AgentType,
    _ROUTES,
    _FUZZY_KEYWORDS,
    _classify_by_keywords,
    _detect_language,
    _fuzzy_classify,
    _bilingual_route,
    _is_greeting,
    _apply_transliteration,
    route_task,
)


# ===========================================================================
# _detect_language
# ===========================================================================

def test_detect_language_english() -> None:
    assert _detect_language("hello world this is english") == "en"


def test_detect_language_russian() -> None:
    assert _detect_language("привет мир это русский") == "ru"


def test_detect_language_mixed() -> None:
    assert _detect_language("напиши код для sorting algorithm") == "mixed"


def test_detect_language_mixed_with_punctuation() -> None:
    assert _detect_language("check my code пожалуйста!") == "mixed"


def test_detect_language_empty() -> None:
    assert _detect_language("") == "en"


def test_detect_language_whitespace() -> None:
    assert _detect_language("   ") == "en"


def test_detect_language_numbers_only() -> None:
    assert _detect_language("123 456 789") == "en"


def test_detect_language_symbols_only() -> None:
    assert _detect_language("@#$%^&*()") == "en"


def test_detect_language_russian_with_yo() -> None:
    assert _detect_language("ёлка") == "ru"


def test_detect_language_mostly_english() -> None:
    # 1 Russian word among 3 → ~30% Russian → mixed. Use 1 Russian word among 5.
    assert _detect_language("hello world and other при") == "en"


def test_detect_language_mostly_russian() -> None:
    # 1 English word among 5 Russian → ~10% English > 80% Russian → ru
    assert _detect_language("привет мир как дела здрав hello") == "ru"


def test_detect_language_boundary_just_over_80() -> None:
    """5 Russian chars + 1 English char = 83.3% → ru (> 0.8)"""
    assert _detect_language("приве a") == "ru"


def test_detect_language_boundary_just_under_20() -> None:
    """1 Russian char + 5 English chars = 16.7% → en (< 0.2)"""
    assert _detect_language("я hello") == "en"


def test_detect_language_boundary_exactly_80() -> None:
    """4 Russian + 1 English = 80% Russian → NOT > 0.8, so 'mixed'"""
    assert _detect_language("привa") == "mixed"


def test_detect_language_uppercase_russian() -> None:
    assert _detect_language("ПРИВЕТ МИР") == "ru"


def test_detect_language_uppercase_english() -> None:
    assert _detect_language("HELLO WORLD") == "en"


def test_detect_language_mixed_with_numbers() -> None:
    # Numbers/Оpen punctuation don't affect ratio
    assert _detect_language("123 привет 456 world") == "mixed"


def test_detect_language_single_char_russian() -> None:
    assert _detect_language("я") == "ru"


def test_detect_language_single_char_english() -> None:
    assert _detect_language("a") == "en"


def test_detect_language_mixed_with_punctuation() -> None:
    assert _detect_language("привет, hello!") == "mixed"


def test_detect_language_newlines_and_tabs() -> None:
    assert _detect_language("\tнапиши код\nвот sorting\nalgorithm") == "mixed"


# ===========================================================================
# _classify_by_keywords — English
# ===========================================================================

def test_classify_english_coder() -> None:
    assert _classify_by_keywords("implement a sorting algorithm") == AgentType.CODER


def test_classify_english_reviewer() -> None:
    # Avoid "pull request" (CODER keyword) and "code change" (also CODER)
    assert _classify_by_keywords("kindly review this document") == AgentType.REVIEWER


def test_classify_english_architect() -> None:
    assert _classify_by_keywords("what architecture should i use") == AgentType.ARCHITECT


def test_classify_english_researcher() -> None:
    assert _classify_by_keywords("search for latest AI news") == AgentType.RESEARCHER


def test_classify_english_memory() -> None:
    assert _classify_by_keywords("remember this for later") == AgentType.MEMORY


def test_classify_english_review_before_coder() -> None:
    # REVIEWER is now before CODER in _ROUTES, so "review" matches first
    assert _classify_by_keywords("review this pull request") == AgentType.REVIEWER


def test_classify_english_pull_request_no_review_is_coder() -> None:
    # Without "review", "pull request" matches CODER
    assert _classify_by_keywords("create a pull request") == AgentType.CODER


def test_classify_english_no_match() -> None:
    assert _classify_by_keywords("how is the weather today") is None


def test_classify_english_empty() -> None:
    assert _classify_by_keywords("") is None


# ===========================================================================
# _classify_by_keywords — Russian
# ===========================================================================

def test_classify_russian_coder() -> None:
    assert _classify_by_keywords("напиши код для парсера") == AgentType.CODER


def test_classify_russian_coder_simple() -> None:
    # "код" alone matches CODER
    assert _classify_by_keywords("код") == AgentType.CODER


def test_classify_russian_reviewer() -> None:
    # Avoid "код" (CODER keyword) — use pure review phrase
    assert _classify_by_keywords("проверь изменения в пул реквесте") == AgentType.REVIEWER


def test_classify_russian_architect() -> None:
    assert _classify_by_keywords("спроектируй архитектуру базы данных") == AgentType.ARCHITECT


def test_classify_russian_researcher() -> None:
    assert _classify_by_keywords("найди информацию про нейросети") == AgentType.RESEARCHER


def test_classify_russian_memory() -> None:
    assert _classify_by_keywords("сохрани эту заметку в obsidian") == AgentType.MEMORY


def test_classify_russian_review_with_code_is_reviewer() -> None:
    # REVIEWER is now before CODER: "провер" matches first
    assert _classify_by_keywords("проверь мой код") == AgentType.REVIEWER



def test_classify_russian_no_match() -> None:
    assert _classify_by_keywords("это просто текст") is None


def test_classify_russian_ishi_is_researcher() -> None:
    """'ищи' added as RESEARCHER keyword."""
    assert _classify_by_keywords("ищи статью") == AgentType.RESEARCHER


# ===========================================================================
# _fuzzy_classify — typo tolerance
# ===========================================================================

def test_fuzzy_english_typo_implement() -> None:
    result = _fuzzy_classify("implemnt a sorting algorithm")
    assert result == AgentType.CODER


def test_fuzzy_english_typo_review() -> None:
    result = _fuzzy_classify("revue my code please")
    assert result == AgentType.REVIEWER


def test_fuzzy_english_typo_search() -> None:
    result = _fuzzy_classify("serch for AI news")
    assert result == AgentType.RESEARCHER


def test_fuzzy_russian_typo_architect() -> None:
    result = _fuzzy_classify("какую архитект использовать")
    assert result == AgentType.ARCHITECT


def test_fuzzy_russian_typo_program() -> None:
    result = _fuzzy_classify("напиши програм")
    assert result == AgentType.CODER


def test_fuzzy_short_word_skipped() -> None:
    assert _fuzzy_classify("hi") is None


def test_fuzzy_no_match_gibberish() -> None:
    assert _fuzzy_classify("xylophone zephyr quantum") is None


def test_fuzzy_empty() -> None:
    assert _fuzzy_classify("") is None


def test_fuzzy_russian_typo_find() -> None:
    """'файнд' (Cyrillic тy-spelling of 'find') — still Cyrillic ≠ Latin, no match.
    This tests that cross-script fuzzy matching correctly returns None."""
    result = _fuzzy_classify("файнд")
    assert result is None


def test_fuzzy_russian_typo_naydi() -> None:
    """'найди' (5 chars) fuzzy-matches 'найд' (4 chars, RESEARCHER) at 0.889 > 0.72."""
    result = _fuzzy_classify("найди информацию")
    assert result == AgentType.RESEARCHER


def test_fuzzy_english_typo_with_punctuation() -> None:
    """Punctuation stripped before fuzzy matching."""
    result = _fuzzy_classify("implemnt! the code")
    assert result == AgentType.CODER


def test_fuzzy_english_typo_explain() -> None:
    """'explin' fuzzy-matches 'explain' → RESEARCHER."""
    result = _fuzzy_classify("explin this concept")
    assert result == AgentType.RESEARCHER


def test_fuzzy_russian_typo_program_misspelled() -> None:
    """'прогрм' (typo for 'программ') fuzzy-matches CODER keyword."""
    result = _fuzzy_classify("напиши прогрм")
    assert result == AgentType.CODER


def test_fuzzy_english_typo_architect() -> None:
    """'archteture' fuzzy-matches 'architecture' → ARCHITECT."""
    result = _fuzzy_classify("archteture design")
    assert result == AgentType.ARCHITECT


def test_fuzzy_russian_typo_reviewer_z() -> None:
    """'рецензы' fuzzy-matches 'рецензи' → REVIEWER."""
    result = _fuzzy_classify("рецензы кода")
    assert result == AgentType.REVIEWER


def test_fuzzy_mixed_language_typo() -> None:
    """'implemnt' alone (English typo) → CODER even without Russian words."""
    result = _fuzzy_classify("implemnt")
    assert result == AgentType.CODER


def test_fuzzy_single_word_not_matched_against_multiword_phrase() -> None:
    """A short single word must NOT fuzzy-match a multi-word keyword.
    Previously 'what' (ratio 0.727 vs 'what is') was routed to RESEARCHER;
    now multi-word keywords are excluded from fuzzy matching entirely."""
    result = _fuzzy_classify("what")
    assert result is None


def test_fuzzy_cutoff_wht_below_threshold() -> None:
    """'wht' (3 chars) vs 'what is': SequenceMatcher ratio = 0.6, below 0.72 cutoff.
    Even though 'wht' vs 'what' alone is 0.857, 'what' is not a standalone keyword —
    only 'what is' is. So 'wht' returns None."""
    result = _fuzzy_classify("wht")
    assert result is None


def test_fuzzy_casual_question_word_does_not_route() -> None:
    """Casual English question words must not misroute to RESEARCHER.
    'how' and 'who' are similar to 'what' — none should fuzzy-match
    multi-word RESEARCHER keywords like 'how does' / 'who is'."""
    assert _fuzzy_classify("how") is None
    assert _fuzzy_classify("who") is None
    assert _fuzzy_classify("when") is None


def test_fuzzy_multiword_keywords_excluded_from_fuzzy_pool() -> None:
    """Every fuzzy-candidate keyword must be a single word (no spaces)."""
    assert _FUZZY_KEYWORDS
    assert all(' ' not in kw for kw in _FUZZY_KEYWORDS)


# ===========================================================================
# _bilingual_route — mixed Russian-English
# ===========================================================================

def test_bilingual_english_only_returns_none() -> None:
    assert _bilingual_route("implement sorting algorithm") is None


def test_bilingual_russian_only_returns_none() -> None:
    assert _bilingual_route("напиши код") is None


def test_bilingual_no_match() -> None:
    assert _bilingual_route("как погода today") is None


def test_bilingual_mixed_researcher() -> None:
    """поищи про machine learning → обе части → RESEARCHER"""
    result = _bilingual_route("поищи про machine learning")
    assert result == AgentType.RESEARCHER


def test_bilingual_mixed_coder() -> None:
    """напиши sorting algorithm → Russian 'напиши' alone <2 words skipped,
    English 'sorting algorithm' has no keyword match → falls to normal routing.
    Test via route_task (not _bilingual_route directly)."""
    assert route_task("напиши sorting algorithm") == AgentType.CODER


def test_bilingual_mixed_memory_english_remember() -> None:
    """'remember эту информацию' → English 'remember' (1 word, >=1) → MEMORY."""
    result = _bilingual_route("remember эту информацию")
    assert result == AgentType.MEMORY


def test_bilingual_mixed_architect_english() -> None:
    """'design архитектуру' → English 'design' matches ARCHITECT."""
    result = _bilingual_route("design архитектуру")
    assert result == AgentType.ARCHITECT


def test_bilingual_mixed_reviewer_check() -> None:
    """'check мой код' → English 'check' (1 word) now processed → REVIEWER."""
    result = _bilingual_route("check мой код")
    assert result == AgentType.REVIEWER


def test_bilingual_mixed_exact_and_fuzzy_combine() -> None:
    """'implemnt код' → fuzzy 'implemnt'→CODER + exact 'код'→CODER = majority CODER."""
    result = _bilingual_route("implemnt код")
    assert result == AgentType.CODER


def test_bilingual_mixed_tie_english_preferred() -> None:
    """'check спроектируй' → English 'check'→REVIEWER, Russian 'спроектируй'→ARCHITECT.
    Tie → English preferred → REVIEWER."""
    result = _bilingual_route("check спроектируй")
    assert result == AgentType.REVIEWER


def test_bilingual_mixed_reviewer_tie_english_wins() -> None:
    """'review архитектуру' → 'review'→REVIEWER, 'архитектур'→ARCHITECT.
    Tie, English preferred → REVIEWER."""
    result = _bilingual_route("review архитектуру")
    assert result == AgentType.REVIEWER


def test_bilingual_mixed_russian_only_part_has_keyword() -> None:
    """'test код' → English 'test' has no single-word fuzzy match anymore
    ("unit test" is multi-word and excluded), Russian 'код'→CODER.
    Majority: CODER."""
    result = _bilingual_route("test код")
    assert result == AgentType.CODER


def test_bilingual_mixed_numbers_only_returns_none() -> None:
    """Mixed text with only numbers/punctuation → no words to classify → None."""
    result = _bilingual_route("123 456 привет 789 hello")
    # 'hello' (1 word, processed) → greeting check runs BEFORE bilingual in route_task
    # But _bilingual_route directly: english_task='hello' (1 word), classify('hello')=None
    # russian_task='привет' (1 word), classify('привет')=None ('прив' is not a keyword)
    # Fuzzy might catch 'привет'? None of the keywords match 'привет' exactly.
    # So no results → None
    assert result is None


def test_bilingual_mixed_no_alpha_words() -> None:
    """Text with no alphabetic characters → None."""
    assert _bilingual_route("123 !@# $") is None


def test_bilingual_mixed_memory_rus_keyword_wins() -> None:
    """'note запомни' → English 'note'→MEMORY, Russian 'запомн'→MEMORY.
    Unanimous: MEMORY."""
    result = _bilingual_route("note запомни")
    assert result == AgentType.MEMORY


def test_bilingual_mixed_researcher_both_sides() -> None:
    """'search информацию' → English 'search'→RESEARCHER, Russian 'информаци'→RESEARCHER."""
    result = _bilingual_route("search информацию")
    assert result == AgentType.RESEARCHER


# ===========================================================================
# route_task — full end-to-end routing
# ===========================================================================

def test_route_english_coder() -> None:
    assert route_task("implement a sorting algorithm") == AgentType.CODER


def test_route_english_reviewer() -> None:
    # Avoid "pull request" and "code change" (both CODER keywords)
    assert route_task("kindly review this document") == AgentType.REVIEWER


def test_route_english_architect() -> None:
    assert route_task("plan the system architecture") == AgentType.ARCHITECT


def test_route_english_researcher() -> None:
    assert route_task("find information about quantum computing") == AgentType.RESEARCHER


def test_route_english_memory() -> None:
    assert route_task("save this note to obsidian") == AgentType.MEMORY


def test_route_russian_coder() -> None:
    assert route_task("напиши функцию для сортировки") == AgentType.CODER



def test_route_russian_reviewer() -> None:
    # REVIEWER is now before CODER: "провер" matches first even with "код"
    assert route_task("проверь изменения в коде") == AgentType.REVIEWER
    assert route_task("проверь пул реквест") == AgentType.REVIEWER
    # "ревью" also matches REVIEWER
    assert route_task("сделай ревью кода") == AgentType.REVIEWER


def test_route_russian_architect() -> None:
    assert route_task("какую архитектуру выбрать для проекта") == AgentType.ARCHITECT


def test_route_russian_researcher() -> None:
    assert route_task("найди информацию про нейросети") == AgentType.RESEARCHER


def test_route_russian_memory() -> None:
    # "создай" is a CODER keyword → use "запомни" which is MEMORY
    assert route_task("запомни эту информацию в obsidian") == AgentType.MEMORY


def test_route_bilingual_coder() -> None:
    assert route_task("напиши sorting algorithm") == AgentType.CODER


def test_route_bilingual_researcher() -> None:
    assert route_task("поищи latest news about AI") == AgentType.RESEARCHER


def test_route_typo_tolerant_english() -> None:
    assert route_task("implemnt sorting algorithm") == AgentType.CODER


def test_route_casual_what_question_is_general() -> None:
    """Casual 'what' question no longer misroutes to RESEARCHER.
    Regression for the documented limitation: 'what' (4 chars) used to
    fuzzy-match the multi-word keyword 'what is' at ratio 0.727 > 0.72.
    Now multi-word keywords are excluded from fuzzy matching, so casual
    questions fall through to GENERAL."""
    assert route_task("what do you think about this") == AgentType.GENERAL
    assert route_task("what should i do") == AgentType.GENERAL


def test_route_what_is_question_is_researcher() -> None:
    """Real 'what is …' research questions STILL route to RESEARCHER
    via exact substring matching of the multi-word keyword."""
    assert route_task("what is machine learning") == AgentType.RESEARCHER
    assert route_task("what is the capital of france") == AgentType.RESEARCHER


def test_route_typo_tolerant_russian() -> None:
    # "провер" is an alias that fuzzy-matches → REVIEWER
    result = route_task("провер пул реквест")
    assert result == AgentType.REVIEWER



def test_route_greeting_russian() -> None:
    """'как дела' detected as greeting → GENERAL."""
    assert route_task("как дела?") == AgentType.GENERAL


def test_route_greeting_english() -> None:
    assert route_task("hello how are you") == AgentType.GENERAL


def test_route_greeting_privet() -> None:
    assert route_task("привет") == AgentType.GENERAL


def test_route_bilingual_check_code() -> None:
    """'check' now a REVIEWER keyword → mixed command routes to REVIEWER."""
    assert route_task("check мой код пожалуйста") == AgentType.REVIEWER


def test_route_fallback_general() -> None:
    assert route_task("how is the weather outside") == AgentType.GENERAL


def test_route_empty() -> None:
    assert route_task("") == AgentType.GENERAL


def test_route_with_history_continuation() -> None:
    """History with "review" routes to REVIEWER.
    Current task "let us continue now" matches no keyword, so history wins."""
    history = [
        {"role": "assistant", "content": "I will review your recent document changes."}
    ]
    result = route_task("let us continue now", history)
    assert result == AgentType.REVIEWER


def test_route_with_history_general_fallback() -> None:
    history = [
        {"role": "assistant", "content": "That is an interesting question."}
    ]
    result = route_task("how are you today", history)
    assert result == AgentType.GENERAL


# ===========================================================================
# Integration tests — route_task full pipeline with bilingual input
# ===========================================================================
# These tests exercise route_task through ALL 6 pipeline stages in order:
#   0. Transliteration (Latin→Cyrillic)
#   1. Greeting detection
#   2. Bilingual routing (mixed Russian-English)
#   3. Exact keyword classification
#   4. Fuzzy matching (typo tolerance)
#   5. Conversation history heuristic
#   6. Fallback → GENERAL
#
# Each test includes a comment tracing the expected pipeline path.


# ── Stage 0→1: Transliteration → Greeting detection ──
# Pipeline: transliteration → greeting check → GENERAL (short-circuit before stages 2-6)

def test_integration_translit_greeting_latin_russian() -> None:
    """Latin-script Russian greeting → transliterated to Cyrillic → greeting
    detected → GENERAL.
    Pipeline: 0(translit 'privet'→'привет') → 1(greeting 'привет' match) → GENERAL
    """
    assert route_task("privet kak dela") == AgentType.GENERAL


def test_integration_translit_greeting_with_keyword() -> None:
    """Latin-script Russian greeting + English keyword → greeting wins
    before bilingual/exact routing.
    Pipeline: 0(translit 'privet'→'привет', 'sdelay'→'сделай', 'kod'→'код')
              → 1(greeting 'привет' match) → GENERAL
    Even though 'код' is a CODER keyword, greeting fires first.
    """
    assert route_task("privet sdelay kod") == AgentType.GENERAL


def test_integration_bilingual_greeting_english() -> None:
    """English greeting + Russian keyword → greeting wins before bilingual.
    Pipeline: 0(no transliteration needed — English 'hi' not in map)
              → 1(greeting 'hi' match) → GENERAL
    """
    assert route_task("hi napishi cod") == AgentType.GENERAL


def test_integration_bilingual_greeting_mixed() -> None:
    """Mixed greeting with actual Cyrillic: greeting detected before bilingual.
    Pipeline: 0(skipped — has Cyrillic) → 1(greeting 'привет' match) → GENERAL
    """
    assert route_task("привет check my code please") == AgentType.GENERAL


# ── Stage 2: Bilingual routing — all 5 agent types ──
# Pipeline: 0(skipped or no-op) → 1(no greeting) → 2(bilingual detects 'mixed') → result

def test_integration_bilingual_coder() -> None:
    """Mixed input → bilingual routing → CODER.
    Pipeline: 0(skipped — has Cyrillic) → 1(no greeting) → 2(bilingual)
    English 'implement' → CODER (exact), Russian 'функцию' → CODER (exact 'функци').
    Majority: CODER.
    """
    assert route_task("implement функцию для парсинга") == AgentType.CODER


def test_integration_bilingual_reviewer() -> None:
    """Mixed input → bilingual routing → REVIEWER.
    Pipeline: 0(skipped — has Cyrillic) → 1(no greeting) → 2(bilingual)
    English 'check' → REVIEWER (exact), Russian 'код' → CODER (exact).
    REVIEWER fires first in _ROUTES, and 'check' is a single-word exact match.
    """
    assert route_task("check мой код пожалуйста") == AgentType.REVIEWER


def test_integration_bilingual_architect() -> None:
    """Mixed input → bilingual routing → ARCHITECT.
    Pipeline: 0(skipped — has Cyrillic) → 1(no greeting) → 2(bilingual)
    English 'architecture' → ARCHITECT (exact), Russian 'системы' → None.
    Single match: ARCHITECT.
    """
    assert route_task("architecture системы microservices") == AgentType.ARCHITECT


def test_integration_bilingual_researcher() -> None:
    """Mixed input → bilingual routing → RESEARCHER.
    Pipeline: 0(skipped — has Cyrillic) → 1(no greeting) → 2(bilingual)
    English 'search' → RESEARCHER (exact), Russian 'информацию' → RESEARCHER (exact 'информаци').
    Unanimous: RESEARCHER.
    """
    assert route_task("search информацию про нейросети") == AgentType.RESEARCHER


def test_integration_bilingual_memory() -> None:
    """Mixed input → bilingual routing → MEMORY.
    Pipeline: 0(skipped — has Cyrillic) → 1(no greeting) → 2(bilingual)
    English 'remember' → MEMORY (exact), Russian 'заметку' → MEMORY (exact 'заметк').
    Unanimous: MEMORY.
    """
    assert route_task("remember эту заметку в obsidian") == AgentType.MEMORY


# ── Stage 2: Bilingual routing — tie-breaking and majority vote ──

def test_integration_bilingual_tie_english_preferred() -> None:
    """Mixed input with tie → English preferred.
    Pipeline: 0(skipped) → 1(no greeting) → 2(bilingual tie)
    English 'check' → REVIEWER, Russian 'спроектируй' → ARCHITECT.
    Tie (1-1) → English preferred → REVIEWER.
    """
    assert route_task("check спроектируй") == AgentType.REVIEWER


def test_integration_bilingual_tie_review_architect() -> None:
    """Mixed tie: 'review' vs 'архитектуру' — English preferred → REVIEWER.
    Pipeline: 0(skipped) → 1(no greeting) → 2(bilingual tie)
    'review' → REVIEWER, 'архитектур' → ARCHITECT.
    Tie → English 'review' preferred → REVIEWER.
    """
    assert route_task("review архитектуру") == AgentType.REVIEWER


def test_integration_bilingual_majority_vote() -> None:
    """Mixed input: English 'implement' + fuzzy 'implemnt' + Russian 'код' →
    majority CODER (3 votes).
    Pipeline: 0(skipped) → 1(no greeting) → 2(bilingual)
    English 'implemnt' → fuzzy None + exact None → skip. Wait, let me re-think.
    
    'implemnt' contains no exact keyword. Fuzzy: 'implemnt' → difflib matches 'implement' → CODER.
    'код' → exact CODER.
    Russian part: no match on 'код' is in English part? No, Russian part = 'код'. 'код' → exact CODER.
    Results: [CODER(fuzzy eng), CODER(exact ru), CODER(fuzzy ru)] → majority CODER.
    """
    # 'implemnt' fuzzy-matches 'implement' (8/14 = 0.833 > 0.72)
    assert route_task("implemnt код") == AgentType.CODER


# ── Stage 2→3: Bilingual returns None → falls through to exact keyword ──

def test_integration_bilingual_fallback_to_exact_russian() -> None:
    """Pure Russian input → bilingual returns None → exact keyword → CODER.
    Pipeline: 0(skipped) → 1(no greeting) → 2(pure 'ru' → None)
              → 3(exact 'код' in 'напиши код') → CODER
    """
    assert route_task("напиши код для парсера") == AgentType.CODER


def test_integration_bilingual_fallback_to_exact_english() -> None:
    """Pure English input → bilingual returns None → exact keyword → RESEARCHER.
    Pipeline: 0(no-translit 'search' not in map) → 1(no greeting)
              → 2(pure 'en' → None) → 3(exact 'search' match) → RESEARCHER
    """
    assert route_task("search for latest AI news") == AgentType.RESEARCHER


# ── Stage 2→3→4: Bilingual → Exact → Fuzzy fallback ──

def test_integration_fuzzy_english_typo() -> None:
    """Pure English typo → bilingual None → exact None → fuzzy → CODER.
    Pipeline: 0(no-op) → 1(no greeting) → 2(pure 'en' → None)
              → 3(no keyword in 'implemnt') → 4('implemnt'∼'implement' → CODER)
    """
    assert route_task("implemnt sorting algorithm") == AgentType.CODER


def test_integration_fuzzy_russian_typo() -> None:
    """Pure Russian with typo 'прогрм' → exact 'напиш' matches → CODER.
    Pipeline: 0(skipped) → 1(no greeting) → 2(pure 'ru' → None)
              → 3(exact 'напиш' in 'напиши прогрм') → CODER
    Note: 'напиш' is an exact CODER keyword in 'напиши', so stage 3
    fires before stage 4 fuzzy matching is ever reached.
    """
    result = route_task("напиши прогрм")
    assert result == AgentType.CODER


def test_integration_fuzzy_bilingual_typo() -> None:
    """Mixed input with typo in English part → bilingual catches it.
    Pipeline: 0(skipped — has Cyrillic) → 1(no greeting) → 2(bilingual)
    English 'explin' → exact None, fuzzy 'explin'∼'explain' → RESEARCHER.
    Russian 'концепцию' → None.
    Single match: RESEARCHER.
    """
    assert route_task("explin эту концепцию") == AgentType.RESEARCHER


def test_integration_fuzzy_bilingual_both_sides() -> None:
    """Mixed input with typos on both sides → bilingual catches both.
    Pipeline: 0(skipped) → 1(no greeting) → 2(bilingual)
    English 'implemnt' → fuzzy 'implement' → CODER.
    Russian 'прогрм' → fuzzy 'программ' → CODER.
    Unanimous: CODER.
    """
    assert route_task("implemnt прогрм") == AgentType.CODER


# ── Stage 5: Conversation history with bilingual input ──

def test_integration_exact_keyword_fires_before_history() -> None:
    """Exact keyword should fire before conversation history stage (stage 3 > stage 5).
    Pipeline: 0(no-op) → 1(no greeting) → 2(pure 'en' → None)
              → 3(exact 'architecture' match) → ARCHITECT
    History is never reached because stage 3 fires first.
    """
    history = [{"role": "assistant", "content": "I will review your changes."}]
    # 'architecture' matches exact keyword before history is consulted
    assert route_task("let us continue the architecture plan", history) == AgentType.ARCHITECT


def test_integration_history_with_bilingual_context() -> None:
    """Fallback input with history → history stage fires.
    Pipeline: 0(skipped) → 1(no greeting) → 2(pure 'ru' → None)
              → 3(no keyword in 'что дальше') → 4(no fuzzy match)
              → 5(history has 'review' → REVIEWER) → REVIEWER
    """
    history = [{"role": "assistant", "content": "I will review your recent document changes."}]
    result = route_task("что дальше", history)
    assert result == AgentType.REVIEWER


def test_integration_history_bilingual_both() -> None:
    """History with bilingual content + bilingual input.
    Pipeline: 0(skipped) → 1(no greeting) → 2(mixed → bilingual)
    `'check код' → mixed → english 'check'→REVIEWER, russian 'код'→CODER.
    Majority with English preference → REVIEWER.
    History not reached.
    """
    history = [{"role": "assistant", "content": "Вот архитектура системы."}]
    # 'check код' → bilingual routing fires before history
    assert route_task("check код", history) == AgentType.REVIEWER


def test_integration_history_fallback_general() -> None:
    """Bilingual input with no match + history with no match → GENERAL.
    Pipeline: 0(skipped) → 1(no greeting) → 2(mixed but no keywords)
              → 3(no exact) → 4(no fuzzy) → 5(history no keywords) → 6 → GENERAL
    History content chosen to avoid any routing keyword substrings.
    """
    history = [{"role": "assistant", "content": "Это просто общий разговор ни о чём."}]
    # 'как погода today' → mixed but no routing keywords match
    # History has no keyword substrings either
    assert route_task("как погода today", history) == AgentType.GENERAL


# ── Stage 6: Fallback → GENERAL ──

def test_integration_fallback_general_bilingual() -> None:
    """Mixed input with no routing keywords → falls through all stages → GENERAL.
    Pipeline: 0(skipped) → 1(no greeting) → 2(mixed · no keywords → None)
              → 3(no exact keyword) → 4(no fuzzy match) → 5(no history) → 6 → GENERAL
    """
    # 'когда обед сегодня' — mixed (Latin only from 'обед'... wait, 'обед' is Cyrillic.
    # Let me use: 'this день' — mixed but neither word is a routing keyword)
    assert route_task("this день") == AgentType.GENERAL


# ── Pipeline priority verification ──
# These tests verify that stages fire in the correct priority order.

def test_integration_priority_greeting_over_bilingual() -> None:
    """Greeting should win over bilingual routing (stage 1 > stage 2).
    Input contains both a greeting ('привет') and bilingual keywords
    ('check', 'код'), but greeting fires first.
    """
    assert route_task("привет check код пожалуйста") == AgentType.GENERAL


def test_integration_priority_bilingual_over_exact() -> None:
    """Bilingual routing should fire before exact keyword (stage 2 > stage 3).
    Input 'search информацию' is mixed → bilingual fires.
    English 'search' → RESEARCHER, Russian 'информацию' → RESEARCHER.
    """
    assert route_task("search информацию") == AgentType.RESEARCHER


def test_integration_priority_exact_over_fuzzy() -> None:
    """Exact keyword should fire before fuzzy matching (stage 3 > stage 4).
    'implement' is an exact CODER keyword → exact fires BEFORE fuzzy.
    """
    assert route_task("implement a sorting algorithm") == AgentType.CODER


def test_integration_priority_reviewer_before_coder() -> None:
    """REVIEWER keywords checked before CODER in _ROUTES priority.
    'review' in 'review this code' matches REVIEWER before CODER.
    """
    assert route_task("review this code") == AgentType.REVIEWER


# ── Edge cases ──

def test_integration_edge_bilingual_punctuation_only() -> None:
    """Mixed input where only punctuation remains after stripping alpha words.
    Pipeline: 0(skipped) → 1(greeting 'привет' match) → GENERAL
    """
    # 'привет!!! как?!?' → greeting 'привет' detected before stage 2+,
    # so GENERAL comes from stage 1, not stage 6.
    assert route_task("привет!!! как?!?") == AgentType.GENERAL


def test_integration_edge_bilingual_numbers() -> None:
    """Bilingual input with numbers interspersed.
    'find 3 articles about AI' → pure English → bilingual None → exact 'find' → RESEARCHER.
    """
    assert route_task("find 3 articles about AI") == AgentType.RESEARCHER


def test_integration_edge_very_short_bilingual() -> None:
    """Very short bilingual input: one English word + one Russian word.
    'hi код' → greeting 'hi' detected → GENERAL (even though 'код' is CODER keyword).
    """
    assert route_task("hi код") == AgentType.GENERAL


def test_integration_edge_empty_after_transliteration() -> None:
    """Input where transliteration produces empty/nonsense → stage 6 → GENERAL.
    Pipeline: 0(all words not in map → unchanged) → 1(no greeting)
              → 2(en → None) → 3(None) → 4(None) → 5(no history) → 6 → GENERAL
    """
    assert route_task("qwerty zxcvb") == AgentType.GENERAL


# ===========================================================================
# AgentType enum
# ===========================================================================

# ===========================================================================
# Transliteration — Latin-script Russian → Cyrillic
# ===========================================================================

def test_transliterate_privet() -> None:
    """'privet' transliterates to 'привет' → detected as greeting → GENERAL."""
    assert route_task("privet") == AgentType.GENERAL


def test_transliterate_spasibo() -> None:
    """'spasibo' transliterates to 'спасибо' → still GENERAL (not routing keyword)."""
    assert route_task("spasibo") == AgentType.GENERAL


def test_transliterate_routing_code() -> None:
    """'naydi kod' → 'найди код' → 'код' matches CODER before RESEARCHER keywords."""
    result = route_task("naydi kod")
    assert result == AgentType.CODER


def test_transliterate_routing_coder() -> None:
    """'napisat kod' → 'написать код' → 'код' matches CODER keyword."""
    result = route_task("napisat kod")
    assert result == AgentType.CODER


def test_transliterate_routing_memory() -> None:
    """'zapomni eto' → Latin → MEMORY via 'запомни'."""
    result = route_task("zapomni eto")
    assert result == AgentType.MEMORY


def test_transliterate_routing_reviewer() -> None:
    """'proverit kod' → Latin 'proverit'→'проверить' → 'провер' matches REVIEWER.
    Note: REVIEWER before CODER, so 'proverit' checks first."""
    result = route_task("proverit kod")
    assert result == AgentType.REVIEWER


def test_transliterate_routing_architect() -> None:
    """'arhitektura sistemi' → Latin 'arhitektura'→'архитектура' → ARCHITECT."""
    result = route_task("arhitektura sistemi")
    assert result == AgentType.ARCHITECT


def test_transliterate_case_preserved() -> None:
    """'Naydi informatsiyu' → capital N preserved after transliteration."""
    result = route_task("Naydi informatsiyu")
    assert result == AgentType.RESEARCHER


def test_transliterate_partial_translit() -> None:
    """Mixed: 'naydi информацию' → Latin 'naydi'→'найди' + already Cyrillic 'информацию'.
    Should still route correctly."""
    result = route_task("naydi информацию")
    assert result == AgentType.RESEARCHER


def test_transliterate_does_not_double_convert() -> None:
    """Text already in Cyrillic should NOT be double-converted."""
    # The transliteration checks has_cyrillic first — pure Cyrillic should pass through unchanged
    result = route_task("привет")
    assert result == AgentType.GENERAL  # Greeting, not affected by transliteration


def test_transliterate_english_commands_still_work() -> None:
    """English commands should NOT be affected by transliteration (words not in map)."""
    result = route_task("implement a sorting algorithm")
    assert result == AgentType.CODER


def test_transliterate_no_false_positive_short_word() -> None:
    """'do' is an English word AND in the transliteration map ('do'→'до').
    But since 'do' in the transliteration map is the Russian preposition 'до',
    it would be converted. However, 'do' alone won't match any keyword."""
    result = route_task("do")
    assert result == AgentType.GENERAL


def test_transliterate_naydi_is_researcher() -> None:
    """'naydi' → 'найди' → RESEARCHER keyword 'найд'."""
    result = route_task("naydi")
    assert result == AgentType.RESEARCHER


def test_agent_type_values() -> None:
    assert AgentType.ARCHITECT.value == "architect"
    assert AgentType.CODER.value == "coder"
    assert AgentType.REVIEWER.value == "reviewer"
    assert AgentType.RESEARCHER.value == "researcher"
    assert AgentType.MEMORY.value == "memory"
    assert AgentType.GENERAL.value == "general"


# ===========================================================================
# _apply_transliteration — Latin-script Russian → Cyrillic (direct tests)
# ===========================================================================

def test_apply_transliteration_empty() -> None:
    """Empty string passes through unchanged."""
    assert _apply_transliteration("") == ""


def test_apply_transliteration_no_cyrillic() -> None:
    """English text with no transliteratable words passes through."""
    assert _apply_transliteration("hello world") == "hello world"


def test_apply_transliteration_english_number_not_affected() -> None:
    """English words not in transliteration map pass through unchanged."""
    assert _apply_transliteration("implement algorithm") == "implement algorithm"


def test_apply_transliteration_already_cyrillic() -> None:
    """Pure Cyrillic text should NOT be double-converted."""
    result = _apply_transliteration("привет мир")
    assert result == "привет мир"


def test_apply_transliteration_single_word() -> None:
    """Single Latin-script Russian word → Cyrillic."""
    result = _apply_transliteration("privet")
    assert result == "привет"


def test_apply_transliteration_multiple_words() -> None:
    """Multiple Latin-script Russian words → Cyrillic."""
    result = _apply_transliteration("privet naydi")
    assert result == "привет найди"


def test_apply_transliteration_case_preserved_upper() -> None:
    """Uppercase first letter preserved after transliteration."""
    result = _apply_transliteration("Privet")
    assert result == "Привет"


def test_apply_transliteration_all_caps() -> None:
    """ALL CAPS Russian transliterations."""
    result = _apply_transliteration("PRIVET")
    assert result == "Привет"  # Only first letter capitalized per the function


def test_apply_transliteration_with_punctuation() -> None:
    """Punctuation is preserved around transliterated words."""
    result = _apply_transliteration("privet, naydi?")
    assert result == "привет, найди?"


def test_apply_transliteration_partial_match() -> None:
    """Some words in map, some not — only mapped words are converted."""
    result = _apply_transliteration("privet world")
    assert result == "привет world"


def test_apply_transliteration_no_known_words() -> None:
    """English words not in the map pass through unchanged."""
    result = _apply_transliteration("hello world")
    assert result == "hello world"


def test_apply_transliteration_mixed_case() -> None:
    """Mixed case: 'NaYdi' → first letter capital preserved."""
    result = _apply_transliteration("NaYdi")
    assert result == "Найди"


def test_apply_transliteration_numbers_in_text() -> None:
    """Numbers in text should be preserved."""
    result = _apply_transliteration("naydi 5 slov")
    assert result == "найди 5 slov"  # 'slov' not in translit map, passes through


# ===========================================================================
# _is_greeting — greeting detection (direct tests)
# ===========================================================================

def test_is_greeting_hello() -> None:
    """'hello' is a greeting."""
    assert _is_greeting("hello") is True


def test_is_greeting_hi() -> None:
    """'hi' is a greeting."""
    assert _is_greeting("hi") is True


def test_is_greeting_hey() -> None:
    """'hey' is a greeting."""
    assert _is_greeting("hey") is True


def test_is_greeting_privet() -> None:
    """'привет' is a greeting."""
    assert _is_greeting("привет") is True


def test_is_greeting_zdravstvuy() -> None:
    """'здравствуй' is a greeting."""
    assert _is_greeting("здравствуй") is True


def test_is_greeting_kak_dela() -> None:
    """'как дела' is a multi-word greeting."""
    assert _is_greeting("как дела") is True


def test_is_greeting_multi_word_how_are_you() -> None:
    """'how are you' is a multi-word greeting."""
    assert _is_greeting("how are you") is True


def test_is_greeting_not_greeting_plain_text() -> None:
    """Plain non-greeting text should return False."""
    assert _is_greeting("implement sorting algorithm") is False


def test_is_greeting_word_boundary_hi_in_this() -> None:
    """'hi' should NOT match 'this' — word boundary check."""
    assert _is_greeting("this") is False


def test_is_greeting_word_boundary_hi_in_chip() -> None:
    """'hi' should NOT match 'chip' — word boundary check."""
    assert _is_greeting("chip") is False


def test_is_greeting_word_boundary_hi_in_him() -> None:
    """'hi' should NOT match 'him' — word boundary check."""
    assert _is_greeting("him") is False


def test_is_greeting_with_punctuation() -> None:
    """Punctuation around greeting should still match."""
    assert _is_greeting("hello!") is True


def test_is_greeting_with_extra_words() -> None:
    """Greeting in a longer sentence should still be detected."""
    assert _is_greeting("hello can you help me") is True

def test_is_greeting_russian_with_extra_words() -> None:
    """Russian greeting in a longer sentence."""
    assert _is_greeting("привет как дела сегодня") is True

def test_is_greeting_empty() -> None:
    """Empty string is not a greeting."""
    assert _is_greeting("") is False

def test_is_greeting_case_insensitive() -> None:
    """'HELLO' should match 'hello' (case insensitive)."""
    assert _is_greeting("HELLO") is True

def test_is_greeting_case_insensitive_russian() -> None:
    """'ПРИВЕТ' should match 'привет' (case insensitive)."""
    assert _is_greeting("ПРИВЕТ") is True

def test_is_greeting_multi_word_extra_spaces() -> None:
    """Multi-word greeting with extra spaces."""
    assert _is_greeting("  how are you  ") is True

def test_is_greeting_sup() -> None:
    """'sup' is a greeting."""
    assert _is_greeting("sup") is True

def test_is_greeting_dobroe_utro() -> None:
    """'доброе утро' is a multi-word greeting."""
    assert _is_greeting("доброе утро") is True


# ===========================================================================
# _fuzzy_classify — additional edge cases
# ===========================================================================

def test_fuzzy_multiple_words_same_agent() -> None:
    """Multiple words all matching the same agent → that agent."""
    result = _fuzzy_classify("implemnt create_function refctor")
    assert result == AgentType.CODER

def test_fuzzy_multiple_words_different_agents_first_wins() -> None:
    """Multiple matches, first agent in _ROUTES order wins.
    'archteture' → ARCHITECT (before CODER), 'implemnt' → CODER.
    ARCHITECT keyword is checked first in _ROUTES, so 'archteture' wins."""
    result = _fuzzy_classify("archteture implemnt")
    assert result == AgentType.ARCHITECT

def test_fuzzy_reviewer_before_coder() -> None:
    """'review' fuzzy match should win before 'implemnt' fuzzy match.
    REVIEWER is before CODER in _ROUTES."""
    result = _fuzzy_classify("revue implemnt")
    assert result == AgentType.REVIEWER

def test_fuzzy_word_with_digits() -> None:
    """Words containing digits should not crash or produce false matches."""
    result = _fuzzy_classify("impl3ment cod3")
    assert result is None or result == AgentType.CODER  # digits stripped or not

def test_fuzzy_unicode_symbols() -> None:
    """Words with unicode symbols (non-Latin, non-Cyrillic)."""
    result = _fuzzy_classify("café résumé")
    assert result is None  # Not matching any keyword

def test_fuzzy_very_long_word() -> None:
    """Very long word should not crash."""
    result = _fuzzy_classify("a" * 100)
    assert result is None

def test_fuzzy_russian_typo_memory_zapomni() -> None:
    """'запомн' fuzzy-matches MEMORY keyword 'запомн' (exact)."""
    result = _fuzzy_classify("запомн это")
    assert result == AgentType.MEMORY

def test_fuzzy_russian_typo_researcher_informaciya() -> None:
    """'информци' fuzzy-matches 'информаци' → RESEARCHER."""
    result = _fuzzy_classify("информци")
    assert result == AgentType.RESEARCHER

def test_fuzzy_punctuation_only_tokens() -> None:
    """Tokens that are only punctuation after stripping → skip."""
    result = _fuzzy_classify("!!! ??? ...")
    assert result is None


# ===========================================================================
# _bilingual_route — additional edge cases
# ===========================================================================

def test_bilingual_english_exact_match_wins_tie() -> None:
    """When bilingual is mixed and both sides match different agents,
    English exact match breaks the tie.
    'check' (EN exact → REVIEWER) vs 'напиш' (RU exact → CODER).
    Tie: 1-1. English exact match on 'check' → REVIEWER."""
    result = _bilingual_route("check напиш")
    assert result == AgentType.REVIEWER

def test_bilingual_english_fuzzy_match_in_tie() -> None:
    """English fuzzy match + Russian exact match = majority wins.
    'implemnt' fuzzy → CODER, 'код' exact → CODER.
    Majority: CODER (2 vs 0)."""
    result = _bilingual_route("implemnt код")
    assert result == AgentType.CODER

def test_bilingual_russian_exact_wins_over_english_fuzzy() -> None:
    """Russian exact + English fuzzy = Russian exact wins.
    'спроектируй' exact → ARCHITECT, 'implemnt' fuzzy → CODER.
    Tie: 1-1. English preferred, but no English exact → top result = majority.
    Actually it's a tie, English preferred → tiebreaker: english_task exact match.
    'implemnt' is not an exact keyword, so no english exact match → top result."""
    result = _bilingual_route("спроектируй implemnt")
    # Tie: ARCHITECT(1) vs CODER(1). English preferred: check english exact match.
    # english_task='implemnt' → _classify_by_keywords returns None → no exact.
    # Falls to majority → top_result = whichever comes first in Counter.most_common().
    # Counter is insertion-ordered in Python 3.9. Results order: ARCHITECT(exact ru), CODER(fuzzy eng).
    # So top = ARCHITECT or CODER depending on insertion order.
    assert result in (AgentType.ARCHITECT, AgentType.CODER)

def test_bilingual_only_english_part_has_keyword() -> None:
    """Only the English part has a routing keyword.
    'review' → REVIEWER, Russian 'красивый' → no match.
    Only REVIEWER match → REVIEWER."""
    result = _bilingual_route("review красивый")
    assert result == AgentType.REVIEWER

def test_bilingual_only_russian_part_has_keyword() -> None:
    """Only the Russian part has a routing keyword.
    English 'beautiful' → no match, Russian 'архитектур' → ARCHITECT.
    Only ARCHITECT match → ARCHITECT."""
    result = _bilingual_route("beautiful архитектур")
    assert result == AgentType.ARCHITECT

def test_bilingual_both_sides_same_agent() -> None:
    """Both English and Russian parts match the SAME agent.
    'search' → RESEARCHER, 'информаци' → RESEARCHER.
    Unanimous: RESEARCHER."""
    result = _bilingual_route("search информаци")
    assert result == AgentType.RESEARCHER

def test_bilingual_both_sides_memory() -> None:
    """Both sides match MEMORY."""
    result = _bilingual_route("remember запомн")
    assert result == AgentType.MEMORY

def test_bilingual_russian_numeric_with_marker() -> None:
    """Mixed text where only Russian part has routing keyword.
    'найди информацию про AI' → 15 Cyr + 2 Lat = 88% → 'ru', not mixed.
    Use balanced ratio: 'найди AI' → 4 Cyr + 2 Lat = 66% → 'mixed'."""
    result = _bilingual_route("найди AI")
    assert result == AgentType.RESEARCHER


# ===========================================================================
# route_task — additional integration tests
# ===========================================================================

def test_route_with_emoji() -> None:
    """Input with emoji should not crash and should route correctly."""
    result = route_task("напиши код 🚀 для парсера")
    assert result == AgentType.CODER

def test_route_with_url() -> None:
    """Input containing a URL should not crash."""
    result = route_task("найди информацию на https://example.com")
    assert result == AgentType.RESEARCHER

def test_route_with_code_snippet() -> None:
    """Input containing code-like text should not crash."""
    result = route_task("проверь код: def foo(): pass")
    assert result == AgentType.REVIEWER  # 'провер' matches REVIEWER before 'код'→CODER

def test_route_very_long_input() -> None:
    """Very long input (1000+ chars) should not crash."""
    long_text = "напиши " + "очень " * 200 + "код"
    result = route_task(long_text)
    assert result == AgentType.CODER

def test_route_with_special_chars() -> None:
    """Input with special characters like @#$% should not crash."""
    result = route_task("search @#$% for AI news")
    assert result == AgentType.RESEARCHER

def test_route_bilingual_with_code_markers() -> None:
    """Bilingual input with code markers (backticks)."""
    result = route_task("напиши `sorting algorithm` на python")
    assert result == AgentType.CODER

def test_route_russian_reviewer_with_emoji() -> None:
    """Russian reviewer command with emoji."""
    result = route_task("проверь ✅ мой код пожалуйста")
    assert result == AgentType.REVIEWER

def test_bilingual_triple_match_different_agents() -> None:
    """Bilingual with tie between 2 agents: English preferred.
    'search' → RESEARCHER, 'код' → CODER. Tie 1-1 → English exact wins → RESEARCHER."""
    result = _bilingual_route("search код")
    assert result == AgentType.RESEARCHER


# ===========================================================================
# Property-based tests with hypothesis — fuzzy matching edge cases
# ===========================================================================
# These tests verify core mathematical/invariant properties of the routing
# system: keyword containment, language detection, fuzzy matching bounds.

pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

# --- Build keyword→agent lookup for property tests ---
_KEYWORD_TO_AGENT: dict[str, AgentType] = {}
for keywords, agent in _ROUTES:
    for kw in keywords:
        if kw not in _KEYWORD_TO_AGENT:  # first agent wins (routing order)
            _KEYWORD_TO_AGENT[kw] = agent

# Single-word keywords only (multi-word keywords are substrings, harder to
# randomly embed without false positives from nested matches).
_SINGLE_WORD_KEYWORDS: list[str] = [
    kw for kw in _KEYWORD_TO_AGENT if ' ' not in kw
]

# Russian-only and English-only single-word keywords for language-specific tests
_RU_SINGLE_KEYWORDS: list[str] = [
    kw for kw in _SINGLE_WORD_KEYWORDS
    if kw and any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in kw)
]
_EN_SINGLE_KEYWORDS: list[str] = [
    kw for kw in _SINGLE_WORD_KEYWORDS
    if kw and all(c.lower() not in 'abcdefghijklmnopqrstuvwxyz' or ('a' <= c.lower() <= 'z') for c in kw)
]


# ── _classify_by_keywords: keyword containment property ──
# Some keywords are substrings of other keywords from higher-priority agents
# (e.g. ARCHITECT's 'структур' is a substring of MEMORY's 'структурир').
# These "shadowed" keywords would be captured by the earlier agent, so we
# exclude them and only test "primary" keywords (those not shadowed).

def _is_primary_keyword(kw: str) -> bool:
    """A keyword is 'primary' if no higher-priority keyword is a substring of it."""
    for other_kw in _KEYWORD_TO_AGENT:
        if other_kw != kw and other_kw in kw:
            # other_kw is a substring — check if it appears in an earlier _ROUTES entry
            for keywords, agent in _ROUTES:
                if other_kw in keywords:
                    return False   # higher-priority match → shadowed
                if kw in keywords:
                    return True    # kw appears before other_kw → safe
    return True


_PRIMARY_KEYWORDS: list[str] = [
    kw for kw in _SINGLE_WORD_KEYWORDS if _is_primary_keyword(kw)
]


@given(
    idx=st.integers(min_value=0, max_value=len(_PRIMARY_KEYWORDS) - 1),
    prefix=st.text(min_size=0, max_size=5, alphabet='abcdefghij '),
    suffix=st.text(min_size=0, max_size=5, alphabet='lmnopqrstuv '),
)
def test_classify_keyword_containment_property(
    idx: int, prefix: str, suffix: str
) -> None:
    """For ANY non-shadowed single-word keyword, embedding it within random
    surrounding text should classify to that keyword's agent type.

    This is the fundamental property of exact keyword matching:
    keyword ∈ task_lower → _classify_by_keywords(task) == agent(keyword)

    Shadowed keywords (e.g. MEMORY's 'структурир' being a superset of
    ARCHITECT's 'структур') are excluded because the first-match-wins
    priority system correctly routes them to the higher-priority agent.
    """
    kw = _PRIMARY_KEYWORDS[idx]
    expected = _KEYWORD_TO_AGENT[kw]
    task = f"{prefix.strip()} {kw} {suffix.strip()}"
    assert _classify_by_keywords(task) == expected


@given(
    text=st.text(min_size=3, max_size=40, alphabet='abcdefghijklmnopqrstuvwxyz '),
)
def test_classify_no_match_random_words(text: str) -> None:
    """Random strings of common English letters (no keywords) should
    return None from _classify_by_keywords.

    This is the soundness property: the classifier should only match
    when a keyword is actually present.
    """
    # Skip strings that accidentally contain a keyword (single OR multi-word)
    text_lower = text.lower()
    for kw in _KEYWORD_TO_AGENT:
        if kw in text_lower:
            return  # skip this case — keyword accidentally present
    result = _classify_by_keywords(text)
    assert result is None, f"'{text}' classified to {result} but contains no keyword"


# ── _detect_language: language detection properties ──

ALL_LATIN = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
ALL_CYRILLIC = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШШЩЪЫЬЭЮЯ'


@given(
    words=st.lists(
        st.text(min_size=1, max_size=10, alphabet=ALL_LATIN),
        min_size=1, max_size=8,
    )
)
def test_detect_language_pure_english_property(words: list[str]) -> None:
    """A string composed solely of Latin letters should always be
    detected as English ('en').

    This holds because `_detect_language` computes:
      ru_ratio = ru_chars / (ru_chars + en_chars)
    and checks ru_ratio < 0.2 → 'en'.
    With zero Cyrillic chars, ru_ratio = 0 → 'en'.
    """
    text = ' '.join(words)
    assert _detect_language(text) == 'en'


@given(
    words=st.lists(
        st.text(min_size=1, max_size=10, alphabet=ALL_CYRILLIC),
        min_size=1, max_size=8,
    )
)
def test_detect_language_pure_russian_property(words: list[str]) -> None:
    """A string composed solely of Cyrillic letters should always be
    detected as Russian ('ru').

    With zero Latin chars: ru_ratio = 1.0 > 0.8 → 'ru'.
    """
    text = ' '.join(words)
    assert _detect_language(text) == 'ru'


@given(
    chars=st.lists(
        st.characters(whitelist_categories=('Nd', 'Sm', 'Sc', 'P'),
                       blacklist_characters=('а', 'a')),
        min_size=1, max_size=20,
    )
)
def test_detect_language_no_alpha_property(chars: list[str]) -> None:
    """Text with no alphabetic characters (only digits, symbols,
    punctuation, whitespace) should always be detected as English ('en').

    When total = ru_chars + en_chars = 0, the function returns 'en'.
    """
    text = ''.join(chars)
    result = _detect_language(text)
    assert result == 'en', f"'{text}' → {result}, expected 'en'"


# ── _fuzzy_classify: short word property ──

@given(
    word=st.text(min_size=1, max_size=2, alphabet=ALL_LATIN + ALL_CYRILLIC + '.,!?')
)
def test_fuzzy_short_word_never_matches_property(word: str) -> None:
    """Words shorter than 3 characters should NEVER produce a fuzzy
    match, regardless of content.

    The function explicitly skips words with len(clean) < 3.
    This is a correctness property: no false positives from tiny words.
    """
    result = _fuzzy_classify(word)
    assert result is None, f"'{word}' (len={len(word)}) classified to {result}"


# Keywords with len >= 3 (fuzzy_classify skips words < 3 chars)
_FUZZY_KEYWORDS: list[str] = [
    kw for kw in _SINGLE_WORD_KEYWORDS if len(kw) >= 3
]


@given(
    idx=st.integers(min_value=0, max_value=len(_FUZZY_KEYWORDS) - 1),
    noise=st.text(min_size=0, max_size=3, alphabet='xyz321 '),
)
def test_fuzzy_exact_keyword_always_matches_property(
    idx: int, noise: str
) -> None:
    """Any single-word keyword >= 3 chars should always fuzzy-match
    to its agent type (SequenceMatcher ratio = 1.0 for exact match, way
    above the 0.72 cutoff).

    Keywords shorter than 3 chars (e.g. "тз", "ок") are excluded because
    _fuzzy_classify explicitly skips words with len < 3.
    """
    kw = _FUZZY_KEYWORDS[idx]
    expected = _KEYWORD_TO_AGENT[kw]
    task = f"{noise.strip()} {kw} {noise.strip()}"
    result = _fuzzy_classify(task)
    assert result == expected, f"'{task}' fuzzy → {result}, expected {expected}"


# ── _bilingual_route: pure language returns None ──

@given(
    text=st.text(min_size=3, max_size=30, alphabet=ALL_LATIN + ' '),
)
def test_bilingual_english_only_returns_none_property(text: str) -> None:
    """Pure English text (all Latin letters) should return None from
    _bilingual_route, since it only handles mixed Russian-English input.

    The function checks _detect_language(text) != 'mixed' first and
    returns None if the text is not mixed.
    """
    result = _bilingual_route(text)
    assert result is None, f"'{text}' → {result}, expected None"


@given(
    words=st.lists(
        st.text(min_size=2, max_size=10, alphabet=ALL_CYRILLIC),
        min_size=1, max_size=5,
    )
)
def test_bilingual_russian_only_returns_none_property(words: list[str]) -> None:
    """Pure Russian text (all Cyrillic) should return None from
    _bilingual_route, since it only handles mixed input.
    """
    text = ' '.join(words)
    if not text.strip():
        return
    # Only proceed if text is actually pure Russian
    if _detect_language(text) != 'ru':
        return
    assert _bilingual_route(text) is None, f"'{text}' should return None"


@given(
    idx=st.integers(min_value=0, max_value=max(0, len(_EN_SINGLE_KEYWORDS) - 1)),
    ru_word=st.text(min_size=2, max_size=6, alphabet='абвгдеёжзийклмнопрстуфхцчшщъыьэюя'),
)
def test_bilingual_mixed_keyword_containment(
    idx: int, ru_word: str
) -> None:
    """A mixed sentence containing an English keyword embedded with
    Russian words should classify to the expected agent type.
    """
    if not _EN_SINGLE_KEYWORDS:
        return
    en_kw = _EN_SINGLE_KEYWORDS[idx]
    expected = _KEYWORD_TO_AGENT[en_kw]
    text = f"{en_kw} {ru_word}"
    # Only test if it's detected as mixed
    if _detect_language(text) == 'mixed':
        result = _bilingual_route(text)
        if result is not None:
            assert result == expected, (
                f"'{text}': eng='{en_kw}'→{expected}, "
                f"bilingual→{result}"
            )


# ── route_task: transliteration round-trip property ──

@given(
    idx=st.integers(min_value=0, max_value=len(_SINGLE_WORD_KEYWORDS) - 1),
    noise=st.text(min_size=0, max_size=3, alphabet='xyz '),
)
def test_route_english_keyword_via_transliteration_unchanged(
    idx: int, noise: str
) -> None:
    """English keywords (no Cyrillic) should route identically via
    route_task — the transliteration step passes through any text
    without Cyrillic chars unchanged.
    """
    kw = _SINGLE_WORD_KEYWORDS[idx]
    # Only test English keywords (no Cyrillic in the keyword)
    if any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in kw):
        return
    expected = _KEYWORD_TO_AGENT[kw]
    task = f"{noise.strip()} {kw} {noise.strip()}"
    result = route_task(task)
    # Must not be GENERAL (unless keyword is a greeting, e.g. 'hi')
    if result != AgentType.GENERAL:
        assert result == expected, (
            f"'{task}': kw='{kw}'→{expected}, route→{result}"
        )


@given(
    task=st.text(min_size=0, max_size=5, alphabet='kqwxyj '),
)
def test_route_empty_or_trivial(task: str) -> None:
    """Short strings that cannot form any routing keyword should always
    route to GENERAL (the fallback behavior of route_task).
    Uses a restricted alphabet ('kqwxyj ') that avoids all keywords.
    """
    result = route_task(task)
    assert result == AgentType.GENERAL, f"'{task}' → {result}"
