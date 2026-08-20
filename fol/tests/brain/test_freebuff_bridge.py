"""Tests for Freebuff PTY Bridge.

Tests the parser, session, and bridge modules. Uses mocking to avoid
launching a real Freebuff CLI during tests.

Coverage:
  1. ANSI stripping
  2. Control character removal
  3. Whitespace normalization
  4. Terminal output cleanup
  5. Ready detection
  6. Response complete detection
  7. Response extraction
  8. Streaming chunks
  9. Session state management
  10. Bridge availability
  11. Bridge prompt building
  12. BrainInterface compliance
  13. Configuration
  14. Fallback integration
"""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestStripAnsi:
    """Tests for ANSI escape sequence stripping."""

    def test_empty_string(self):
        from modules.brain.freebuff_parser import strip_ansi
        assert strip_ansi("") == ""

    def test_none_input(self):
        from modules.brain.freebuff_parser import strip_ansi
        result = strip_ansi(None)
        assert result is None or result == ""

    def test_no_ansi(self):
        from modules.brain.freebuff_parser import strip_ansi
        assert strip_ansi("hello world") == "hello world"

    def test_csi_color(self):
        from modules.brain.freebuff_parser import strip_ansi
        # ESC[1;32m = bold green
        assert strip_ansi("\x1b[1;32mhello\x1b[0m") == "hello"

    def test_csi_cursor(self):
        from modules.brain.freebuff_parser import strip_ansi
        # ESC[2J = clear screen
        assert strip_ansi("\x1b[2J") == ""

    def test_csi_question_mode(self):
        from modules.brain.freebuff_parser import strip_ansi
        # ESC[?1049h = enter alternate screen
        assert strip_ansi("\x1b[?1049h") == ""

    def test_osc_title(self):
        from modules.brain.freebuff_parser import strip_ansi
        # ESC]0;titleBEL
        assert strip_ansi("\x1b]0;Freebuff\x07") == ""

    def test_osc_url(self):
        from modules.brain.freebuff_parser import strip_ansi
        # ESC]8;;urlBELtextESC]8;;BEL
        text = "\x1b]8;;https://example.com\x07click here\x1b]8;;\x07"
        assert strip_ansi(text) == "click here"

    def test_dcs(self):
        from modules.brain.freebuff_parser import strip_ansi
        assert strip_ansi("\x1bPsome data\x1b\\") == ""

    def test_apc(self):
        from modules.brain.freebuff_parser import strip_ansi
        assert strip_ansi("\x1b_apc data\x1b\\") == ""

    def test_sos(self):
        from modules.brain.freebuff_parser import strip_ansi
        assert strip_ansi("\x1bXsos data\x1b\\") == ""

    def test_esc_single(self):
        from modules.brain.freebuff_parser import strip_ansi
        # ESC 7 = save cursor, ESC 8 = restore cursor
        assert strip_ansi("\x1b7") == ""

    def test_mixed_content(self):
        from modules.brain.freebuff_parser import strip_ansi
        raw = "\x1b[?1049h\x1b[1;32mHello\x1b[0m\x1b[2J"
        assert strip_ansi(raw) == "Hello"

    def test_preserves_newlines(self):
        from modules.brain.freebuff_parser import strip_ansi
        text = "line1\n\x1b[1mline2\x1b[0m\nline3"
        assert strip_ansi(text) == "line1\nline2\nline3"

    def test_preserves_tabs(self):
        from modules.brain.freebuff_parser import strip_ansi
        text = "\t\x1b[1mtext\x1b[0m"
        assert strip_ansi(text) == "\ttext"


class TestStripControlChars:
    """Tests for control character removal."""

    def test_empty(self):
        from modules.brain.freebuff_parser import strip_control_chars
        assert strip_control_chars("") == ""

    def test_preserves_newline_tab_cr(self):
        from modules.brain.freebuff_parser import strip_control_chars
        text = "hello\t\n\rworld"
        result = strip_control_chars(text)
        assert "hello" in result
        assert "world" in result

    def test_removes_bell(self):
        from modules.brain.freebuff_parser import strip_control_chars
        assert strip_control_chars("hello\x07world") == "helloworld"

    def test_removes_backspace(self):
        from modules.brain.freebuff_parser import strip_control_chars
        assert strip_control_chars("hel\x08lo") == "hello"


class TestNormalizeWhitespace:
    """Tests for whitespace normalization."""

    def test_empty(self):
        from modules.brain.freebuff_parser import normalize_whitespace
        assert normalize_whitespace("") == ""

    def test_collapse_spaces(self):
        from modules.brain.freebuff_parser import normalize_whitespace
        assert normalize_whitespace("hello    world") == "hello world"

    def test_collapse_tabs(self):
        from modules.brain.freebuff_parser import normalize_whitespace
        assert normalize_whitespace("hello\t\tworld") == "hello world"

    def test_trim_lines(self):
        from modules.brain.freebuff_parser import normalize_whitespace
        assert normalize_whitespace("  hello  ") == "hello"

    def test_remove_blank_lines(self):
        from modules.brain.freebuff_parser import normalize_whitespace
        text = "line1\n\n\nline2"
        assert normalize_whitespace(text) == "line1\nline2"


class TestCleanTerminalOutput:
    """Tests for full cleanup pipeline."""

    def test_full_cleanup(self):
        from modules.brain.freebuff_parser import clean_terminal_output
        raw = "\x1b[?1049h\x1b[1;32mHello World\x1b[0m\x1b[?1049l"
        assert clean_terminal_output(raw) == "Hello World"

    def test_complex_tui_output(self):
        from modules.brain.freebuff_parser import clean_terminal_output
        raw = (
            "\x1b[2J\x1b[?1049h"
            "\x1b[1;32m● Freebuff\x1b[0m\n"
            "\x1b[2mReady\x1b[0m\n"
            "\x1b[?1049l"
        )
        cleaned = clean_terminal_output(raw)
        assert "Freebuff" in cleaned
        assert "Ready" in cleaned


class TestDetectReady:
    """Tests for TUI ready detection."""

    def test_empty_output(self):
        from modules.brain.freebuff_parser import detect_ready
        assert detect_ready("") is False

    def test_none_output(self):
        from modules.brain.freebuff_parser import detect_ready
        assert detect_ready(None) is False

    def test_ready_with_prompt(self):
        from modules.brain.freebuff_parser import detect_ready
        assert detect_ready("Ready\n>") is True

    def test_ready_with_substantial_output(self):
        from modules.brain.freebuff_parser import detect_ready
        assert detect_ready("Line 1\nLine 2\nLine 3") is True

    def test_not_ready_thinking(self):
        from modules.brain.freebuff_parser import detect_ready
        assert detect_ready("Thinking...") is False

    def test_not_ready_analyzing(self):
        from modules.brain.freebuff_parser import detect_ready
        assert detect_ready("Analyzing your request...") is False


class TestDetectResponseComplete:
    """Tests for response completion detection."""

    def test_empty(self):
        from modules.brain.freebuff_parser import detect_response_complete
        assert detect_response_complete("") is False

    def test_none(self):
        from modules.brain.freebuff_parser import detect_response_complete
        assert detect_response_complete(None) is False

    def test_complete_response(self):
        from modules.brain.freebuff_parser import detect_response_complete
        assert detect_response_complete("Here is the answer.") is True

    def test_not_complete_thinking(self):
        from modules.brain.freebuff_parser import detect_response_complete
        assert detect_response_complete("Thinking about your question...") is False

    def test_not_complete_spinner(self):
        from modules.brain.freebuff_parser import detect_response_complete
        # Braille spinner characters (from _SPINNER_CHARS set)
        assert detect_response_complete("\u280bLoading...") is False
        assert detect_response_complete("\u280b") is False


class TestExtractResponse:
    """Tests for response extraction."""

    def test_empty(self):
        from modules.brain.freebuff_parser import extract_response
        assert extract_response("") == ""

    def test_none(self):
        from modules.brain.freebuff_parser import extract_response
        assert extract_response(None) == ""

    def test_simple_response(self):
        from modules.brain.freebuff_parser import extract_response
        raw = "Hello, how can I help you?"
        assert extract_response(raw) == "Hello, how can I help you?"

    def test_filters_input_echo(self):
        from modules.brain.freebuff_parser import extract_response
        raw = "What is Python?\nPython is a programming language."
        assert "What is Python?" not in extract_response(raw, input_text="What is Python?")
        assert "Python is a programming language" in extract_response(raw, input_text="What is Python?")

    def test_filters_prompt_chars(self):
        from modules.brain.freebuff_parser import extract_response
        raw = ">\nThe answer is 42.\n>"
        response = extract_response(raw)
        assert ">" not in response
        assert "42" in response

    def test_multiline_response(self):
        from modules.brain.freebuff_parser import extract_response
        raw = "Line 1\nLine 2\nLine 3"
        response = extract_response(raw)
        assert "Line 1" in response
        assert "Line 2" in response
        assert "Line 3" in response

    def test_strips_ansi_from_response(self):
        from modules.brain.freebuff_parser import extract_response
        raw = "\x1b[1mBold text\x1b[0m"
        assert extract_response(raw) == "Bold text"


class TestExtractStreamingChunks:
    """Tests for streaming chunk extraction."""

    def test_empty(self):
        from modules.brain.freebuff_parser import extract_streaming_chunks
        assert extract_streaming_chunks("") == []

    def test_single_line(self):
        from modules.brain.freebuff_parser import extract_streaming_chunks
        chunks = extract_streaming_chunks("Hello world")
        assert "Hello world" in chunks

    def test_multiple_lines(self):
        from modules.brain.freebuff_parser import extract_streaming_chunks
        chunks = extract_streaming_chunks("Line 1\nLine 2\nLine 3")
        assert len(chunks) == 3

    def test_filters_empty_lines(self):
        from modules.brain.freebuff_parser import extract_streaming_chunks
        chunks = extract_streaming_chunks("Line 1\n\n\nLine 2")
        assert len(chunks) == 2


# ---------------------------------------------------------------------------
# Session tests
# ---------------------------------------------------------------------------


class TestSessionState:
    """Tests for session state management."""

    def test_session_state_enum(self):
        from modules.brain.freebuff_session import SessionState
        assert SessionState.CREATED.value == "created"
        assert SessionState.READY.value == "ready"
        assert SessionState.ERROR.value == "error"

    def test_session_config_defaults(self):
        from modules.brain.freebuff_session import SessionConfig
        config = SessionConfig()
        assert config.binary == "freebuff"
        assert config.start_timeout == 15.0
        assert config.response_timeout == 300.0

    def test_create_session_factory(self):
        from modules.brain.freebuff_session import create_session, SessionState
        session = create_session(binary="freebuff", cwd="/tmp")
        assert session.state == SessionState.CREATED
        assert session._config.binary == "freebuff"
        assert session._config.cwd == "/tmp"

    def test_session_not_alive_initially(self):
        from modules.brain.freebuff_session import create_session, SessionState
        session = create_session()
        assert session.is_alive is False
        assert session.state == SessionState.CREATED

    @pytest.mark.asyncio
    async def test_create_fails_without_binary(self):
        from modules.brain.freebuff_session import create_session, SessionState
        session = create_session(binary="nonexistent_binary_12345")
        result = await session.create()
        # Should fail because binary doesn't exist (os.fork will fail)
        # or succeed at fork but child will fail to exec
        # Either way, state should eventually be ERROR or STARTING
        assert session.state in (SessionState.STARTING, SessionState.ERROR)


class TestSessionClose:
    """Tests for session close behavior."""

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        from modules.brain.freebuff_session import create_session, SessionState
        session = create_session()
        await session.close()
        assert session.state == SessionState.CLOSED
        # Closing again should be safe
        await session.close()
        assert session.state == SessionState.CLOSED


# ---------------------------------------------------------------------------
# Bridge tests
# ---------------------------------------------------------------------------


class TestFreebuffBridgeCLI:
    """Tests for FreebuffBridgeCLI BrainInterface implementation."""

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_name(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        assert bridge.name == "freebuff_cli"

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_unavailable_without_binary(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        with patch.object(bridge, "_check_binary", return_value=False):
            assert bridge.available is False

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_model_chain_empty_when_unavailable(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        with patch.object(bridge, "_check_binary", return_value=False):
            assert bridge.model_chain() == []

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_status_dict(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        status = bridge.status()
        assert status["backend"] == "freebuff_cli"
        assert "available" in status
        assert "session_state" in status
        assert "request_count" in status

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_test_connection_no_binary(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        with patch.object(bridge, "_check_binary", return_value=False):
            result = bridge.test_connection()
            assert "not found" in result.lower() or "❌" in result

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_build_prompt_simple(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        messages = [{"role": "user", "content": "Hello"}]
        prompt = bridge._build_prompt(messages, None)
        assert "Hello" in prompt

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_build_prompt_with_system(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        messages = [{"role": "user", "content": "Hello"}]
        prompt = bridge._build_prompt(messages, "You are helpful")
        assert "You are helpful" in prompt
        assert "Hello" in prompt

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_build_prompt_multi_turn(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        messages = [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a language."},
            {"role": "user", "content": "Tell me more."},
        ]
        prompt = bridge._build_prompt(messages, None)
        assert "What is Python?" in prompt
        assert "Python is a language" in prompt
        assert "Tell me more" in prompt

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_build_prompt_with_list_content(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "Hello"},
            ]},
        ]
        prompt = bridge._build_prompt(messages, None)
        assert "Hello" in prompt

    @patch.dict(os.environ, {}, clear=True)
    def test_bridge_available_providers(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        with patch.object(bridge, "_check_binary", return_value=False):
            assert bridge.available_providers() == []

    @patch.dict(os.environ, {"FREEBUFF_BINARY": "custom-freebuff"}, clear=True)
    def test_bridge_reads_config_from_env(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        assert bridge._config["binary"] == "custom-freebuff"

    @patch.dict(os.environ, {"FREEBUFF_CWD": "/my/project"}, clear=True)
    def test_bridge_reads_cwd_from_env(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        assert bridge._config["cwd"] == "/my/project"


class TestBridgeBrainInterface:
    """Tests that FreebuffBridgeCLI implements BrainInterface correctly."""

    def test_is_brain_interface(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        from modules.llm.brain import BrainInterface
        bridge = FreebuffBridgeCLI()
        assert isinstance(bridge, BrainInterface)

    def test_has_required_methods(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        assert hasattr(bridge, "chat")
        assert hasattr(bridge, "chat_stream")
        assert hasattr(bridge, "acomplete")
        assert hasattr(bridge, "classify")
        assert hasattr(bridge, "plan")
        assert hasattr(bridge, "select_tools")
        assert hasattr(bridge, "summarize")
        assert hasattr(bridge, "verify")
        assert hasattr(bridge, "status")
        assert hasattr(bridge, "model_chain")
        assert hasattr(bridge, "available_providers")
        assert hasattr(bridge, "test_connection")

    @patch.dict(os.environ, {}, clear=True)
    def test_chat_raises_when_unavailable(self):
        from modules.llm.brain import BrainError, BrainUnavailableError
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        with patch.object(bridge, "_check_binary", return_value=False):
            with pytest.raises((BrainError, BrainUnavailableError)):
                bridge.chat([{"role": "user", "content": "hello"}])

    @patch.dict(os.environ, {}, clear=True)
    def test_classify_returns_label(self):
        from modules.brain.freebuff_bridge import FreebuffBridgeCLI
        bridge = FreebuffBridgeCLI()
        # Mock the session to avoid real PTY
        with patch.object(bridge, "chat", return_value="command"):
            result = bridge.classify("open VS Code")
            assert result in ("command", "other")


# ---------------------------------------------------------------------------
# get_brain() factory integration
# ---------------------------------------------------------------------------


class TestGetBrainFactoryIntegration:
    """Tests for get_brain() with freebuff_cli option."""

    @patch.dict(os.environ, {}, clear=True)
    def test_get_brain_freebuff_cli_unavailable(self):
        from modules.llm.brain import BrainConfigurationError, get_brain
        with pytest.raises(BrainConfigurationError):
            get_brain("freebuff_cli")

    @patch.dict(os.environ, {}, clear=True)
    def test_get_brain_freebuff_cli_not_found(self):
        from modules.llm.brain import BrainConfigurationError, get_brain
        # Mock binary check to return False
        with patch("modules.brain.freebuff_bridge.FreebuffBridgeCLI._check_binary", return_value=False):
            with pytest.raises(BrainConfigurationError):
                get_brain("freebuff_cli")


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestBridgeConfig:
    """Tests for bridge configuration."""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_config(self):
        from modules.brain.freebuff_bridge import _bridge_config
        config = _bridge_config()
        assert config["binary"] == "freebuff"
        assert config["auto_start"] == "true"
        assert config["start_timeout"] == "15"
        assert config["response_timeout"] == "300"

    @patch.dict(os.environ, {
        "FREEBUFF_BINARY": "my-freebuff",
        "FREEBUFF_CWD": "/tmp/test",
        "FREEBUFF_AUTO_START": "false",
        "FREEBUFF_START_TIMEOUT": "30",
        "FREEBUFF_RESPONSE_TIMEOUT": "600",
    }, clear=True)
    def test_custom_config(self):
        from modules.brain.freebuff_bridge import _bridge_config
        config = _bridge_config()
        assert config["binary"] == "my-freebuff"
        assert config["cwd"] == "/tmp/test"
        assert config["auto_start"] == "false"
        assert config["start_timeout"] == "30"
        assert config["response_timeout"] == "600"
