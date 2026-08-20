"""Tests for Freebuff Tmux Bridge.

Covers:
- Parser: ANSI cleanup, box-drawing removal, response extraction, completion detection
- Session: tmux lifecycle, send/capture, readiness, crash recovery
- Bridge: BrainInterface contract, ensure_session, fallback, status
- Integration: end-to-end with mocked tmux
"""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestTmuxParser:
    """Tests for freebuff_tmux_parser."""

    def test_strip_ansi_csi(self):
        from modules.brain.freebuff_tmux_parser import strip_ansi
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"
        assert strip_ansi("\x1b[1;32mgreen\x1b[0m") == "green"

    def test_strip_ansi_osc(self):
        from modules.brain.freebuff_tmux_parser import strip_ansi
        assert strip_ansi("\x1b]0;title\x07") == ""
        assert strip_ansi("before\x1b]0;title\x07after") == "beforeafter"

    def test_strip_ansi_cursor_positioning(self):
        from modules.brain.freebuff_tmux_parser import strip_ansi
        assert strip_ansi("\x1b[1;1H") == ""
        assert strip_ansi("\x1b[24;51H") == ""
        assert strip_ansi("text\x1b[10;20Hmore") == "textmore"

    def test_strip_control_chars(self):
        from modules.brain.freebuff_tmux_parser import strip_control_chars
        assert strip_control_chars("hello\x00world") == "helloworld"
        assert strip_control_chars("a\x01b\x02c") == "abc"
        assert strip_control_chars("a\tb\nc\rd") == "a\tb\nc\rd"

    def test_strip_box_drawing(self):
        from modules.brain.freebuff_tmux_parser import strip_box_drawing
        assert strip_box_drawing("╔════╗") == ""
        assert strip_box_drawing("║ text ║") == " text "
        assert strip_box_drawing("hello ══ world") == "hello  world"

    def test_preserves_prompt_char(self):
        """Prompt character ❯ (U+276F) must NOT be stripped."""
        from modules.brain.freebuff_tmux_parser import strip_box_drawing, clean_capture
        assert "❯" in strip_box_drawing("❯")
        assert "❯" in clean_capture("Some UI\n❯")

    def test_normalize_whitespace(self):
        from modules.brain.freebuff_tmux_parser import normalize_whitespace
        assert normalize_whitespace("  hello   world  ") == "hello world"
        assert normalize_whitespace("line1\n\n\nline2") == "line1\nline2"
        assert normalize_whitespace("") == ""

    def test_clean_capture_full_pipeline(self):
        from modules.brain.freebuff_tmux_parser import clean_capture
        raw = "\x1b[38;2;241;245;249m\x1b[49m╔═══╗\x1b[0m"
        result = clean_capture(raw)
        assert "╔" not in result
        assert "\x1b" not in result

    def test_clean_capture_empty(self):
        from modules.brain.freebuff_tmux_parser import clean_capture
        assert clean_capture("") == ""
        assert clean_capture(None) == ""

    def test_detect_ready_with_prompt(self):
        from modules.brain.freebuff_tmux_parser import detect_ready
        assert detect_ready("Some UI\n❯") is True
        assert detect_ready("Output\n>") is True
        assert detect_ready("") is False

    def test_detect_ready_no_thinking(self):
        from modules.brain.freebuff_tmux_parser import detect_ready
        assert detect_ready("thinking...") is False
        assert detect_ready("analyzing code...") is False

    def test_detect_response_complete_with_prompt(self):
        from modules.brain.freebuff_tmux_parser import detect_response_complete
        assert detect_response_complete("Response text\n❯") is True
        assert detect_response_complete("Done.\n>") is True

    def test_detect_response_complete_thinking(self):
        from modules.brain.freebuff_tmux_parser import detect_response_complete
        assert detect_response_complete("thinking about...") is False
        assert detect_response_complete("processing...") is False

    def test_detect_response_complete_spinner(self):
        from modules.brain.freebuff_tmux_parser import detect_response_complete
        assert detect_response_complete("⠋ working...") is False
        assert detect_response_complete("⠙ loading...") is False

    def test_extract_response_basic(self):
        from modules.brain.freebuff_tmux_parser import extract_response
        raw = "user message\nHello! I can help with that.\n❯"
        result = extract_response(raw, input_text="user message")
        assert "user message" not in result
        assert "Hello! I can help with that." in result

    def test_extract_response_filters_tui_chrome(self):
        from modules.brain.freebuff_tmux_parser import extract_response
        raw = "❯\n>\n▶\nReal response here\n✕\n● Thinking..."
        result = extract_response(raw)
        assert "Real response here" in result

    def test_extract_response_empty(self):
        from modules.brain.freebuff_tmux_parser import extract_response
        assert extract_response("") == ""
        assert extract_response(None) == ""

    def test_extract_streaming_chunks(self):
        from modules.brain.freebuff_tmux_parser import extract_streaming_chunks
        current = "Line 1\nLine 2\nLine 3\n❯"
        previous = "Line 1\n❯"
        chunks = extract_streaming_chunks(current, previous)
        assert "Line 2" in chunks
        assert "Line 3" in chunks

    def test_extract_streaming_chunks_empty(self):
        from modules.brain.freebuff_tmux_parser import extract_streaming_chunks
        assert extract_streaming_chunks("", "") == []


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------

class TestTmuxSession:
    """Tests for FreebuffTmuxSession."""

    def test_config_from_env(self):
        from modules.brain.freebuff_tmux_session import tmux_config_from_env
        with patch.dict(os.environ, {
            "FREEBUFF_TMUX_SESSION": "test-session",
            "FREEBUFF_BINARY": "test-freebuff",
            "FREEBUFF_CWD": "/tmp",
        }):
            config = tmux_config_from_env()
            assert config.session_name == "test-session"
            assert config.binary == "test-freebuff"
            assert config.cwd == "/tmp"

    def test_config_defaults(self):
        from modules.brain.freebuff_tmux_session import tmux_config_from_env
        with patch.dict(os.environ, {}, clear=True):
            config = tmux_config_from_env()
            assert config.session_name == "fol-freebuff"
            assert config.binary == "freebuff"

    def test_session_state_enum(self):
        from modules.brain.freebuff_tmux_session import TmuxSessionState
        assert TmuxSessionState.CREATED.value == "created"
        assert TmuxSessionState.READY.value == "ready"
        assert TmuxSessionState.ERROR.value == "error"

    @patch("modules.brain.freebuff_tmux_session.session_exists", return_value=False)
    @patch("modules.brain.freebuff_tmux_session._run_tmux", return_value=(0, "", ""))
    def test_check_or_create_new(self, mock_run, mock_exists):
        from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxConfig
        config = TmuxConfig(session_name="test", binary="freebuff")
        session = FreebuffTmuxSession(config)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(session.check_or_create())
        finally:
            loop.close()
        assert result is True
        assert session._info.owned_process is True

    @patch("modules.brain.freebuff_tmux_session.session_exists", return_value=True)
    @patch("modules.brain.freebuff_tmux_session._run_tmux", return_value=(0, "12345\n", ""))
    def test_check_or_create_existing(self, mock_run, mock_exists):
        from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxConfig
        config = TmuxConfig(session_name="test", binary="freebuff")
        session = FreebuffTmuxSession(config)
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(session.check_or_create())
        finally:
            loop.close()
        assert result is True
        assert session._info.owned_process is False

    @patch("modules.brain.freebuff_tmux_session.session_exists", return_value=True)
    @patch("modules.brain.freebuff_tmux_session.capture_pane", return_value="Response text\n❯")
    def test_read_response(self, mock_capture, mock_exists):
        from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxConfig
        config = TmuxConfig(session_name="test", settle_ms=100, response_timeout=2)
        session = FreebuffTmuxSession(config)
        session._previous_capture = "old capture"

        with patch("modules.brain.freebuff_tmux_session.detect_response_complete", return_value=True):
            loop = asyncio.new_event_loop()
            try:
                response = loop.run_until_complete(session.read_response(timeout=2))
            finally:
                loop.close()
            assert "Response text" in response

    @patch("modules.brain.freebuff_tmux_session.session_exists", return_value=True)
    @patch("modules.brain.freebuff_tmux_session.kill_session", return_value=True)
    def test_close_owned(self, mock_kill, mock_exists):
        from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxConfig
        config = TmuxConfig(session_name="test")
        session = FreebuffTmuxSession(config)
        session._info.owned_process = True
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(session.close())
        finally:
            loop.close()
        mock_kill.assert_called_once_with("test")

    @patch("modules.brain.freebuff_tmux_session.session_exists", return_value=True)
    @patch("modules.brain.freebuff_tmux_session.kill_session", return_value=True)
    def test_close_user_owned(self, mock_kill, mock_exists):
        from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxConfig
        config = TmuxConfig(session_name="test")
        session = FreebuffTmuxSession(config)
        session._info.owned_process = False
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(session.close())
        finally:
            loop.close()
        mock_kill.assert_not_called()

    def test_status(self):
        from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxConfig
        config = TmuxConfig(session_name="test")
        session = FreebuffTmuxSession(config)
        status = session.status()
        assert "session_name" in status
        assert "state" in status
        assert status["session_name"] == "test"


# ---------------------------------------------------------------------------
# Bridge tests
# ---------------------------------------------------------------------------

class TestFreebuffTmuxBridge:
    """Tests for FreebuffTmuxBridge BrainInterface."""

    def test_bridge_name(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        assert bridge.name == "freebuff_tmux"

    @patch("modules.brain.freebuff_tmux_bridge.tmux_available", return_value=True)
    @patch("modules.brain.freebuff_tmux_bridge.shutil.which", return_value="/usr/bin/freebuff")
    def test_available(self, mock_which, mock_tmux):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        # Without session or initialization, available is False
        assert bridge.available is False
        # With initialization, available is True
        bridge._initialized = True
        assert bridge.available is True

    @patch("modules.brain.freebuff_tmux_bridge.tmux_available", return_value=False)
    def test_unavailable_no_tmux(self, mock_tmux):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        assert bridge.available is False

    @patch("modules.brain.freebuff_tmux_bridge.tmux_available", return_value=True)
    @patch("modules.brain.freebuff_tmux_bridge.shutil.which", return_value=None)
    def test_unavailable_no_binary(self, mock_which, mock_tmux):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        assert bridge.available is False

    def test_status(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        status = bridge.status()
        assert status["backend"] == "freebuff_tmux"
        assert "tmux_available" in status
        assert "binary_available" in status

    def test_build_prompt_simple(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        messages = [{"role": "user", "content": "Hello"}]
        prompt = bridge._build_prompt(messages, None)
        assert prompt == "Hello"

    def test_build_prompt_with_system(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        messages = [{"role": "user", "content": "Hello"}]
        prompt = bridge._build_prompt(messages, "You are helpful")
        assert "[System: You are helpful]" in prompt
        assert "Hello" in prompt

    def test_build_prompt_multi_turn(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        prompt = bridge._build_prompt(messages, None)
        assert "Hello" in prompt
        assert "Assistant: Hi there!" in prompt
        assert "How are you?" in prompt

    def test_build_prompt_list_content(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        messages = [{"role": "user", "content": [{"type": "text", "text": "Hello"}]}]
        prompt = bridge._build_prompt(messages, None)
        assert prompt == "Hello"

    def test_classify(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        bridge.chat = MagicMock(return_value="greeting")
        result = bridge.classify("Hello!")
        assert result == "greeting"

    def test_plan(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        bridge.chat = MagicMock(return_value="1. Step one\n2. Step two\n3. Step three")
        result = bridge.plan("Build a feature")
        assert len(result) == 3
        assert "Step one" in result[0]

    def test_select_tools(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        bridge.chat = MagicMock(return_value="tool_a\ntool_b")
        tools = [
            {"name": "tool_a", "description": "Tool A"},
            {"name": "tool_b", "description": "Tool B"},
            {"name": "tool_c", "description": "Tool C"},
        ]
        result = bridge.select_tools("Do something", tools)
        assert "tool_a" in result
        assert "tool_b" in result
        assert "tool_c" not in result

    def test_summarize(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        bridge.chat = MagicMock(return_value="Short summary of the text.")
        result = bridge.summarize("Long text that needs summarizing.")
        assert result == "Short summary of the text."

    def test_verify(self):
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        bridge.chat = MagicMock(return_value="supported")
        result = bridge.verify("claim", "evidence")
        assert result == "supported"


# ---------------------------------------------------------------------------
# Integration tests (mocked tmux)
# ---------------------------------------------------------------------------

class TestTmuxBridgeIntegration:
    """Integration tests with mocked tmux commands."""

    def test_ensure_session_and_send(self):
        """Test full flow: create session -> send -> receive."""
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxConfig

        bridge = FreebuffTmuxBridge()
        session = FreebuffTmuxSession(TmuxConfig(session_name="test"))
        session._info.owned_process = True
        bridge._session = session
        bridge._initialized = True

        session.send_message = AsyncMock(return_value=True)
        session.read_response = AsyncMock(return_value="Response from Freebuff")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(bridge._send_and_receive("user message"))
        finally:
            loop.close()
        assert result == "Response from Freebuff"

    def test_chat_calls_send_and_receive(self):
        """Test that chat() calls _send_and_receive with built prompt."""
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        bridge._send_and_receive = MagicMock(return_value="Hello from Freebuff")

        result = bridge.chat(
            [{"role": "user", "content": "Hi"}],
            system="You are helpful",
        )
        assert result == "Hello from Freebuff"

    def test_acomplete(self):
        """Test async completion."""
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        bridge._send_and_receive = AsyncMock(return_value="Async response")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(bridge.acomplete(
                [{"role": "user", "content": "Hello"}],
            ))
        finally:
            loop.close()
        assert result["content"] == "Async response"
        assert result["tool_calls"] == []
        assert result["stop_reason"] == "end_turn"

    def test_cleanup(self):
        """Test cleanup closes session."""
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        mock_session = AsyncMock()
        bridge._session = mock_session
        bridge._initialized = True

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bridge.cleanup())
        finally:
            loop.close()
        mock_session.close.assert_called_once()
        assert bridge._initialized is False


# ---------------------------------------------------------------------------
# Brain integration
# ---------------------------------------------------------------------------

class TestBrainIntegration:
    """Test that freebuff_tmux integrates with brain system."""

    def test_bridge_creation(self):
        """Test that bridge can be created and has correct name."""
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        assert bridge.name == "freebuff_tmux"

    def test_alias_matching(self):
        """Test that config aliases are recognized."""
        cfg = "freebuff-tmux"
        assert cfg in ("freebuff_tmux", "freebuff-tmux", "freebufftmux")

    def test_model_chain_when_available(self):
        """Test model chain returns correct format."""
        from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
        bridge = FreebuffTmuxBridge()
        # Force available by mocking
        with patch.object(type(bridge), 'available', new_callable=lambda: property(lambda self: True)):
            chain = bridge.model_chain()
            assert len(chain) == 1
            assert "freebuff_tmux" in chain[0]
