"""Platform detection and cross-platform utilities for FOL.

Detects the current OS and provides platform-specific fallbacks for:
  - App control (open, quit, activate)
  - Notifications
  - Screen capture
  - TTS (text-to-speech)
  - Mouse/keyboard control
  - Browser URL detection

Usage:
    from modules.platform import IS_MAC, IS_WINDOWS, IS_LINUX, get_platform
    from modules.platform import open_url, open_app, notify, capture_screen
"""

from modules.platform.detector import (
    IS_MAC,
    IS_WINDOWS,
    IS_LINUX,
    IS_WSL,
    PLATFORM,
    get_platform,
    require_mac,
)

from modules.platform.urls import open_url, open_app, open_file
from modules.platform.notifications import notify
from modules.platform.tts import speak, get_tts_provider
from modules.platform.screen import capture_screenshot, get_active_app, get_browser_url

__all__ = [
    "IS_MAC",
    "IS_WINDOWS",
    "IS_LINUX",
    "IS_WSL",
    "PLATFORM",
    "get_platform",
    "require_mac",
    "open_url",
    "open_app",
    "open_file",
    "notify",
    "speak",
    "get_tts_provider",
    "capture_screenshot",
    "get_active_app",
    "get_browser_url",
]
