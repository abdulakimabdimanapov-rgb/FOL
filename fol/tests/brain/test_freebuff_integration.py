"""Tests for Freebuff Brain integration.

Tests the Freebuff brain adapter, process manager, and startup flow.
Uses mocking to avoid real API calls during tests.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# FreebuffBrainAdapter tests
# ---------------------------------------------------------------------------


class TestFreebuffBrainAdapter:
    """Tests for FreebuffBrainAdapter."""

    @patch.dict(os.environ, {}, clear=True)
    def test_unavailable_without_openrouter_key(self):
        """Adapter reports unavailable when OPENROUTER_API_KEY is not set."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        assert adapter.available is False
        assert adapter.name == "freebuff"

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=True)
    def test_unavailable_with_empty_key(self):
        """Adapter reports unavailable when OPENROUTER_API_KEY is empty."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        assert adapter.available is False

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
        clear=True,
    )
    def test_available_with_openrouter_key(self):
        """Adapter is available when OPENROUTER_API_KEY is set."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        assert adapter.available is True

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
        clear=True,
    )
    def test_status_shows_integration_method(self):
        """Status correctly reports OpenRouter as integration method."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        status = adapter.status()
        assert status["backend"] == "freebuff"
        assert "OpenRouter" in status["integration"]
        assert status["available"] is True

    @patch.dict(os.environ, {}, clear=True)
    def test_status_unavailable_reason(self):
        """Status shows correct reason when unavailable."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        status = adapter.status()
        assert status["available"] is False
        assert "OPENROUTER_API_KEY" in status["reason"]

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
        clear=True,
    )
    def test_model_chain(self):
        """Model chain includes Freebuff models."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        chain = adapter.model_chain()
        assert len(chain) >= 1
        assert "openrouter/deepseek/deepseek-v4-flash" in chain[0]

    @patch.dict(os.environ, {}, clear=True)
    def test_model_chain_empty_when_unavailable(self):
        """Model chain is empty when adapter is unavailable."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        assert adapter.model_chain() == []

    @patch.dict(os.environ, {}, clear=True)
    def test_chat_raises_when_unavailable(self):
        """chat() raises BrainError when adapter is unavailable."""
        from modules.llm.brain import BrainError
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        with pytest.raises(BrainError):
            adapter.chat([{"role": "user", "content": "hello"}])

    @patch.dict(os.environ, {}, clear=True)
    def test_acomplete_raises_when_unavailable(self):
        """acomplete() raises BrainError when adapter is unavailable."""
        from modules.llm.brain import BrainError
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        with pytest.raises(BrainError):
            asyncio.get_event_loop().run_until_complete(
                adapter.acomplete([{"role": "user", "content": "hello"}])
            )

    @patch.dict(os.environ, {}, clear=True)
    def test_classify_raises_when_unavailable(self):
        """classify() raises BrainError when adapter is unavailable."""
        from modules.llm.brain import BrainError
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        with pytest.raises(BrainError):
            adapter.classify("hello")

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
        clear=True,
    )
    def test_available_providers(self):
        """available_providers returns freebuff/openrouter."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        providers = adapter.available_providers()
        assert "freebuff/openrouter" in providers

    @patch.dict(os.environ, {}, clear=True)
    def test_available_providers_empty_when_unavailable(self):
        """available_providers is empty when unavailable."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        assert adapter.available_providers() == []

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
        clear=True,
    )
    def test_test_connection_string(self):
        """test_connection returns a string."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        result = adapter.test_connection()
        assert isinstance(result, str)

    @patch.dict(os.environ, {}, clear=True)
    def test_test_connection_unavailable(self):
        """test_connection returns failure message when unavailable."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter

        adapter = FreebuffBrainAdapter()
        result = adapter.test_connection()
        assert "unavailable" in result.lower() or "❌" in result


# ---------------------------------------------------------------------------
# FreebuffProcessManager tests
# ---------------------------------------------------------------------------


class TestFreebuffProcessManager:
    """Tests for FreebuffProcessManager."""

    @pytest.mark.asyncio
    async def test_start_unavailable_without_key(self):
        """start() returns False when OPENROUTER_API_KEY is not set."""
        from modules.brain.freebuff_process import (
            FreebuffProcessManager,
            BrainProcessState,
        )

        with patch.dict(os.environ, {}, clear=True):
            manager = FreebuffProcessManager(auto_start=True)
            result = await manager.start()
            assert result is False
            assert manager.status.state == BrainProcessState.ERROR

    @pytest.mark.asyncio
    async def test_start_available_with_key(self):
        """start() returns True when OpenRouter is configured and healthy."""
        from modules.brain.freebuff_process import (
            FreebuffProcessManager,
            BrainProcessState,
        )

        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
            clear=True,
        ):
            manager = FreebuffProcessManager(auto_start=True)
            # Mock the health check to return True
            with patch.object(manager, "_health_check", return_value=True):
                result = await manager.start()
                assert result is True
                assert manager.status.state == BrainProcessState.READY

    @pytest.mark.asyncio
    async def test_stop(self):
        """stop() cleans up resources."""
        from modules.brain.freebuff_process import (
            FreebuffProcessManager,
            BrainProcessState,
        )

        manager = FreebuffProcessManager()
        manager._session = AsyncMock()
        await manager.stop()
        assert manager.status.state == BrainProcessState.STOPPED

    @pytest.mark.asyncio
    async def test_health_check_unavailable(self):
        """health_check() returns False when no API key."""
        from modules.brain.freebuff_process import FreebuffProcessManager

        with patch.dict(os.environ, {}, clear=True):
            manager = FreebuffProcessManager()
            result = await manager.health_check()
            assert result is False

    def test_check_cli_installed(self):
        """_check_cli_installed returns a boolean."""
        from modules.brain.freebuff_process import FreebuffProcessManager

        manager = FreebuffProcessManager()
        result = manager._check_cli_installed()
        assert isinstance(result, bool)

    def test_check_openrouter_config(self):
        """_check_openrouter_config checks OPENROUTER_API_KEY."""
        from modules.brain.freebuff_process import FreebuffProcessManager

        with patch.dict(os.environ, {}, clear=True):
            manager = FreebuffProcessManager()
            assert manager._check_openrouter_config() is False

        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
            clear=True,
        ):
            manager = FreebuffProcessManager()
            assert manager._check_openrouter_config() is True

    def test_status_to_dict(self):
        """status.to_dict() returns a serializable dict."""
        from modules.brain.freebuff_process import BrainProcessStatus

        status = BrainProcessStatus()
        d = status.to_dict()
        assert isinstance(d, dict)
        assert "state" in d
        assert "cli_installed" in d
        assert "openrouter_configured" in d

    def test_status_is_alive(self):
        """is_alive() returns True for READY and BUSY states."""
        from modules.brain.freebuff_process import (
            BrainProcessStatus,
            BrainProcessState,
        )

        ready = BrainProcessStatus(state=BrainProcessState.READY)
        assert ready.is_alive() is True

        busy = BrainProcessStatus(state=BrainProcessState.BUSY)
        assert busy.is_alive() is True

        stopped = BrainProcessStatus(state=BrainProcessState.STOPPED)
        assert stopped.is_alive() is False


# ---------------------------------------------------------------------------
# BrainStartupManager tests
# ---------------------------------------------------------------------------


class TestBrainStartupManager:
    """Tests for BrainStartupManager."""

    @pytest.mark.asyncio
    async def test_initialize_primary_available(self):
        """initialize() returns primary brain when available."""
        from modules.brain.startup import BrainStartupManager

        mock_adapter = MagicMock()
        mock_adapter.available = True
        mock_adapter.name = "freebuff"

        with patch(
            "modules.brain.startup.FreebuffBrainAdapter",
            return_value=mock_adapter,
        ):
            with patch.dict(
                os.environ,
                {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
                clear=True,
            ):
                manager = BrainStartupManager(
                    primary_brain="freebuff",
                    fallback_brains=["current"],
                )
                # Mock process manager
                mock_pm = AsyncMock()
                mock_pm.start = AsyncMock(return_value=True)
                manager._process_managers["freebuff"] = mock_pm

                brain = await manager.initialize()
                assert brain.name == "freebuff"

    @pytest.mark.asyncio
    async def test_initialize_fallback_to_current(self):
        """initialize() falls back to 'current' when freebuff unavailable."""
        from modules.brain.startup import BrainStartupManager

        mock_freebuff = MagicMock()
        mock_freebuff.available = False

        mock_current = MagicMock()
        mock_current.available = True
        mock_current.name = "current"

        with patch(
            "modules.brain.startup.FreebuffBrainAdapter",
            return_value=mock_freebuff,
        ):
            with patch.dict(os.environ, {}, clear=True):
                manager = BrainStartupManager(
                    primary_brain="freebuff",
                    fallback_brains=["current"],
                )
                # Mock process manager to return False
                mock_pm = AsyncMock()
                mock_pm.start = AsyncMock(return_value=False)
                manager._process_managers["freebuff"] = mock_pm

                # Mock get_brain for fallback (imported lazily in _initialize_brain)
                with patch(
                    "modules.llm.brain.get_brain",
                    return_value=mock_current,
                ):
                    brain = await manager.initialize()
                    assert brain.name == "current"

    @pytest.mark.asyncio
    async def test_shutdown(self):
        """shutdown() stops process managers and cleans up."""
        from modules.brain.startup import BrainStartupManager

        manager = BrainStartupManager(
            primary_brain="freebuff",
            fallback_brains=["current"],
        )
        mock_pm = AsyncMock()
        manager._process_managers["freebuff"] = mock_pm
        mock_adapter = MagicMock()
        mock_adapter.cleanup = AsyncMock()
        manager._adapters["freebuff"] = mock_adapter

        await manager.shutdown()
        mock_pm.stop.assert_called_once()
        mock_adapter.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_no_brain(self):
        """health_check() returns offline when no brain is initialized."""
        from modules.brain.startup import BrainStartupManager

        manager = BrainStartupManager()
        result = await manager.health_check()
        assert result["status"] == "offline"

    @pytest.mark.asyncio
    async def test_get_active_brain_raises_when_none(self):
        """get_active_brain() raises when no brain is initialized."""
        from modules.llm.brain import BrainConfigurationError
        from modules.brain.startup import BrainStartupManager

        manager = BrainStartupManager()
        with pytest.raises(BrainConfigurationError):
            await manager.get_active_brain()


# ---------------------------------------------------------------------------
# get_brain() factory tests
# ---------------------------------------------------------------------------


class TestGetBrainFactory:
    """Tests for get_brain() factory function."""

    @patch.dict(os.environ, {}, clear=True)
    def test_get_brain_current(self):
        """get_brain('current') returns CurrentLLMAdapter."""
        from modules.llm.brain import CurrentLLMAdapter, get_brain

        brain = get_brain("current")
        assert isinstance(brain, CurrentLLMAdapter)

    @patch.dict(os.environ, {}, clear=True)
    def test_get_brain_default(self):
        """get_brain() defaults to 'current'."""
        from modules.llm.brain import CurrentLLMAdapter, get_brain

        brain = get_brain()
        assert isinstance(brain, CurrentLLMAdapter)

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
        clear=True,
    )
    def test_get_brain_freebuff(self):
        """get_brain('freebuff') returns BrainRouter with Freebuff adapter."""
        from modules.llm.brain_router import BrainRouter
        from modules.llm.brain import get_brain

        brain = get_brain("freebuff")
        assert isinstance(brain, BrainRouter)

    @patch.dict(os.environ, {}, clear=True)
    def test_get_brain_freebuff_unavailable(self):
        """get_brain('freebuff') raises when OpenRouter key is missing."""
        from modules.llm.brain import BrainConfigurationError, get_brain

        with pytest.raises(BrainConfigurationError):
            get_brain("freebuff")

    @patch.dict(os.environ, {}, clear=True)
    def test_get_brain_unknown(self):
        """get_brain('unknown') raises BrainConfigurationError."""
        from modules.llm.brain import BrainConfigurationError, get_brain

        with pytest.raises(BrainConfigurationError):
            get_brain("unknown")


# ---------------------------------------------------------------------------
# BrainRouter with Freebuff adapter tests
# ---------------------------------------------------------------------------


class TestBrainRouterWithFreebuff:
    """Tests for BrainRouter composing Freebuff + Current backends."""

    @patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "sk-or-test-key-12345"},
        clear=True,
    )
    def test_router_with_freebuff_primary(self):
        """Router with Freebuff primary uses Freebuff when available."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter
        from modules.llm.brain import CurrentLLMAdapter
        from modules.llm.brain_router import BrainRouter

        freebuff = FreebuffBrainAdapter()
        current = CurrentLLMAdapter()
        router = BrainRouter([freebuff, current])

        assert router.available is True
        # First available backend should be Freebuff
        assert router._first_available().name == "freebuff"

    @patch.dict(os.environ, {}, clear=True)
    @patch('modules.llm.router.load_dotenv')
    def test_router_fallback_to_current(self, mock_load_dotenv):
        """Router falls back to Current when Freebuff is unavailable."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter
        from modules.llm.brain_router import BrainRouter

        freebuff = FreebuffBrainAdapter()
        # Mock CurrentLLMAdapter as available (has configured models)
        mock_current = MagicMock()
        mock_current.name = "current"
        mock_current.available = True
        router = BrainRouter([freebuff, mock_current])

        assert router.available is True
        # Freebuff is unavailable, so Current should be first available
        assert router._first_available().name == "current"

    @patch.dict(os.environ, {}, clear=True)
    def test_router_status_shows_chain(self):
        """Router status shows the full chain."""
        from modules.brain.freebuff_adapter import FreebuffBrainAdapter
        from modules.llm.brain import CurrentLLMAdapter
        from modules.llm.brain_router import BrainRouter

        freebuff = FreebuffBrainAdapter()
        current = CurrentLLMAdapter()
        router = BrainRouter([freebuff, current])

        status = router.status()
        assert "chain" in status
        assert len(status["chain"]) == 2
        assert status["chain"][0]["backend"] == "freebuff"
        assert status["chain"][1]["backend"] == "current"
