"""OS detection for FOL cross-platform support.

Provides constants and helpers to branch on the current platform:
  IS_MAC, IS_WINDOWS, IS_LINUX, IS_WSL, PLATFORM
"""

from __future__ import annotations

import os
import sys
import platform as _platform


def _is_wsl() -> bool:
    """Detect Windows Subsystem for Linux."""
    if not IS_LINUX:
        return False
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except (OSError, IOError):
        return False


IS_MAC: bool = sys.platform == "darwin"
IS_WINDOWS: bool = sys.platform == "win32" or os.name == "nt"
IS_LINUX: bool = sys.platform.startswith("linux") and not IS_MAC

# WSL detection (must be after IS_LINUX)
IS_WSL: bool = False  # set below

PLATFORM: str = (
    "macos" if IS_MAC
    else "windows" if IS_WINDOWS
    else "linux"
)

IS_WSL = _is_wsl()

# Apple Silicon detection
IS_APPLE_SILICON: bool = (
    IS_MAC and _platform.machine().startswith("arm64")
)


def get_platform() -> str:
    """Return 'macos', 'windows', or 'linux'."""
    return PLATFORM


def require_mac(action: str = "this feature") -> str | None:
    """Return None if on Mac, or an error message if not."""
    if IS_MAC:
        return None
    return f"{action} requires macOS (current platform: {PLATFORM})"


__all__ = [
    "IS_MAC",
    "IS_WINDOWS",
    "IS_LINUX",
    "IS_WSL",
    "IS_APPLE_SILICON",
    "PLATFORM",
    "get_platform",
    "require_mac",
]
