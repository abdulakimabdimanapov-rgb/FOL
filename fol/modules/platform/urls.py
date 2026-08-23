"""Cross-platform URL, app, and file opening.

Works on macOS, Windows, and Linux without platform-specific imports.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def open_url(url: str) -> bool:
    """Open a URL in the default browser (cross-platform).

    Returns True on success.
    """
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            os.startfile(url)
        else:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        logger.warning("open_url failed: %s", exc)
        return False


def open_app(name: str) -> bool:
    """Open an application by name (cross-platform).

    macOS:   open -a "Safari"
    Windows: start "" "Chrome"
    Linux:   xdg-open or direct binary
    """
    try:
        if sys.platform == "darwin":
            subprocess.Popen(
                ["open", "-a", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "win32":
            # Try common Windows paths
            for path in [
                os.path.expandvars(f"%PROGRAMFILES%\\{name}\\{name}.exe"),
                os.path.expandvars(f"%PROGRAMFILES(X86)%\\{name}\\{name}.exe"),
                os.path.expandvars(f"%LOCALAPPDATA%\\{name}\\{name}.exe"),
            ]:
                if os.path.isfile(path):
                    subprocess.Popen([path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
            # Fallback: try `start`
            subprocess.Popen(
                ["cmd", "/c", "start", "", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # Linux: try xdg-open with app name, or direct launch
            subprocess.Popen(
                [name.lower()],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as exc:
        logger.warning("open_app(%s) failed: %s", name, exc)
        return False


def open_file(path: str) -> bool:
    """Open a file with the default application (cross-platform)."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        logger.warning("open_file(%s) failed: %s", path, exc)
        return False


__all__ = ["open_url", "open_app", "open_file"]
