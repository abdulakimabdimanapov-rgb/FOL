"""Freebuff Tmux Parser — clean tmux capture-pane output and extract responses.

Unlike the PTY approach, tmux capture-pane gives us the *rendered* screen
content (a snapshot of what's on screen).  This is much easier to parse
because cursor positioning has already been resolved by the terminal
emulator inside tmux.

Pipeline:
    tmux capture-pane -p
        → strip bracketed paste markers
        → strip trailing whitespace per line
        → remove ANSI escape sequences
        → remove Unicode box-drawing / TUI decoration
        → deduplicate consecutive identical lines
        → detect completion markers
        → extract assistant response text
"""

from __future__ import annotations

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI escape sequence patterns
# ---------------------------------------------------------------------------

_CSI_RE = re.compile(
    r"\x1b\["       # ESC [
    r"[\x30-\x3f]*"  # parameter bytes
    r"[\x20-\x2f]*"  # intermediate bytes
    r"[\x40-\x7e]",  # final byte
)

_OSC_RE = re.compile(
    r"\x1b\]"
    r"[^\x07\x1b]*"
    r"(?:\x07|x1b\\\\)",
)

_ESC_SINGLE_RE = re.compile(r"\x1b[^\[\]\\\\P_X_]")

_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f]"
)

# Bracketed paste markers (sent by tmux, must be stripped from output)
_BRACKETED_PASTE_START = re.compile(r"\x1b\[200~")
_BRACKETED_PASTE_END = re.compile(r"\x1b\[201~")

# ---------------------------------------------------------------------------
# TUI decoration
# ---------------------------------------------------------------------------

# Box-drawing characters (Unicode range U+2500–U+257F and extended)
# Excludes U+276F (❮), U+276E (❯) — used as Freebuff prompt
_BOX_DRAWING_RE = re.compile(
    r"[\u2500-\u257F"   # Box Drawing
    r"\u2580-\u259F"    # Block Elements
    r"\u25A0-\u25FF"    # Geometric Shapes
    r"\u2800-\u28FF"    # Braille Patterns
    r"\u2B50-\u2B55"    # Stars / Circles
    r"\u2700-\u276D"    # Dingbats (before ❯)
    r"\u2770-\u27BF"    # Dingbats (after ❯)
    r"\u2190-\u21FF"    # Arrows
    r"\u2600-\u26FF"    # Misc Symbols
    r"\uFE30-\uFE4F"    # CJK Compatibility Forms
    r"\u2000-\u206F"    # General Punctuation (em-dash, etc.)
    r"]+"
)

# Spinner characters
_SPINNER_CHARS = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏-\\|/•")

# TUI status prefixes
_TUI_STATUS_PREFIXES = (
    "●", "○", "◉", "◎", "◇", "◆", "▪", "▫",
    "▸", "▹", "►", "▻", "▶", "▷",
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
    "🔄", "⏳", "✓", "✗", "✘", "✅", "❌",
)

# Patterns that indicate Freebuff is idle / waiting for input
_IDLE_PATTERNS = (
    ">",                    # generic prompt
    "❯",                    # fancy prompt
    "▶",                    # arrow prompt
    ">>",                   # double prompt
    "Ready",                # ready state
    "Type your message",   # instruction
    "Ask me anything",     # instruction
)

# Freebuff-specific TUI chrome (exact-match lines to remove)
_FREEBUFF_CHROME = frozenset((
    "❯", ">", "▶", ">>", ":", "$", "#", "✕",
    "Type your message", "Ask me anything", "Ready",
))


# ---------------------------------------------------------------------------
# Cleanup functions
# ---------------------------------------------------------------------------

def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences."""
    if not text:
        return text
    text = _OSC_RE.sub("", text)
    text = _CSI_RE.sub("", text)
    text = _ESC_SINGLE_RE.sub("", text)
    return text


def strip_control_chars(text: str) -> str:
    """Remove control characters except tab, newline, carriage return."""
    if not text:
        return text
    return _CONTROL_CHARS_RE.sub("", text)


def strip_box_drawing(text: str) -> str:
    """Remove Unicode box-drawing and TUI decoration characters."""
    if not text:
        return text
    return _BOX_DRAWING_RE.sub("", text)


def strip_bracketed_paste(text: str) -> str:
    """Remove bracketed paste start/end markers from output.

    When tmux sends bracketed paste, the start (ESC[200~) and end (ESC[201~)
    markers may appear in captured output. This strips them cleanly.
    """
    if not text:
        return text
    text = _BRACKETED_PASTE_START.sub("", text)
    text = _BRACKETED_PASTE_END.sub("", text)
    return text


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace, trim lines, remove blank lines."""
    if not text:
        return text
    lines = text.split("\n")
    normalized = []
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            normalized.append(line)
    return "\n".join(normalized)


def dedup_lines(lines: list[str]) -> list[str]:
    """Remove consecutive duplicate lines.

    TUIs often repeat the same status line while processing.
    This collapses those duplicates while preserving legitimate
    repeated content.
    """
    if not lines:
        return lines
    result = [lines[0]]
    for line in lines[1:]:
        if line != result[-1]:
            result.append(line)
    return result


def clean_capture(raw: str) -> str:
    """Full cleanup pipeline for tmux capture-pane output.

    This is the primary entry point for cleaning raw tmux output.
    """
    if not raw:
        return ""
    text = strip_bracketed_paste(raw)
    text = strip_ansi(text)
    text = strip_control_chars(text)
    text = strip_box_drawing(text)
    text = normalize_whitespace(text)
    return text


def clean_capture_dedup(raw: str) -> str:
    """Cleanup pipeline with consecutive line deduplication.

    Use this for response extraction where TUI status flicker
    produces duplicate lines.
    """
    if not raw:
        return ""
    text = strip_bracketed_paste(raw)
    text = strip_ansi(text)
    text = strip_control_chars(text)
    text = strip_box_drawing(text)
    # Dedup before normalizing whitespace (preserves line structure)
    lines = [l.rstrip() for l in text.split("\n")]
    lines = dedup_lines(lines)
    text = "\n".join(lines)
    text = normalize_whitespace(text)
    return text


# ---------------------------------------------------------------------------
# Completion detection
# ---------------------------------------------------------------------------

# Patterns that indicate Freebuff is still working
_THINKING_PATTERNS = (
    "thinking",
    "analyzing",
    "processing",
    "working",
    "searching",
    "reading",
    "writing",
    "running",
    "executing",
    "generating",
    "loading",
    "connecting",
    "fetching",
)

# Patterns that indicate Freebuff is in an error, block, or modal state
_ERROR_SCREEN_PATTERNS = (
    ("another freebuff instance took over this account", "Another Freebuff instance took over account"),
    ("only one cli per account can be active at a time", "Only one Freebuff CLI active per account"),
    ("press ctrl+c to exit", "Freebuff session in exit/blocked state"),
    ("sessions used, resets in", "Freebuff daily quota exhausted"),
    ("0 of 7 sessions remaining", "Freebuff daily quota exhausted"),
    ("some models aren't available", "Freebuff regional/model restriction"),
    ("rate limit exceeded", "Freebuff rate limit exceeded"),
    ("unauthorized", "Freebuff unauthorized"),
    ("logged out", "Freebuff logged out"),
)


def detect_error_screen(raw_output: str) -> Optional[str]:
    """Detect if Freebuff is displaying an error or blocked screen."""
    if not raw_output:
        return None
    raw_lower = raw_output.lower()
    for pattern, description in _ERROR_SCREEN_PATTERNS:
        if pattern in raw_lower:
            return description
    return None


def detect_ready(raw_output: str) -> bool:
    """Detect if Freebuff TUI is ready for input after startup.

    Uses tmux capture-pane output to check if the TUI has rendered
    its initial UI with a visible prompt.
    """
    if not raw_output:
        return False
    if detect_error_screen(raw_output):
        return False
    cleaned = clean_capture(raw_output)
    if not cleaned:
        return False

    # Check for idle patterns (prompt visible)
    for pattern in _IDLE_PATTERNS:
        if pattern in cleaned:
            return True

    return False


def detect_response_complete(
    raw_output: str,
    previous_output: str = "",
    settle_time_ms: int = 1500,
) -> bool:
    """Detect if Freebuff has finished responding.

    Strategy (ordered by reliability):
    1. Idle pattern visible (prompt returned) — strongest signal
    2. No thinking/spinner indicators + stable output
    3. Output unchanged for settle_time_ms + no thinking patterns

    Args:
        raw_output: Current tmux capture-pane output
        previous_output: Previous capture (to detect settling)
        settle_time_ms: How long output must be stable (unused here, handled by caller)
    """
    if not raw_output:
        return False

    cleaned = clean_capture(raw_output)
    if not cleaned:
        return False

    # If thinking indicators present, NOT complete
    cleaned_lower = cleaned.lower()
    for pattern in _THINKING_PATTERNS:
        if pattern in cleaned_lower:
            return False

    # If spinner characters present in raw output, likely still streaming
    for char in _SPINNER_CHARS:
        if char in raw_output:
            return False

    # Check for idle patterns — strongest signal of completion
    for pattern in _IDLE_PATTERNS:
        if pattern in cleaned:
            return True

    # If we have substantial non-decorative content and no thinking, probably done
    lines = [l for l in cleaned.split("\n") if l.strip()]
    if len(lines) >= 3:
        return True

    return False


# ---------------------------------------------------------------------------
# Response extraction
# ---------------------------------------------------------------------------

def extract_response(
    raw_output: str,
    input_text: str = "",
    message_sent_at: float = 0.0,
) -> str:
    """Extract the assistant's response from tmux capture-pane output.

    Strategy:
    1. Clean all ANSI/box-drawing/control characters
    2. Dedup consecutive identical lines (TUI flicker)
    3. Split into lines
    4. Filter out TUI chrome (prompts, spinners, status prefixes)
    5. Remove the user's input echo
    6. Remove bracketed paste markers if they leaked through
    7. Return the remaining clean text

    Args:
        raw_output: Raw tmux capture-pane output
        input_text: User's input (to filter out echo)
        message_sent_at: Timestamp when message was sent (to filter old content)

    Returns:
        Clean assistant response text
    """
    if not raw_output:
        return ""

    # Use dedup-aware cleanup
    cleaned = clean_capture_dedup(raw_output)
    if not cleaned:
        return ""

    lines = cleaned.split("\n")
    response_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip bracketed paste markers that leaked through
        if stripped.startswith("\x1b[200") or stripped.startswith("\x1b[201"):
            continue

        # Skip the user's input (echoed in TUI)
        if input_text and stripped == input_text.strip():
            continue

        # Skip lines that are just prompt / chrome characters
        if stripped in _FREEBUFF_CHROME:
            continue

        # Skip single-character spinner lines
        if len(stripped) == 1 and stripped in _SPINNER_CHARS:
            continue

        # Skip TUI status prefix lines
        is_status = False
        for prefix in _TUI_STATUS_PREFIXES:
            if stripped.startswith(prefix):
                without_prefix = stripped[len(prefix):].strip()
                if len(without_prefix) < 3:
                    is_status = True
                    break
                stripped = without_prefix
                break
        if is_status:
            continue

        # Skip Freebuff close button "✕"
        if stripped == "✕":
            continue

        # Skip lines that are purely decorative (e.g. "───────")
        if re.match(r"^[\s\-=_~·•]+$", stripped):
            continue

        response_lines.append(stripped)

    response = "\n".join(response_lines)

    # Final cleanup pass
    response = strip_ansi(response)
    response = strip_control_chars(response)
    response = strip_bracketed_paste(response)
    response = normalize_whitespace(response)

    return response.strip()


def extract_streaming_chunks(raw_output: str, previous: str = "") -> list[str]:
    """Extract new text chunks from tmux capture since previous capture.

    Returns new lines that weren't in the previous output.
    Filters out TUI chrome and spinner characters.
    """
    if not raw_output:
        return []

    current = clean_capture_dedup(raw_output)
    prev = clean_capture_dedup(previous) if previous else ""

    if not current:
        return []

    current_lines = current.split("\n")
    prev_lines = prev.split("\n") if prev else []

    # Simple diff: return lines in current that aren't in previous
    new_lines = []
    for line in current_lines:
        stripped = line.strip()
        if stripped and stripped not in prev_lines:
            # Skip TUI chrome
            if stripped in _FREEBUFF_CHROME:
                continue
            if stripped == "✕":
                continue
            if len(stripped) == 1 and stripped in _SPINNER_CHARS:
                continue
            # Skip purely decorative lines
            if re.match(r"^[\s\-=_~·•]+$", stripped):
                continue
            new_lines.append(stripped)

    return new_lines


__all__ = [
    "strip_ansi",
    "strip_control_chars",
    "strip_box_drawing",
    "strip_bracketed_paste",
    "normalize_whitespace",
    "dedup_lines",
    "clean_capture",
    "clean_capture_dedup",
    "detect_ready",
    "detect_error_screen",
    "detect_response_complete",
    "extract_response",
    "extract_streaming_chunks",
]
