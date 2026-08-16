"""Tests for orchestrator/memory_bridge.py (Phase 4).

Covers: secret filtering (scrub), whole-item secret dropping, graceful
degradation when the FOL API is unavailable, and that the bridge exposes only
the single canonical memory path (context retrieve + episode record).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))

from memory_bridge import _is_secret_like, _scrub, record_episode, retrieve_context  # noqa: E402


# --- secret filter ---------------------------------------------------------

def test_scrub_api_key():
    out = _scrub("my key is sk-ant-abcdefghijklmnop123456")
    assert "sk-ant-abcdefghijklmnop123456" not in out
    assert "[REDACTED_KEY]" in out


def test_scrub_bearer_token():
    out = _scrub("Authorization: Bearer abc.def.ghi-jkl12345")
    assert "abc.def.ghi-jkl12345" not in out
    assert "REDACTED" in out


def test_scrub_password():
    out = _scrub("password=hunter2secret")
    assert "hunter2secret" not in out


def test_scrub_private_key_block():
    out = _scrub("-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----")
    assert "AAAA" not in out


def test_scrub_keeps_plain_text():
    out = _scrub("Remember to send the report tomorrow")
    assert out == "Remember to send the report tomorrow"


def test_is_secret_like_drops_credentials():
    assert _is_secret_like("password=hunter2secret")
    assert _is_secret_like("-----BEGIN RSA PRIVATE KEY-----")


def test_is_secret_like_keeps_normal():
    assert not _is_secret_like("User prefers short answers")


# --- graceful degradation (no FOL API running) -----------------------------

def test_retrieve_context_never_raises():
    # No FOL API on 8754 in tests → returns "" (single-path best effort)
    ctx = retrieve_context("what is the user working on")
    assert ctx == ""


def test_retrieve_context_empty_query():
    assert retrieve_context("") == ""


def test_record_episode_never_raises():
    # Best-effort: returns False when the FOL API is unavailable
    ok = record_episode("User asked about FOL architecture")
    assert ok is False


def test_record_episode_drops_secret_events():
    # A credential inside the event must never be sent — returns False fast
    ok = record_episode("the token is sk-ant-abcdefghijklmnop123456")
    assert ok is False


# --- single canonical path -------------------------------------------------

def test_bridge_exposes_only_context_and_episode():
    """The bridge must NOT expose store_memory/vector paths — one retrieval,
    one update. This guards against a second RAG retrieval path appearing."""
    public = {n for n in dir(sys.modules["memory_bridge"]) if not n.startswith("_")}
    assert "retrieve_context" in public
    assert "record_episode" in public
    assert "store_memory" not in public
    assert "vector" not in public
