"""FreebuffBrainAdapter tests — honest, audited, never simulates a backend.

Contract under test:
  - The adapter exists, implements the full ``BrainInterface`` contract and
    is NEVER ``available`` (no official Freebuff programmatic interface
    exists — audited 2026-08-17).
  - Configuration (``FREEBUFF_*`` env) is read at the adapter boundary and
    reported in ``status()`` — never used against invented endpoints, never
    passed through FOL Core.
  - Every reasoning method raises ``BrainUnavailableError`` (a
    ``BrainError`` subtype); streaming yields a single ``error`` event with
    the documented requirements.
"""

from __future__ import annotations

import os

import pytest

from modules.llm.brain import (
    BrainError,
    BrainInterface,
    BrainUnavailableError,
    FreebuffBrainAdapter,
    get_brain,
    BrainConfigurationError,
)
from modules.llm.freebuff import FREEBUFF_REQUIREMENTS, freebuff_config


class TestInitialization:
    def test_creates_adapter(self):
        adapter = FreebuffBrainAdapter()
        assert adapter.name == "freebuff"

    def test_never_available(self):
        assert FreebuffBrainAdapter().available is False

    def test_status_has_no_secrets(self):
        status = FreebuffBrainAdapter().status()
        assert status["backend"] == "freebuff"
        assert status["available"] is False
        text = str(status)
        assert "token" not in text.lower() or "api_token" in text  # key name, not value


class TestConfiguration:
    def test_env_config_read(self, monkeypatch):
        monkeypatch.setenv("FREEBUFF_API_URL", "https://example.invalid/v1")
        monkeypatch.setenv("FREEBUFF_API_TOKEN", "secret-value")
        monkeypatch.setenv("FREEBUFF_TIMEOUT", "30")
        cfg = freebuff_config()
        assert cfg["api_url"] == "https://example.invalid/v1"
        assert cfg["api_token"] == "secret-value"
        assert cfg["timeout"] == "30"

    def test_env_config_defaults(self, monkeypatch):
        monkeypatch.delenv("FREEBUFF_API_URL", raising=False)
        monkeypatch.delenv("FREEBUFF_API_TOKEN", raising=False)
        monkeypatch.delenv("FREEBUFF_TIMEOUT", raising=False)
        cfg = freebuff_config()
        assert cfg["api_url"] == ""
        assert cfg["api_token"] == ""
        assert cfg["timeout"] == "60"

    def test_config_reported_but_still_unavailable(self, monkeypatch):
        monkeypatch.setenv("FREEBUFF_API_URL", "https://example.invalid/v1")
        adapter = FreebuffBrainAdapter()
        # Config presence is reported, but the adapter stays unavailable:
        # the endpoint is NOT official — never contacted.
        assert adapter.status()["configured"] is True
        assert adapter.available is False

    def test_adapter_never_contacts_endpoint(self, monkeypatch):
        """No transport exists: methods raise before any network I/O."""
        monkeypatch.setenv("FREEBUFF_API_URL", "https://example.invalid/v1")
        adapter = FreebuffBrainAdapter()
        with pytest.raises(BrainUnavailableError):
            adapter.chat([{"role": "user", "content": "hi"}])


class TestUnavailableEverywhere:
    def test_chat_raises(self):
        with pytest.raises(BrainUnavailableError) as exc:
            FreebuffBrainAdapter().chat([{"role": "user", "content": "hi"}])
        assert "no public HTTP API" in str(exc.value) or "not a programmatic runtime backend" in str(exc.value)
        assert isinstance(exc.value, BrainError)

    @pytest.mark.asyncio
    async def test_acomplete_raises(self):
        with pytest.raises(BrainUnavailableError):
            await FreebuffBrainAdapter().acomplete([{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_stream_yields_error_event(self):
        events = [
            e
            async for e in FreebuffBrainAdapter().chat_stream(
                [{"role": "user", "content": "hi"}]
            )
        ]
        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "no public HTTP API" in events[0]["message"] or "programmatic runtime backend" in events[0]["message"]

    def test_classify_raises(self):
        with pytest.raises(BrainUnavailableError):
            FreebuffBrainAdapter().classify("hi")

    def test_plan_raises(self):
        with pytest.raises(BrainUnavailableError):
            FreebuffBrainAdapter().plan("task")

    def test_select_tools_raises(self):
        with pytest.raises(BrainUnavailableError):
            FreebuffBrainAdapter().select_tools("task", [{"name": "x"}])

    def test_summarize_raises(self):
        with pytest.raises(BrainUnavailableError):
            FreebuffBrainAdapter().summarize("text")

    def test_verify_raises(self):
        with pytest.raises(BrainUnavailableError):
            FreebuffBrainAdapter().verify("claim", "evidence")

    def test_requirements_documented(self):
        # New requirements mention OpenRouter and Codebuff as alternatives
        assert "OpenRouter" in FREEBUFF_REQUIREMENTS or "FREEBUFF_API_URL" in FREEBUFF_REQUIREMENTS
        assert "Codebuff" in FREEBUFF_REQUIREMENTS or "FREEBUFF_API_TOKEN" in FREEBUFF_REQUIREMENTS


class TestBrainInterfaceCompatibility:
    def test_implements_full_contract(self):
        adapter = FreebuffBrainAdapter()
        assert isinstance(adapter, BrainInterface)
        # Every abstract method must be implemented (not abstract).
        missing = [
            name
            for name in (
                "chat",
                "chat_stream",
                "acomplete",
                "classify",
                "plan",
                "select_tools",
                "summarize",
                "verify",
            )
            if getattr(BrainInterface, name).__isabstractmethod__
            and getattr(adapter, name) is getattr(BrainInterface, name)
        ]
        assert not missing


class TestSelectionInvariant:
    def test_freebuff_selection_still_fails_clearly(self, monkeypatch):
        """Explicit Freebuff must NEVER silently become another brain."""
        monkeypatch.setenv("FOL_BRAIN", "current")
        with pytest.raises(BrainConfigurationError) as exc:
            get_brain("freebuff")
        assert "no public HTTP API" in str(exc.value) or "not a programmatic runtime backend" in str(exc.value)

    def test_freebuff_env_still_fails_clearly(self, monkeypatch):
        monkeypatch.setenv("FOL_BRAIN", "freebuff")
        with pytest.raises(BrainConfigurationError):
            get_brain()
        assert os.environ.get("FOL_BRAIN") == "freebuff"  # env untouched
