"""Unified context engine — ONE context layer inside FOL.

This is the canonical home of desktop context: active application, browser
URL, screen capture and Vision OCR. The root ``context_engine/`` package is
now a compatibility shim that delegates here (the orchestrator's
``build_context_messages`` keeps working unchanged).

Pipeline:

    Screen capture → Vision → Context Engine → ContextSnapshot → prompt block
        ↓
    active app (AppleScript) / browser URL (AppleScript)

Everything is best-effort and never raises: a missing permission, a timed-out
AppleScript or an absent OCR framework degrades to empty fields instead of
breaking the caller. Screen content is captured only when explicitly
requested (``with_vision=True``) — by default only lightweight app/browser
context is gathered, so the hot path stays fast and privacy-light.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TIMEOUT = 5  # seconds per subprocess call

# App categories by bundle id (browsers get URL context).
_BROWSER_BUNDLES = {
    "com.google.Chrome",
    "com.apple.Safari",
    "company.thebrowser.Browser",
    "com.microsoft.edgemac",
    "org.mozilla.firefox",
}

_APP_CATEGORIES = {
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

# AppleScript per browser → "URL|||title".
_BROWSER_SCRIPTS: dict[str, str] = {
    "Google Chrome": """
        tell application "Google Chrome"
            if (count of windows) > 0 then
                set win to front window
                set activeTab to active tab of win
                return (URL of activeTab) & "|||" & (title of activeTab)
            end if
        end tell
    """,
    "Safari": """
        tell application "Safari"
            if (count of windows) > 0 then
                set win to front window
                set currentTab to current tab of win
                return (URL of currentTab) & "|||" & (name of currentTab)
            end if
        end tell
    """,
    "Arc": """
        tell application "Arc"
            if (count of windows) > 0 then
                set win to front window
                set activeTab to active tab of win
                return (URL of activeTab) & "|||" & (title of activeTab)
            end if
        end tell
    """,
    "Microsoft Edge": """
        tell application "Microsoft Edge"
            if (count of windows) > 0 then
                set win to front window
                set activeTab to active tab of win
                return (URL of activeTab) & "|||" & (title of activeTab)
            end if
        end tell
    """,
    "Firefox": """
        tell application "System Events"
            tell process "Firefox"
                try
                    set urlBar to text field 1 of toolbar 1 of window 1
                    return (value of urlBar) & "|||" & (title of window 1)
                end try
            end tell
        end tell
    """,
}

_URL_CATEGORIES: dict[str, str] = {
    "github.com": "development",
    "gitlab.com": "development",
    "stackoverflow.com": "development",
    "developer.apple.com": "development",
    "mail.google.com": "email",
    "calendar.google.com": "calendar",
    "docs.google.com": "documents",
    "drive.google.com": "storage",
    "notion.so": "notes",
    "linear.app": "project_management",
    "youtube.com": "media",
    "netflix.com": "media",
    "twitter.com": "social",
    "x.com": "social",
    "reddit.com": "social",
    "linkedin.com": "social",
    "slack.com": "communication",
    "discord.com": "communication",
    "chatgpt.com": "learning",
    "perplexity.ai": "learning",
    "google.com": "search",
}


def _run_osascript(script: str, *, timeout: float = _TIMEOUT) -> str:
    """Run an AppleScript and return stdout ("" on any failure/timeout)."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except Exception as exc:
        logger.debug("osascript failed: %s", exc)
    return ""


def _classify_domain(domain: str) -> str:
    for key, category in _URL_CATEGORIES.items():
        if key in domain:
            return category
    return "browsing"


@dataclass
class ContextSnapshot:
    """Structured desktop context snapshot.

    Field names for the active app / browser are kept identical to the former
    ``context_engine.ContextSnapshot`` so existing consumers
    (``build_context_messages``) work unchanged; the ``screen`` / ``window`` /
    ``vision`` / ``user_activity`` groups extend the contract with the
    structured screen context.
    """

    timestamp: str = ""
    check_count: int = 0

    # Active application (compat names)
    app_name: str = ""
    app_bundle_id: str = ""
    app_pid: int = 0
    app_category: str = "other"

    # Browser (compat names)
    browser_url: str = ""
    browser_page_title: str = ""
    browser_domain: str = ""
    url_category: str = ""

    # Structured screen context (unified contract)
    screen: dict[str, Any] = field(default_factory=dict)          # {"captured": bool, "path": str}
    window: dict[str, Any] = field(default_factory=dict)          # {"title": str, "pid": str}
    vision: dict[str, Any] = field(default_factory=dict)          # {"text": str, "description": str}
    user_activity: dict[str, Any] = field(default_factory=dict)   # {"running_apps": [...]}

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict (never contains secrets)."""
        return {
            "timestamp": self.timestamp,
            "check_count": self.check_count,
            "active_app": {
                "name": self.app_name,
                "bundle_id": self.app_bundle_id,
                "pid": self.app_pid,
                "category": self.app_category,
            },
            "browser": {
                "url": self.browser_url,
                "title": self.browser_page_title,
                "domain": self.browser_domain,
                "category": self.url_category,
            },
            "screen": self.screen,
            "window": self.window,
            "vision": self.vision,
            "user_activity": self.user_activity,
        }

    def to_prompt(self) -> str:
        """Compact prompt block — same shape as the former
        ``context_engine.format_context_for_prompt``."""
        parts = []
        parts.append(f"Active: {self.app_name} ({self.app_category})")
        if self.browser_url:
            parts.append(f"URL: {self.browser_url}")
            if self.browser_page_title:
                parts.append(f"Page: {self.browser_page_title[:60]}")
            if self.url_category:
                parts.append(f"URL category: {self.url_category}")
        return " | ".join(parts)


class ContextEngine:
    """Unified desktop context engine.

    ``capture()`` gathers app + browser context (light, fast); pass
    ``with_vision=True`` to also capture the screen and run Vision OCR.
    Every component is isolated and best-effort — any failure degrades to an
    empty field. Never raises.
    """

    name = "context_engine"

    def __init__(self) -> None:
        self._last_app: dict[str, Any] = {"name": "", "bundle_id": "", "pid": 0, "_time": 0.0}
        self._check_count = 0
        self._screenshots_dir = __import__("pathlib").Path.home() / ".fol" / "screenshots"

    # -- public -----------------------------------------------------------

    def capture(self, use_cache: bool = False, with_vision: bool = False) -> ContextSnapshot:
        """Build a snapshot of the current desktop context. Never raises."""
        self._check_count += 1
        snapshot = ContextSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            check_count=self._check_count,
        )

        app = self._active_app(use_cache=use_cache)
        snapshot.app_name = app.get("name", "")
        snapshot.app_bundle_id = app.get("bundle_id", "")
        snapshot.app_pid = app.get("pid", 0)
        snapshot.app_category = _APP_CATEGORIES.get(snapshot.app_bundle_id, "other")

        if snapshot.app_category == "browser":
            url_info = self._browser_url(snapshot.app_name)
            snapshot.browser_url = url_info.get("url", "")
            snapshot.browser_page_title = url_info.get("title", "")
            snapshot.browser_domain = url_info.get("domain", "")
            snapshot.url_category = _classify_domain(snapshot.browser_domain)

        if with_vision:
            snapshot.screen, snapshot.window, snapshot.vision = self._screen_context()

        snapshot.user_activity = {"running_apps": self._running_apps()}
        return snapshot

    # -- components (each isolated, best-effort) --------------------------

    def _active_app(self, *, use_cache: bool) -> dict[str, Any]:
        """Frontmost app via System Events (no Accessibility permission)."""
        now = time.time()
        if use_cache and now - self._last_app.get("_time", 0.0) < 1.0:
            return {k: v for k, v in self._last_app.items() if k != "_time"}
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
            out = _run_osascript(script)
        except Exception as exc:  # defensive: never let context break the caller
            logger.debug("active app detection failed: %s", exc)
            out = ""
        parts = out.split("|||")
        app = {
            "name": parts[0] if parts and parts[0] else "unknown",
            "bundle_id": parts[1] if len(parts) > 1 else "",
            "pid": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
        }
        app["_time"] = now
        self._last_app = app
        return {k: v for k, v in app.items() if k != "_time"}

    def _browser_url(self, app_name: str) -> dict[str, Any]:
        """URL + title + domain of the frontmost browser tab."""
        script = _BROWSER_SCRIPTS.get(app_name)
        if not script:
            return {"url": "", "title": "", "domain": ""}
        try:
            out = _run_osascript(script)
        except Exception as exc:  # defensive
            logger.debug("browser url detection failed: %s", exc)
            out = ""
        if not out:
            return {"url": "", "title": "", "domain": ""}
        parts = out.split("|||")
        url = parts[0] if parts else ""
        domain = ""
        if url:
            try:
                from urllib.parse import urlparse

                parsed = urlparse(url)
                domain = parsed.netloc or ""
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                domain = ""
        return {
            "url": url,
            "title": parts[1] if len(parts) > 1 else "",
            "domain": domain,
        }

    def _screen_context(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Screen capture + active window + Vision OCR (all best-effort)."""
        screen = {"captured": False, "path": ""}
        window = {"title": "", "pid": ""}
        vision = {"text": "", "description": ""}

        try:
            self._screenshots_dir.mkdir(parents=True, exist_ok=True)
            path = self._screenshots_dir / f"screen_{int(time.time())}.png"
            result = subprocess.run(
                ["screencapture", "-x", str(path)],
                capture_output=True, timeout=_TIMEOUT,
            )
            if result.returncode == 0 and path.exists():
                screen = {"captured": True, "path": str(path)}
        except Exception as exc:
            logger.debug("Screen capture failed: %s", exc)

        try:
            script = """
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                set appName to name of frontApp
                set pid to unix id of frontApp
                set frontWindow to front window of frontApp
                set windowTitle to name of frontWindow
            end tell
            return appName & "|||" & pid & "|||" & windowTitle
            """
            out = _run_osascript(script)
            if out:
                parts = out.split("|||")
                window = {
                    "title": parts[2] if len(parts) > 2 else "",
                    "pid": parts[1] if len(parts) > 1 else "",
                }
        except Exception as exc:
            logger.debug("Window detection failed: %s", exc)

        vision["text"] = self._ocr_text()
        if vision["text"]:
            vision["description"] = f"Screen contains text: {vision['text'][:500]}"
        return screen, window, vision

    def _ocr_text(self) -> str:
        """Extract on-screen text via the macOS Vision framework (best-effort)."""
        try:
            import tempfile
            from pathlib import Path

            tmp = Path(tempfile.mktemp(suffix=".png"))
            subprocess.run(["screencapture", "-x", str(tmp)], capture_output=True, timeout=_TIMEOUT)
            script = f"""
            use framework "Vision"
            use framework "AppKit"
            set imagePath to POSIX file "{tmp}"
            set imageRep to current application's NSImage's alloc()'s initWithContentsOfFile:imagePath
            set cgImage to imageRep's CGImageForProposedRect:(current application's NSZeroRect) context:(missing value) hints:(missing value)
            set requestHandler to current application's VNImageRequestHandler's alloc()'s initWithCGImage:cgImage options:(current application's NSDictionary's dictionary())
            set textRequest to current application's VNRecognizeTextRequest's alloc()'s init()
            set textRequest's recognitionLevel to 1
            requestHandler's performRequests:{{textRequest}} |error|:(missing value)
            set results to textRequest's results()
            set outputText to ""
            repeat with observation in results
                set topCandidate to observation's topCandidates():'s firstObject()
                set outputText to outputText & (topCandidate's |string|() as text) & linefeed
            end repeat
            return outputText
            """
            out = _run_osascript(script, timeout=15)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            return out
        except Exception as exc:
            logger.debug("OCR unavailable: %s", exc)
            return ""

    def _running_apps(self) -> list[str]:
        """Visible running applications (best-effort)."""
        try:
            out = _run_osascript(
                'tell application "System Events" to get name of every application process whose background only is false'
            )
        except Exception as exc:  # defensive
            logger.debug("running apps detection failed: %s", exc)
            out = ""
        if not out:
            return []
        return [a.strip() for a in out.split(", ") if a.strip()]


def format_for_prompt(snapshot: ContextSnapshot) -> str:
    """Prompt-ready one-liner (same shape as the legacy formatter)."""
    return snapshot.to_prompt()


__all__ = ["ContextEngine", "ContextSnapshot", "format_for_prompt"]
