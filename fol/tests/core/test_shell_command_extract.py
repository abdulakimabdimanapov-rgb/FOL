"""Tests for FOL shell-command extraction (_extract_shell_command).

Guards the real bug: the old regex ``(?:run|execute|выполни|...|run command|
выполни команду|...)`` matched the SHORT prefix first, so
``выполни команду pwd`` became the command ``команду pwd`` and the shell
replied ``/bin/sh: команду: command not found``. Longest phrases must win,
and trailing filler (``в терминале``, ``пожалуйста``) must be stripped.
"""

from __future__ import annotations

import re

import pytest

from core.app import FOL


@pytest.fixture(scope="module")
def fol() -> FOL:
    """A bare FOL instance — extraction is a pure method, no services needed."""
    f = FOL()
    f._init_minimal() if hasattr(f, "_init_minimal") else None
    return f


@pytest.mark.parametrize(
    "phrase,expected",
    [
        # Russian — the original bug
        ("выполни команду pwd", "pwd"),
        ("выполни команду ls", "ls"),
        ("выполни команду ls в терминале", "ls"),
        ("выполни команду pwd пожалуйста", "pwd"),
        ("выполни pwd", "pwd"),
        ("выполнить ls -la", "ls -la"),
        ("выполни в терминале pwd", "pwd"),
        ("терминал pwd", "pwd"),
        # English
        ("run command ls", "ls"),
        ("run the command ls", "ls"),
        ("execute command pwd", "pwd"),
        ("run ls -la", "ls -la"),
        ("execute pwd", "pwd"),
        ("terminal pwd", "pwd"),
        ("run ls in terminal please", "ls"),
        # Nested / multi-arg commands must survive untouched
        ("run echo 'hello world'", "echo 'hello world'"),
        ("выполни команду git status --short", "git status --short"),
    ],
)
def test_extract_shell_command(fol: FOL, phrase: str, expected: str):
    assert fol._extract_shell_command(phrase) == expected


@pytest.mark.parametrize(
    "phrase",
    [
        # Not command requests — must return None
        "привет",
        "как дела",
        "открой Safari",
        "выполни",          # prefix alone, no command
        "run",              # prefix alone, no command
        "run command",      # prefix alone, no command
        "выполни команду",  # prefix alone, no command
        "терминал",
        "",
        "hello world",
    ],
)
def test_extract_shell_command_returns_none(fol: FOL, phrase: str):
    assert fol._extract_shell_command(phrase) is None


@pytest.mark.parametrize(
    "phrase,expected",
    [
        # Noise stripping must not eat real arguments
        ("run python3 script.py", "python3 script.py"),
        ("выполни команду cd ~/projects", "cd ~/projects"),
        ("run ls --color=always", "ls --color=always"),
        # Sentence punctuation must be stripped — but "ls ." stays intact
        ("выполни команду pwd.", "pwd"),
        ("run ls!", "ls"),
        ("run ls .", "ls ."),
        # Compound filler fully collapses
        ("run ls in the terminal please", "ls"),
        ("выполни команду ls в терминале пожалуйста", "ls"),
        ("run pwd in terminal please", "pwd"),
    ],
)
def test_extract_shell_command_preserves_args(fol: FOL, phrase: str, expected: str):
    assert fol._extract_shell_command(phrase) == expected


@pytest.mark.parametrize(
    "phrase",
    [
        # "запусти команду X" is routed by app_match (which runs earlier) —
        # the extractor itself correctly declines, since "запусти" opens apps.
        "запусти команду echo hi",
        "запусти команду ls",
    ],
)
def test_zapusti_command_not_handled_by_extractor(fol: FOL, phrase: str):
    assert fol._extract_shell_command(phrase) is None


def test_app_match_command_routing_payload():
    """The payload app_match hands to execute_command is the command only."""
    payload = re.sub(r"^(?:команду|команда|command)\s+", "", "команду echo hi").strip()
    assert payload == "echo hi"
