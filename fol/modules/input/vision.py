"""Vision module — screen analysis for FOL.

Handles:
- Screenshot capture
- Screen content analysis (OCR)
- Active window detection
- Running apps detection
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FOL_DIR = Path.home() / ".fol"
SCREENSHOTS_DIR = FOL_DIR / "screenshots"


@dataclass
class ScreenContent:
    """Represents analyzed screen content."""

    timestamp: float = field(default_factory=time.time)
    screenshot_path: str = ""
    active_window: str = ""
    active_app: str = ""
    window_title: str = ""
    screen_text: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ScreenAnalyzer:
    """Analyzes the screen using macOS tools."""

    def __init__(self) -> None:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        self._last_capture: ScreenContent | None = None

    def capture_screenshot(self, filename: str = "") -> str:
        """Take a screenshot and return the path."""
        if not filename:
            filename = f"screen_{int(time.time())}.png"
        filepath = SCREENSHOTS_DIR / filename
        try:
            subprocess.run(["screencapture", "-x", str(filepath)], check=True, timeout=5)
            return str(filepath)
        except Exception as exc:
            logger.error("Screenshot failed: %s", exc)
            return ""

    def get_active_window(self) -> dict[str, str]:
        """Get information about the active window."""
        try:
            script = '''
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                set appName to name of frontApp
                set pid to unix id of frontApp
            end tell
            return appName & "|||" & pid
            '''
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and "|||" in result.stdout:
                parts = result.stdout.strip().split("|||")
                app_name = parts[0]
                pid = parts[1] if len(parts) > 1 else ""
                title = self._get_window_title(app_name)
                return {"app": app_name, "title": title, "pid": pid}
        except Exception as exc:
            logger.error("Failed to get active window: %s", exc)
        return {"app": "Unknown", "title": "", "pid": ""}

    def _get_window_title(self, app_name: str) -> str:
        """Get the title of the frontmost window of an app."""
        try:
            script = f'''
            tell application "System Events"
                set frontProcess to first application process whose name is "{app_name}"
                set frontWindow to front window of frontProcess
                set windowTitle to name of frontWindow
            end tell
            return windowTitle
            '''
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return ""

    def get_screen_text(self) -> str:
        """Extract text from the screen using macOS Vision framework OCR."""
        try:
            temp_path = SCREENSHOTS_DIR / "_temp_ocr.png"
            subprocess.run(["screencapture", "-x", str(temp_path)], check=True, timeout=5)

            script = f'''
            use framework "Vision"
            use framework "AppKit"

            set imagePath to POSIX file "{temp_path}"
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
            '''
            result = subprocess.run(
                ["osascript", "-l", "AppleScript", "-e", script],
                capture_output=True, text=True, timeout=15,
            )

            if temp_path.exists():
                temp_path.unlink()

            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as exc:
            logger.debug("OCR not available: %s", exc)
        return ""

    def analyze_screen(self) -> ScreenContent:
        """Perform a full screen analysis."""
        screenshot_path = self.capture_screenshot()
        window_info = self.get_active_window()
        screen_text = self.get_screen_text()

        content = ScreenContent(
            screenshot_path=screenshot_path,
            active_window=window_info.get("app", ""),
            active_app=window_info.get("app", ""),
            window_title=window_info.get("title", ""),
            screen_text=screen_text[:5000] if screen_text else "",
        )
        content.description = self._generate_description(content)
        self._last_capture = content
        return content

    def _generate_description(self, content: ScreenContent) -> str:
        parts = []
        if content.active_app:
            parts.append(f"Active application: {content.active_app}")
        if content.window_title:
            parts.append(f"Window: {content.window_title}")
        if content.screen_text:
            parts.append(f"Screen contains text: {content.screen_text[:500]}")
        if not parts:
            parts.append("Screen captured (no detailed analysis available)")
        return ". ".join(parts)

    def get_running_apps(self) -> list[str]:
        """Get list of running applications."""
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of every application process whose background only is false'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return [a.strip() for a in result.stdout.strip().split(", ") if a.strip()]
        except Exception:
            pass
        return []

    @property
    def last_capture(self) -> ScreenContent | None:
        return self._last_capture
