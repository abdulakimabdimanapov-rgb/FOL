"""App Monitor — macOS активное приложение через AppleScript.

Определяет: название приложения, bundle ID, PID.
Не требует Accessibility permission.
"""

import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def get_active_app() -> dict[str, Any]:
    """Get the currently active (frontmost) application.
    
    Uses AppleScript via osascript. Works from any Python process.
    No PyObjC needed.
    
    Returns:
        {"name": "Google Chrome", "bundle_id": "com.google.Chrome",
         "pid": 12345, "timestamp": "2026-04-12T14:30:00Z"}
    """
    script = """
    tell application "System Events"
        set frontApp to first application process whose frontmost is true
        set appName to name of frontApp
        set bundleId to bundle identifier of frontApp
        set pid to unix id of frontApp
        return appName & "|||" & bundleId & "|||" & pid
    end tell
    """
    
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {"name": "unknown", "bundle_id": "", "pid": 0}
        
        parts = result.stdout.strip().split("|||")
        app_info = {
            "name": parts[0] if len(parts) > 0 else "unknown",
            "bundle_id": parts[1] if len(parts) > 1 else "",
            "pid": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
        }
        return app_info
    except subprocess.TimeoutExpired:
        return {"name": "unknown", "bundle_id": "", "pid": 0}
    except Exception as exc:
        logger.debug("get_active_app failed: %s", exc)
        return {"name": "unknown", "bundle_id": "", "pid": 0}


def get_app_category(bundle_id: str) -> str:
    """Categorize an application by bundle ID."""
    CATEGORIES = {
        "com.google.Chrome": "browser",
        "com.apple.Safari": "browser",
        "company.thebrowser.Browser": "browser",
        "com.microsoft.edgemac": "browser",
        "org.mozilla.firefox": "browser",
        "com.microsoft.VSCode": "ide",
        "com.jetbrains.intellij": "ide",
        "com.apple.dt.Xcode": "ide",
        "com.apple.Terminal": "terminal",
        "com.googlecode.iterm2": "terminal",
        "md.obsidian": "notes",
        "com.apple.Notes": "notes",
        "com.apple.mail": "email",
        "com.tinyspeck.slackmacgap": "communication",
        "com.microsoft.teams2": "communication",
        "com.spotify.client": "media",
        "com.apple.TV": "media",
        "com.figma.Desktop": "design",
    }
    return CATEGORIES.get(bundle_id, "other")


_last_app: dict[str, Any] = {"name": "", "bundle_id": "", "pid": 0, "_time": 0}


def get_active_app_cached() -> dict[str, Any]:
    """Get active app with a simple cache to avoid polling too fast."""
    global _last_app
    import time
    now = time.time()
    if now - _last_app.get("_time", 0) < 1.0:  # 1s cache
        return {k: v for k, v in _last_app.items() if k != "_time"}
    app = get_active_app()
    app["_time"] = now
    _last_app = app
    return {k: v for k, v in app.items() if k != "_time"}
