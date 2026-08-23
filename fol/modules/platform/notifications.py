"""Cross-platform desktop notifications.

macOS:   osascript display notification
Windows: PowerShell toast notification
Linux:   notify-send (libnotify)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def notify(title: str, message: str) -> bool:
    """Send a desktop notification (cross-platform).

    Returns True on success.
    """
    try:
        if sys.platform == "darwin":
            return _notify_macos(title, message)
        elif sys.platform == "win32":
            return _notify_windows(title, message)
        else:
            return _notify_linux(title, message)
    except Exception as exc:
        logger.warning("notify failed: %s", exc)
        return False


def _notify_macos(title: str, message: str) -> bool:
    """macOS notification via osascript."""
    if not shutil.which("osascript"):
        return False
    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, timeout=5,
    )
    return True


def _notify_windows(title: str, message: str) -> bool:
    """Windows notification via PowerShell BurntToast or balloon."""
    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
  <visual>
    <binding template="ToastText02">
      <text id="1">{title}</text>
      <text id="2">{message}</text>
    </binding>
  </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("FOL").Show($toast)
"""
    try:
        subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True, timeout=10,
        )
        return True
    except Exception:
        # Fallback: simple message box
        try:
            subprocess.run(
                ["powershell", "-Command", f"msg * '{title}: {message}'"],
                capture_output=True, timeout=5,
            )
            return True
        except Exception:
            return False


def _notify_linux(title: str, message: str) -> bool:
    """Linux notification via notify-send."""
    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", title, message],
            capture_output=True, timeout=5,
        )
        return True
    # Fallback: terminal bell
    print(f"\a[{title}] {message}")
    return False


__all__ = ["notify"]
