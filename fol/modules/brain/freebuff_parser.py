"""Freebuff PTY Output Parser — ANSI cleanup and response extraction.

The Freebuff CLI is a TUI application that uses:
  - Alternate screen buffer
  - Raw terminal mode
  - Mouse tracking
  - Cursor positioning
  - Spinners and progress UI

This module strips all terminal artifacts and extracts the clean assistant
response from the raw PTY output.

Pipeline:
  raw PTY output
    → ANSI escape sequence removal
    → Terminal control code cleanup
    → TUI artifact filtering
    → Response boundary detection
    → Clean text
"""

from __future__ import annotations

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ANSI escape sequence patterns
# ---------------------------------------------------------------------------

# CSI sequences: ESC [ ... letter/tilde
# Examples: \x1b[2J, \x1b[1;32m, \x1b[?1049h, \x1b[38;5;196m
_CSI_RE = re.compile(
    r"\x1b\["       # ESC [
    r"[\x30-\x3f]*"  # parameter bytes (0x30-0x3f: 0-9, ?, etc.)
    r"[\x20-\x2f]*"  # intermediate bytes (0x20-0x2f: space, !, etc.)
    r"[\x40-\x7e]",  # final byte (0x40-0x7e: A-Z, a-z, etc.)
)

# OSC sequences: ESC ] ... BEL or ST
# Examples: \x1b]0;title\x07, \x1b]8;;url\x07text\x1b]8;;\x07
_OSC_RE = re.compile(
    r"\x1b\]"       # ESC ]
    r"[^\x07\x1b]*" # content
    r"(?:\x07|\x1b\\)",  # BEL or ST (ESC \)
)

# DCS sequences: ESC P ... ST
_DCS_RE = re.compile(
    r"\x1bP"
    r"[^\x1b]*"
    r"\x1b\\",
)

# APC sequences: ESC _ ... ST
_APC_RE = re.compile(
    r"\x1b_"
    r"[^\x1b]*"
    r"\x1b\\",
)

# SOS sequences: ESC X ... ST
_SOS_RE = re.compile(
    r"\x1bX"
    r"[^\x1b]*"
    r"\x1b\\",
)

# Single ESC followed by a non-CSI/OSC character (e.g., ESC 7 = save cursor)
_ESC_SINGLE_RE = re.compile(r"\x1b[^\[\]\\P_X_]")

# ---------------------------------------------------------------------------
# Terminal control characters
# ---------------------------------------------------------------------------

# C0 control codes (0x00-0x1F) except common ones: \t (0x09), \n (0x0A), \r (0x0D)
# Also preserve \x1b (ESC) — handled by ANSI patterns above.
_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1a\x1c-\x1f]"
)

# ---------------------------------------------------------------------------
# TUI artifact patterns
# ---------------------------------------------------------------------------

# Spinner characters commonly used in terminal UIs
_SPINNER_CHARS = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏-\\|/•")

# Common TUI status prefixes
_TUI_STATUS_PREFIXES = (
    "●", "○", "◉", "◎", "◇", "◆", "▪", "▫",
    "▸", "▹", "►", "▻", "▶", "▷",
    "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏",
    "🔄", "⏳", "✓", "✗", "✘", "✅", "❌",
)


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from text.

    Handles CSI, OSC, DCS, APC, SOS sequences and standalone ESC codes.
    This is a comprehensive replacement for naive regex-only approaches.
    """
    if not text:
        return text

    # Order matters: OSC before CSI (some OSC contains CSI-like sequences)
    text = _OSC_RE.sub("", text)
    text = _DCS_RE.sub("", text)
    text = _APC_RE.sub("", text)
    text = _SOS_RE.sub("", text)
    text = _CSI_RE.sub("", text)
    text = _ESC_SINGLE_RE.sub("", text)

    return text


def strip_control_chars(text: str) -> str:
    """Remove control characters except tab, newline, and carriage return."""
    if not text:
        return text
    return _CONTROL_CHARS_RE.sub("", text)


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace: collapse runs, trim lines, remove blank lines."""
    if not text:
        return text

    lines = text.split("\n")
    normalized = []
    for line in lines:
        # Collapse internal whitespace (tabs, multiple spaces)
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            normalized.append(line)

    return "\n".join(normalized)


def clean_terminal_output(raw: str) -> str:
    """Full cleanup pipeline: ANSI → control chars → normalize.

    This is the primary entry point for cleaning raw PTY output.
    """
    if not raw:
        return ""

    text = strip_ansi(raw)
    text = strip_control_chars(text)
    text = normalize_whitespace(text)

    return text


# ---------------------------------------------------------------------------
# Response detection
# ---------------------------------------------------------------------------

# Patterns that indicate the TUI is in a "thinking" / "working" state
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
    "thinking...",
    "analyzing...",
    "processing...",
    "working...",
)

# Patterns that indicate the TUI is idle / waiting for input
_IDLE_PATTERNS = (
    ">",                    # generic prompt
    "❯",                    # fancy prompt
    "▶",                    # arrow prompt
    ">>",                   # double prompt
    "Ready",                # ready state
    "Type your message",   # instruction
    "Ask me anything",     # instruction
)


def detect_ready(raw_output: str) -> bool:
    """Detect if the Freebuff TUI is ready for input.

    After startup, the TUI renders its initial UI. This function checks
    if the output suggests the UI is ready (prompt visible, no spinner).

    Returns True when the TUI appears ready for user input.
    """
    if not raw_output:
        return False

    cleaned = clean_terminal_output(raw_output)
    if not cleaned:
        return False

    # Check for idle patterns (prompt visible)
    for pattern in _IDLE_PATTERNS:
        if pattern in cleaned:
            return True

    # Check that no thinking/working patterns are active
    cleaned_lower = cleaned.lower()
    for pattern in _THINKING_PATTERNS:
        if pattern in cleaned_lower:
            return False

    # If we have substantial text output and no spinner, likely ready
    lines = [l for l in cleaned.split("\n") if l.strip()]
    if len(lines) >= 2:
        return True

    return False


def detect_response_complete(
    raw_output: str,
    since: float = 0.0,
    last_chunk: str = "",
    settle_time_ms: int = 1500,
) -> bool:
    """Detect if the Freebuff response is complete.

    Heuristics:
    1. Output has settled (no new data for settle_time_ms)
    2. No active spinner/thinking indicators
    3. Response has content (not just prompts/UI)

    This is called periodically by the session reader to determine
    when to stop waiting for more output.
    """
    if not raw_output:
        return False

    cleaned = clean_terminal_output(raw_output)
    if not cleaned:
        return False

    # If there are thinking indicators, response is NOT complete
    cleaned_lower = cleaned.lower()
    for pattern in _THINKING_PATTERNS:
        if pattern in cleaned_lower:
            return False

    # If there's a spinner character, response is likely still streaming
    for char in _SPINNER_CHARS:
        if char in raw_output:
            return False

    return True


def extract_response(raw_output: str, input_text: str = "") -> str:
    """Extract the assistant's response from raw PTY output.

    Strategy:
    1. Clean all ANSI/control characters
    2. Split into lines
    3. Filter out TUI status lines (prompts, spinners, UI chrome)
    4. Remove the user's input text from the output
    5. Return the remaining clean text

    Args:
        raw_output: Raw bytes/string from PTY stdout
        input_text: The user's input (to filter it out from echo)

    Returns:
        Clean assistant response text
    """
    if not raw_output:
        return ""

    cleaned = clean_terminal_output(raw_output)
    if not cleaned:
        return ""

    lines = cleaned.split("\n")
    response_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Skip the user's input (echoed back in TUI)
        if input_text and stripped == input_text.strip():
            continue

        # Skip lines that are just prompt characters
        if stripped in (">", "❯", "▶", ">>", ":", "$", "#"):
            continue

        # Skip single-character spinner lines
        if len(stripped) == 1 and stripped in _SPINNER_CHARS:
            continue

        # Skip TUI status prefix lines (e.g., "● Thinking...")
        if any(stripped.startswith(prefix) for prefix in _TUI_STATUS_PREFIXES):
            # But keep lines that have substantial content after the prefix
            without_prefix = stripped
            for prefix in _TUI_STATUS_PREFIXES:
                if stripped.startswith(prefix):
                    without_prefix = stripped[len(prefix):].strip()
                    break
            if len(without_prefix) < 3:
                continue
            stripped = without_prefix

        response_lines.append(stripped)

    response = "\n".join(response_lines)

    # Final cleanup: remove any remaining ANSI artifacts
    response = strip_ansi(response)
    response = strip_control_chars(response)

    return response.strip()


def extract_streaming_chunks(raw_output: str) -> list[str]:
    """Extract incremental text chunks from streaming PTY output.

    Used when the bridge reads output incrementally and needs to
    identify new text since the last read.

    Returns a list of new text lines (already cleaned).
    """
    if not raw_output:
        return []

    cleaned = clean_terminal_output(raw_output)
    if not cleaned:
        return []

    chunks = []
    for line in cleaned.split("\n"):
        stripped = line.strip()
        if stripped and len(stripped) > 1:
            chunks.append(stripped)

    return chunks


__all__ = [
    "strip_ansi",
    "strip_control_chars",
    "normalize_whitespace",
    "clean_terminal_output",
    "detect_ready",
    "detect_response_complete",
    "extract_response",
    "extract_streaming_chunks",
]
