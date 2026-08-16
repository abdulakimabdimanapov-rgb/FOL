"""Unit tests for orchestrator/applescript_apps.py.

Тестирует AppleScript-хелперы с моками subprocess.run:
- _run_osascript — базовый запуск osascript
- safari_goto / safari_get_url / safari_execute_js — Safari
- activate_app — активация приложений
- is_app_running — проверка запущенных приложений
- telegram_send / whatsapp_send — отправка сообщений
- open_url — открытие URL в браузере

Все тесты используют mock — реальный osascript не вызывается.
"""

from __future__ import annotations

import subprocess
import sys
import os
from unittest.mock import patch, MagicMock

# Add orchestrator/ to path (where applescript_apps lives)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))

import pytest

from applescript_apps import (
    _run_osascript,
    safari_goto,
    safari_get_url,
    safari_execute_js,
    safari_get_page_title,
    activate_app,
    is_app_running,
    telegram_send,
    whatsapp_send,
    open_url,
)


# ============================================================================
# Fixtures
# ============================================================================


def _make_mock_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Create a mocked subprocess.CompletedProcess."""
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ============================================================================
# _run_osascript
# ============================================================================


class TestRunOsascript:
    """Core AppleScript runner — базовая функция."""

    def test_success_returns_ok(self):
        """Успешный запуск возвращает status=ok с stdout."""
        with patch("subprocess.run", return_value=_make_mock_result(0, "hello")) as mock_run:
            result = _run_osascript('return "hello"', timeout=10)

        assert result["status"] == "ok"
        assert result["stdout"] == "hello"
        mock_run.assert_called_once_with(
            ["osascript", "-e", 'return "hello"'],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_failure_returns_error(self):
        """Ошибка osascript возвращает status=error со stderr."""
        with patch("subprocess.run", return_value=_make_mock_result(1, "", "Syntax error")):
            result = _run_osascript("bad script")

        assert result["status"] == "error"
        assert "Syntax error" in result["error"]

    def test_failure_no_stderr_uses_exit_code(self):
        """Если stderr пустой, используется exit code как сообщение."""
        with patch("subprocess.run", return_value=_make_mock_result(127, "", "")):
            result = _run_osascript("missing")

        assert result["status"] == "error"
        assert "Exit code 127" in result["error"]

    def test_timeout_returns_error(self):
        """Таймаут возвращает ошибку."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=10)):
            result = _run_osascript("slow script")

        assert result["status"] == "error"
        assert "timed out" in result["error"].lower()

    def test_file_not_found_returns_error(self):
        """Если osascript не найден — ошибка."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = _run_osascript("script")

        assert result["status"] == "error"
        assert "osascript not found" in result["error"]

    def test_unknown_exception_returns_error(self):
        """Любое другое исключение перехватывается."""
        with patch("subprocess.run", side_effect=PermissionError("denied")):
            result = _run_osascript("script")

        assert result["status"] == "error"
        assert "denied" in result["error"]


# ============================================================================
# Safari
# ============================================================================


class TestSafariGoto:
    """safari_goto(url) — навигация Safari."""

    def test_goto_success(self):
        """Успешная навигация возвращает status=ok."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "ok"}):
            result = safari_goto("https://example.com")
        assert result["status"] == "ok"

    def test_goto_failure(self):
        """Ошибка навигации возвращает status=error."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "error", "error": "Safari not running"}):
            result = safari_goto("https://example.com")
        assert result["status"] == "error"
        assert "Safari" in result["error"]


class TestSafariGetUrl:
    """safari_get_url() — получение URL из Safari."""

    def test_get_url_success(self):
        """Успешное получение URL."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "https://example.com"}):
            url = safari_get_url()
        assert url == "https://example.com"

    def test_get_url_error_returns_empty(self):
        """Ошибка возвращает пустую строку."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "error", "error": "no window"}):
            url = safari_get_url()
        assert url == ""


class TestSafariExecuteJs:
    """safari_execute_js(javascript) — выполнение JS."""

    def test_js_success(self):
        """Успешное выполнение JS."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "clicked"}):
            result = safari_execute_js('document.querySelector("button").click()')
        assert result["status"] == "ok"
        assert result.get("stdout") == "clicked"

    def test_js_with_quotes(self):
        """JS с кавычками корректно экранируется."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "hello"}):
            result = safari_execute_js('console.log("hello")')
        assert result["status"] == "ok"


class TestSafariGetPageTitle:
    """safari_get_page_title() — получение заголовка страницы."""

    def test_title_success(self):
        """Успешное получение заголовка."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "My Page"}):
            title = safari_get_page_title()
        assert title == "My Page"

    def test_title_error_returns_empty(self):
        """Ошибка возвращает пустую строку."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "error", "error": "no window"}):
            title = safari_get_page_title()
        assert title == ""


# ============================================================================
# App activation
# ============================================================================


class TestActivateApp:
    """activate_app(app_name) — активация приложения."""

    def test_activate_success(self):
        """Успешная активация через osascript."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "ok"}):
            result = activate_app("Safari")
        assert result["status"] == "ok"

    def test_activate_fallback_to_open(self):
        """При ошибке osascript fallback на 'open -a'."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "error", "error": "not running"}):
            with patch("subprocess.run",
                       return_value=_make_mock_result(0, "")) as mock_open:
                result = activate_app("Telegram")

        assert result["status"] == "ok"
        assert result["method"] == "open_fallback"
        mock_open.assert_called_once_with(
            ["open", "-a", "Telegram"],
            capture_output=True,
            timeout=5,
        )

    def test_activate_fallback_fails(self):
        """Если и fallback не работает — возвращаем ошибку."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "error", "error": "not running"}):
            with patch("subprocess.run", side_effect=FileNotFoundError("open not found")):
                result = activate_app("UnknownApp")

        assert result["status"] == "error"
        assert "not found" in result["error"]


class TestIsAppRunning:
    """is_app_running(app_name) — проверка запущенного приложения."""

    def test_running_true(self):
        """Приложение запущено."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "yes"}):
            assert is_app_running("Safari") is True

    def test_running_false(self):
        """Приложение не запущено."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "ok", "stdout": "no"}):
            assert is_app_running("Telegram") is False

    def test_running_error_returns_false(self):
        """Ошибка скрипта = не запущено."""
        with patch("applescript_apps._run_osascript",
                   return_value={"status": "error", "error": "permission denied"}):
            assert is_app_running("Safari") is False


# ============================================================================
# Telegram
# ============================================================================


class TestTelegramSend:
    """telegram_send(contact, message) — отправка в Telegram."""

    def test_telegram_not_running_returns_error(self):
        """Если Telegram не запущен — возвращаем ошибку."""
        with patch("applescript_apps.is_app_running", return_value=False):
            result = telegram_send("Alice", "Hello!")

        assert result["status"] == "error"
        assert "not running" in result["error"].lower()

    def test_telegram_sends_instructions(self):
        """Если Telegram запущен — активируем и возвращаем инструкции."""
        with patch("applescript_apps.is_app_running", return_value=True):
            with patch("applescript_apps.activate_app",
                       return_value={"status": "ok", "stdout": "ok"}):
                result = telegram_send("Alice", "Hello!")

        assert result["status"] == "ok"
        assert result["method"] == "ui_automation"
        assert result["contact"] == "Alice"
        assert "type_text" in result["instructions"]
        assert "hotkey" in result["instructions"]

    def test_telegram_activate_fails(self):
        """Если активация не удалась — возвращаем ошибку активации."""
        with patch("applescript_apps.is_app_running", return_value=True):
            with patch("applescript_apps.activate_app",
                       return_value={"status": "error", "error": "activation failed"}):
                result = telegram_send("Bob", "Test")

        assert result["status"] == "error"
        assert "activation failed" in result["error"]


# ============================================================================
# WhatsApp
# ============================================================================


class TestWhatsAppSend:
    """whatsapp_send(contact, message) — отправка в WhatsApp."""

    def test_whatsapp_not_running_tries_to_open(self):
        """Если WhatsApp не запущен — пытаемся открыть."""
        with patch("applescript_apps.is_app_running", return_value=False):
            with patch("applescript_apps.activate_app",
                       side_effect=[
                           {"status": "error", "error": "not found"},
                           {"status": "error", "error": "not found"},
                       ]):
                result = whatsapp_send("Alice", "Hello!")

        assert result["status"] == "error"
        assert "not installed" in result["error"].lower()

    def test_whatsapp_running_sends_instructions(self):
        """Если WhatsApp запущен — возвращаем инструкции."""
        with patch("applescript_apps.is_app_running", return_value=True):
            with patch("applescript_apps.activate_app",
                       return_value={"status": "ok", "stdout": "ok"}):
                result = whatsapp_send("Alice", "Hello!")

        assert result["status"] == "ok"
        assert result["method"] == "ui_automation"
        assert result["contact"] == "Alice"
        assert "type_text" in result["instructions"]

    def test_whatsapp_not_running_opens_successfully(self):
        """WhatsApp не запущен, но открывается успешно — возвращаем инструкции."""
        with patch("applescript_apps.is_app_running", return_value=False):
            with patch("applescript_apps.activate_app",
                       return_value={"status": "ok", "stdout": "ok"}):
                result = whatsapp_send("Alice", "Hello!")

        assert result["status"] == "ok"
        assert result["method"] == "ui_automation"
        assert "type_text" in result["instructions"]

    def test_whatsapp_activate_fails(self):
        """Если активация WhatsApp не удалась."""
        with patch("applescript_apps.is_app_running", return_value=True):
            with patch("applescript_apps.activate_app",
                       return_value={"status": "error", "error": "activation failed"}):
                result = whatsapp_send("Bob", "Test")

        assert result["status"] == "error"
        assert "activation failed" in result["error"]


# ============================================================================
# Open URL
# ============================================================================


class TestOpenUrl:
    """open_url(url) — открытие URL в браузере."""

    def test_open_success(self):
        """Успешное открытие URL."""
        with patch("subprocess.run", return_value=_make_mock_result(0, "")):
            result = open_url("https://example.com")
        assert result["status"] == "ok"

    def test_open_failure(self):
        """Ошибка открытия URL."""
        with patch("subprocess.run", return_value=_make_mock_result(1, "", "no URL")):
            result = open_url("bad://url")
        assert result["status"] == "error"
        assert "no URL" in result["error"]

    def test_open_exception(self):
        """Исключение при открытии URL."""
        with patch("subprocess.run", side_effect=OSError("connection refused")):
            result = open_url("https://example.com")
        assert result["status"] == "error"
        assert "connection refused" in result["error"]
