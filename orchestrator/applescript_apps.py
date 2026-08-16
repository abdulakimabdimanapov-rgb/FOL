"""AppleScript helpers for controlling native macOS applications.

Используется orchestrator-ом для:
- Safari: навигация, выполнение JavaScript, получение URL
- Telegram: активация, отправка сообщений через UI automation
- WhatsApp: активация, отправка сообщений
- Общие: открытие приложений, получение информации

Каждая функция возвращает dict с status и данными или error.
Никогда не крашится — все исключения перехватываются.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def _run_osascript(script: str, timeout: int = 10) -> dict[str, Any]:
    """Run an AppleScript and return the result.

    Args:
        script: Raw AppleScript code (without 'osascript -e' wrapper)
        timeout: Seconds to wait before timeout

    Returns:
        {"status": "ok", "stdout": "..."} or {"status": "error", "error": "..."}
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return {"status": "ok", "stdout": result.stdout.strip()}
        else:
            error = result.stderr.strip() or f"Exit code {result.returncode}"
            return {"status": "error", "error": error}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "AppleScript timed out"}
    except FileNotFoundError:
        return {"status": "error", "error": "osascript not found (not macOS?)"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------------------
# Safari
# ---------------------------------------------------------------------------


def safari_goto(url: str) -> dict[str, Any]:
    """Navigate Safari to a URL.

    Args:
        url: Full URL including protocol, e.g. "https://web.telegram.org"

    Returns:
        {"status": "ok"} or error dict
    """
    script = f"""
    tell application "Safari"
        activate
        if (count of windows) = 0 then
            make new document with properties {{URL:"{url}"}}
        else
            set URL of current tab of front window to "{url}"
        end if
        delay 1
    end tell
    return "ok"
    """
    return _run_osascript(script, timeout=15)


def safari_get_url() -> str:
    """Get the current URL from the active Safari tab.

    Returns:
        URL string, or empty string on error.
    """
    script = """
    tell application "Safari"
        if (count of windows) = 0 then return ""
        set currentURL to URL of current tab of front window
        return currentURL
    end tell
    """
    result = _run_osascript(script)
    if result["status"] == "ok":
        return result.get("stdout", "")
    return ""


def safari_execute_js(javascript: str) -> dict[str, Any]:
    """Execute JavaScript in Safari's current tab.

    Args:
        javascript: JavaScript code to execute, e.g.
            'document.querySelector("input").value = "hello"'

    Returns:
        {"status": "ok", "result": "..."} or error dict
    """
    # Escape quotes for AppleScript
    escaped_js = javascript.replace('"', '\\"')
    script = f"""
    tell application "Safari"
        if (count of windows) = 0 then return "No open window"
        set resultText to do JavaScript "{escaped_js}" in current tab of front window
        return resultText
    end tell
    """
    return _run_osascript(script, timeout=15)


def safari_get_page_title() -> str:
    """Get the title of the current Safari page.

    Returns:
        Title string, or empty string on error.
    """
    script = """
    tell application "Safari"
        if (count of windows) = 0 then return ""
        set pageTitle to name of current tab of front window
        return pageTitle
    end tell
    """
    result = _run_osascript(script)
    if result["status"] == "ok":
        return result.get("stdout", "")
    return ""


# ---------------------------------------------------------------------------
# App activation & window control
# ---------------------------------------------------------------------------


def activate_app(app_name: str) -> dict[str, Any]:
    """Bring an application to the front.

    Args:
        app_name: "Telegram", "WhatsApp", "Safari", "Google Chrome", etc.

    Returns:
        {"status": "ok"} or error dict
    """
    script = f"""
    tell application "{app_name}"
        activate
    end tell
    return "ok"
    """
    result = _run_osascript(script)
    if result["status"] == "error":
        # Fallback: try 'open' command
        try:
            subprocess.run(["open", "-a", app_name], capture_output=True, timeout=5)
            return {"status": "ok", "method": "open_fallback"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}
    return result


def is_app_running(app_name: str) -> bool:
    """Check if an application is currently running.

    Args:
        app_name: "Telegram", "WhatsApp", etc.

    Returns:
        True if running
    """
    script = f"""
    tell application "System Events"
        set appList to name of every process
        if "{app_name}" is in appList then
            return "yes"
        else
            return "no"
        end if
    end tell
    """
    result = _run_osascript(script)
    return result.get("stdout", "").strip().lower() == "yes"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def telegram_send(contact: str, message: str) -> dict[str, Any]:
    """Send a message via Telegram Desktop using UI automation.

    Открывает Telegram, находит контакт и отправляет сообщение.

    NOTE: Telegram не поддерживает AppleScript напрямую.
    Используется комбинация: activate + PyAutoGUI (type_text + hotkey).

    Args:
        contact: Contact name or username to search for
        message: Message text to send

    Returns:
        {"status": "ok", "method": "ui_automation", "contact": contact}
        or error dict if Telegram is not running.
    """
    # First check if Telegram is running
    if not is_app_running("Telegram"):
        return {
            "status": "error",
            "error": "Telegram is not running. Open it first with open_app('Telegram')",
        }

    # Activate Telegram
    activate_result = activate_app("Telegram")
    if activate_result["status"] != "ok":
        return activate_result

    return {
        "status": "ok",
        "method": "ui_automation",
        "contact": contact,
        "instructions": (
            "Telegram is now active. To send a message, use these steps:\n"
            "1. type_text(contact_name) — type the contact name (it will search)\n"
            "2. Wait briefly\n"
            "3. hotkey(['return']) — select the contact\n"
            "4. type_text(message_text) — type the message\n"
            "5. hotkey(['command', 'return']) — or hotkey(['return']) to send\n"
            "Telegram Desktop does not support AppleScript for direct messaging."
        ),
    }


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------


def whatsapp_send(contact: str, message: str) -> dict[str, Any]:
    """Send a message via WhatsApp Desktop using UI automation.

    NOTE: WhatsApp Desktop has limited AppleScript support.
    Uses activation + PyAutoGUI for message sending.

    Args:
        contact: Contact name as it appears in WhatsApp
        message: Message text

    Returns:
        {"status": "ok", "method": "ui_automation"} or error
    """
    if not is_app_running("WhatsApp"):
        # Try to open it
        result = activate_app("WhatsApp")
        if result["status"] != "ok":
            # Try WhatsApp Desktop
            result = activate_app("WhatsApp Desktop")
            if result["status"] != "ok":
                return {
                    "status": "error",
                    "error": "WhatsApp is not installed or running. "
                             "Use the web version via browser_goto('https://web.whatsapp.com')",
                }

    activate_result = activate_app("WhatsApp")
    if activate_result["status"] != "ok":
        return activate_result

    return {
        "status": "ok",
        "method": "ui_automation",
        "contact": contact,
        "instructions": (
            "WhatsApp is now active. To send a message, use these steps:\n"
            "1. hotkey(['command', 'k']) — open search (if WhatsApp Desktop)\n"
            "   OR hotkey(['command', 'f']) — find contact\n"
            "2. type_text(contact_name) — type the contact name\n"
            "3. hotkey(['return']) — select the contact\n"
            "4. type_text(message_text) — type the message\n"
            "5. hotkey(['return']) — send the message\n"
            "If WhatsApp Desktop is not available, use "
            "browser_goto('https://web.whatsapp.com') and browser tools."
        ),
    }


# ---------------------------------------------------------------------------
# Generic: open URL in default browser
# ---------------------------------------------------------------------------


def open_url(url: str) -> dict[str, Any]:
    """Open a URL in the default browser using the 'open' command.

    Args:
        url: Full URL, e.g. "https://web.telegram.org"

    Returns:
        {"status": "ok"} or error dict
    """
    try:
        result = subprocess.run(["open", url], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return {"status": "ok"}
        return {"status": "error", "error": result.stderr.strip()}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
