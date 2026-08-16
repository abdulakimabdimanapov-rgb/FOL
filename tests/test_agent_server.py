"""Unit tests for agent-server/server.py desktop tools.

Covers the desktop tool layer added for v0.4.0:
- close_app (AppleScript quit)
- drag (PyAutoGUI dragTo)
- clipboard_get / clipboard_set (pbpaste / pbcopy)
- notify (osascript display notification)

All subprocess / pyautogui calls are mocked so tests run headless.

NOTE: agent-server/server.py is loaded via importlib with a unique module
name ("_agent_server_under_test") instead of `import server` to avoid the
name collision with orchestrator/server.py — both files are named server.py.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Load agent-server/server.py under a unique module name
# ---------------------------------------------------------------------------

_agent_path = Path(__file__).parent.parent / "agent-server" / "server.py"

_spec = importlib.util.spec_from_file_location("_agent_server_under_test", _agent_path)
assert _spec is not None and _spec.loader is not None, "Could not locate agent-server/server.py"
agent_server = importlib.util.module_from_spec(_spec)
sys.modules["_agent_server_under_test"] = agent_server
_spec.loader.exec_module(agent_server)


# ---------------------------------------------------------------------------
# close_app
# ---------------------------------------------------------------------------

class TestCloseApp:
    def test_close_app_success(self):
        """A successful osascript quit returns status ok."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout="ok", stderr=""))
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.close_app("Notes")
        assert result["status"] == "ok"
        assert result["action"] == "close_app"
        assert result["app"] == "Notes"
        # AppleScript must include a quit command
        script = mock_run.call_args.args[0][-1]
        assert "quit" in script.lower()
        assert "Notes" in script

    def test_close_app_error(self):
        """A failed osascript quit returns an error with stderr detail."""
        mock_run = Mock(
            return_value=Mock(returncode=1, stdout="", stderr="application not running")
        )
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.close_app("MissingApp")
        assert result["status"] == "error"
        assert "not running" in result["error"]

    def test_close_app_escapes_name(self):
        """App names with quotes must be escaped in the AppleScript string."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout="ok", stderr=""))
        with patch.object(agent_server.subprocess, "run", mock_run) as m:
            agent_server.close_app('Weird"App')
        script = m.call_args.args[0][-1]
        assert '\\"' in script  # escaped quote inside the string literal


# ---------------------------------------------------------------------------
# drag
# ---------------------------------------------------------------------------

class TestDrag:
    def test_drag_calls_pyautogui(self):
        """drag() should moveTo then dragTo with the given coordinates."""
        mock_pg = Mock()
        with patch.dict(sys.modules, {"pyautogui": mock_pg}):
            result = agent_server.drag(10, 20, 30, 40, duration=0.5)
        assert result["status"] == "ok"
        assert result["action"] == "drag"
        assert result["from"] == [10, 20]
        assert result["to"] == [30, 40]
        mock_pg.moveTo.assert_called_once_with(10, 20, duration=0.15)
        mock_pg.dragTo.assert_called_once_with(30, 40, duration=0.5, button="left")

    def test_drag_default_duration(self):
        """drag() defaults duration to 0.3 seconds."""
        mock_pg = Mock()
        with patch.dict(sys.modules, {"pyautogui": mock_pg}):
            agent_server.drag(0, 0, 5, 5)
        _, kwargs = mock_pg.dragTo.call_args
        assert kwargs["duration"] == 0.3


# ---------------------------------------------------------------------------
# clipboard_get / clipboard_set
# ---------------------------------------------------------------------------

class TestClipboard:
    def test_clipboard_get(self):
        """clipboard_get() should return pbpaste stdout as text."""
        mock_run = Mock(
            return_value=Mock(returncode=0, stdout="hello clipboard", stderr="")
        )
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.clipboard_get()
        assert result["status"] == "ok"
        assert result["action"] == "clipboard_get"
        assert result["text"] == "hello clipboard"
        assert mock_run.call_args.args[0][0] == "pbpaste"

    def test_clipboard_set(self):
        """clipboard_set() should feed text to pbcopy via stdin."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.clipboard_set("some text")
        assert result["status"] == "ok"
        assert result["action"] == "clipboard_set"
        assert result["length"] == 9
        call_kwargs = mock_run.call_args.kwargs
        assert call_kwargs["input"] == "some text"
        assert mock_run.call_args.args[0][0] == "pbcopy"

    def test_clipboard_set_empty(self):
        """Setting an empty string is still a valid clipboard write."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.clipboard_set("")
        assert result["status"] == "ok"
        assert result["length"] == 0

    def test_clipboard_set_error(self):
        """A failed pbcopy should surface the stderr message."""
        mock_run = Mock(
            return_value=Mock(returncode=1, stdout="", stderr="pipe error")
        )
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.clipboard_set("x")
        assert result["status"] == "error"
        assert "pipe error" in result["error"]


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------

class TestNotify:
    def test_notify_success(self):
        """notify() should build a display notification AppleScript."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout="ok", stderr=""))
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.notify("Test", "Hello there")
        assert result["status"] == "ok"
        assert result["action"] == "notify"
        assert result["title"] == "Test"
        script = mock_run.call_args.args[0][-1]
        assert "display notification" in script
        assert "Test" in script
        assert "Hello there" in script

    def test_notify_error(self):
        """A failed notification should return an error."""
        mock_run = Mock(
            return_value=Mock(returncode=1, stdout="", stderr="osascript error")
        )
        with patch.object(agent_server.subprocess, "run", mock_run):
            result = agent_server.notify("Test", "")
        assert result["status"] == "error"
        assert "osascript error" in result["error"]

    def test_notify_escapes_quotes(self):
        """Message quotes must be escaped to not break AppleScript."""
        mock_run = Mock(return_value=Mock(returncode=0, stdout="ok", stderr=""))
        with patch.object(agent_server.subprocess, "run", mock_run) as m:
            agent_server.notify('Say "hi"', "It's fine")
        script = m.call_args.args[0][-1]
        assert '\\"' in script


# ---------------------------------------------------------------------------
# TOOLS route table registration
# ---------------------------------------------------------------------------

class TestToolsRegistration:
    def test_new_tools_registered(self):
        """All new desktop tool endpoints must be present in the route table."""
        for endpoint in [
            "/tool/close_app",
            "/tool/drag",
            "/tool/clipboard_get",
            "/tool/clipboard_set",
            "/tool/notify",
        ]:
            assert endpoint in agent_server.TOOLS, f"Missing route: {endpoint}"

    def test_tools_handler_shapes(self):
        """Handlers should accept a body dict and return a dict."""
        for endpoint in ["/tool/clipboard_get", "/tool/notify"]:
            handler = agent_server.TOOLS[endpoint]
            with patch.object(agent_server.subprocess, "run",
                              return_value=Mock(returncode=0, stdout="ok", stderr="")):
                result = handler({})
            assert isinstance(result, dict)
            assert result.get("status") == "ok"
