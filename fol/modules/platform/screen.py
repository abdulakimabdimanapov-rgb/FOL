"""Cross-platform screen capture, active app, and browser URL detection.

macOS:   screencapture, osascript (AppleScript)
Windows: PowerShell screenshot, window title API
Linux:   scrot, xdotool, xprop
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
import tempfile

logger = logging.getLogger(__name__)


def capture_screenshot(output_path: str | None = None) -> str | None:
    """Capture a screenshot and return the file path (or None on failure).

    Cross-platform: macOS screencapture, Windows PowerShell, Linux scrot/maim.
    """
    if output_path is None:
        output_path = os.path.join(tempfile.gettempdir(), "fol_screenshot.png")

    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["screencapture", "-x", output_path],
                capture_output=True, timeout=10,
            )
        elif sys.platform == "win32":
            ps = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save('{output_path}')
$graphics.Dispose()
$bitmap.Dispose()
"""
            subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True, timeout=15,
            )
        else:
            # Linux: try scrot, then maim
            for tool in ["scrot", "maim"]:
                if shutil.which(tool):
                    if tool == "scrot":
                        subprocess.run([tool, output_path], capture_output=True, timeout=10)
                    else:
                        subprocess.run([tool, output_path], capture_output=True, timeout=10)
                    break
            else:
                logger.warning("No screenshot tool found (install scrot or maim)")
                return None

        if os.path.isfile(output_path):
            return output_path
        return None
    except Exception as exc:
        logger.warning("Screenshot failed: %s", exc)
        return None


def get_active_app() -> str:
    """Get the name of the currently active (frontmost) application.

    macOS:   osascript (AppleScript)
    Windows: PowerShell Get-Process
    Linux:   xdotool
    """
    try:
        if sys.platform == "darwin":
            script = 'tell application "System Events" to get name of first application process whose frontmost is true'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""

        elif sys.platform == "win32":
            ps = "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object -First 1 -ExpandProperty ProcessName"
            result = subprocess.run(
                ["powershell", "-Command", ps],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""

        else:
            # Linux: xdotool
            if shutil.which("xdotool"):
                result = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True, text=True, timeout=5,
                )
                return result.stdout.strip() if result.returncode == 0 else ""
            return ""

    except Exception as exc:
        logger.debug("get_active_app failed: %s", exc)
        return ""


def get_browser_url() -> str:
    """Get the URL from the active browser tab.

    macOS:   osascript (AppleScript) for Safari/Chrome/Firefox/Edge
    Windows: PowerShell COM automation
    Linux:   xdotool + xprop or browser extensions
    """
    try:
        if sys.platform == "darwin":
            return _browser_url_macos()
        elif sys.platform == "win32":
            return _browser_url_windows()
        else:
            return _browser_url_linux()
    except Exception as exc:
        logger.debug("get_browser_url failed: %s", exc)
        return ""


def _browser_url_macos() -> str:
    """Get browser URL on macOS via AppleScript."""
    browsers = {
        "Safari": 'tell application "Safari" to get URL of current tab of front window',
        "Google Chrome": 'tell application "Google Chrome" to get URL of active tab of front window',
        "Firefox": 'tell application "Firefox" to get URL of front window',
        "Microsoft Edge": 'tell application "Microsoft Edge" to get URL of active tab of front window',
    }
    for name, script in browsers.items():
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            continue
    return ""


def _browser_url_windows() -> str:
    """Get browser URL on Windows via PowerShell."""
    ps = """
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class WinAPI {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);
}
'@
$handle = [WinAPI]::GetForegroundWindow()
$sb = New-Object System.Text.StringBuilder 256
[WinAPI]::GetWindowText($handle, $sb, 256) | Out-Null
$sb.ToString()
"""
    try:
        result = subprocess.run(
            ["powershell", "-Command", ps],
            capture_output=True, text=True, timeout=5,
        )
        title = result.stdout.strip()
        # Extract URL from window title (browsers often show URL in title)
        if "http" in title.lower():
            for part in title.split():
                if part.startswith("http"):
                    return part.rstrip("-–—|")
        return ""
    except Exception:
        return ""


def _browser_url_linux() -> str:
    """Get browser URL on Linux via xdotool/xprop."""
    if not shutil.which("xdotool"):
        return ""

    try:
        # Get active window ID
        result = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0:
            return ""
        win_id = result.stdout.strip()

        # Try to get WM_NAME or _NET_WM_NAME
        for prop in ["_NET_WM_NAME", "WM_NAME"]:
            result = subprocess.run(
                ["xprop", "-id", win_id, prop],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                title = result.stdout.split("=")[-1].strip().strip('"')
                if "http" in title.lower():
                    for part in title.split():
                        if part.startswith("http"):
                            return part.rstrip("-–—|")
        return ""
    except Exception:
        return ""


__all__ = [
    "capture_screenshot",
    "get_active_app",
    "get_browser_url",
]
