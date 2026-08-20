"""Tests for the canonical unified context engine (fol/modules/input/context.py).

Covers: structured snapshot contract, active-app + browser context, screen /
vision best-effort degradation, permission/timeout failures, empty and
malformed context, caching, and the prompt format.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from modules.input.context import ContextEngine, ContextSnapshot, format_for_prompt


# ---------------------------------------------------------------------------
# Structured contract
# ---------------------------------------------------------------------------

class TestContextSnapshotContract:
    def test_to_dict_has_unified_structure(self):
        snap = ContextSnapshot(timestamp="2026-01-01T00:00:00Z", app_name="Safari", app_category="browser")
        d = snap.to_dict()
        assert set(d.keys()) == {
            "timestamp", "check_count", "active_app", "browser",
            "screen", "window", "vision", "user_activity",
        }
        assert d["active_app"]["name"] == "Safari"
        assert d["active_app"]["category"] == "browser"
        assert d["screen"] == {} and d["vision"] == {}

    def test_to_prompt_matches_legacy_format(self):
        snap = ContextSnapshot(
            app_name="Safari",
            app_category="browser",
            browser_url="https://github.com/foo",
            browser_page_title="FOL repo",
            url_category="development",
        )
        prompt = snap.to_prompt()
        assert "Active: Safari (browser)" in prompt
        assert "URL: https://github.com/foo" in prompt
        assert "Page: FOL repo" in prompt
        assert "URL category: development" in prompt

    def test_format_for_prompt_delegates(self):
        snap = ContextSnapshot(app_name="Terminal", app_category="terminal")
        assert format_for_prompt(snap) == "Active: Terminal (terminal)"


# ---------------------------------------------------------------------------
# Capture with mocked AppleScript
# ---------------------------------------------------------------------------

class TestContextEngineCapture:
    def test_capture_fills_app_context(self):
        engine = ContextEngine()
        osascript_outputs = iter([
            "Google Chrome|||com.google.Chrome|||12345",
            "",  # browser_url script (mocked below separately)
        ])
        with patch("modules.input.context._run_osascript", side_effect=lambda script, timeout=5: next(osascript_outputs, "")):
            snap = engine.capture(use_cache=False)
        assert snap.app_name == "Google Chrome"
        assert snap.app_bundle_id == "com.google.Chrome"
        assert snap.app_pid == 12345
        assert snap.app_category == "browser"

    def test_capture_browser_url_when_browser_active(self):
        engine = ContextEngine()
        calls = []
        def fake_run(script, timeout=5):
            calls.append(script)
            if "frontmost is true" in script:
                return "Safari|||com.apple.Safari|||77"
            if "URL of currentTab" in script:
                return "https://github.com/foo/bar|||FOL repo"
            return ""
        with patch("modules.input.context._run_osascript", side_effect=fake_run):
            snap = engine.capture(use_cache=False)
        assert snap.browser_url == "https://github.com/foo/bar"
        assert snap.browser_domain == "github.com"
        assert snap.url_category == "development"
        assert snap.browser_page_title == "FOL repo"

    def test_capture_non_browser_skips_url(self):
        engine = ContextEngine()
        def fake_run(script, timeout=5):
            if "frontmost is true" in script:
                return "Xcode|||com.apple.dt.Xcode|||9"
            return ""
        with patch("modules.input.context._run_osascript", side_effect=fake_run):
            snap = engine.capture(use_cache=False)
        assert snap.app_category == "ide"
        assert snap.browser_url == ""

    def test_capture_osascript_failure_degrades(self):
        engine = ContextEngine()
        with patch("modules.input.context._run_osascript", return_value="") as mock_run:
            snap = engine.capture(use_cache=False)
        assert snap.app_name == "unknown"
        assert snap.app_category == "other"
        assert snap.browser_url == ""
        assert mock_run.called

    def test_capture_never_raises_on_exceptions(self):
        engine = ContextEngine()

        def boom(script, timeout=5):
            raise RuntimeError("AppleScript permission denied")

        with patch("modules.input.context._run_osascript", side_effect=boom):
            snap = engine.capture(use_cache=False)
        assert snap is not None
        assert snap.app_name == "unknown"

    def test_capture_vision_best_effort(self):
        """With screen capture unavailable, the screen/vision fields degrade
        without raising (no real screencapture runs in tests)."""
        engine = ContextEngine()
        with patch("modules.input.context._run_osascript", return_value=""), \
             patch("modules.input.context.subprocess.run", side_effect=RuntimeError("no display")):
            snap = engine.capture(use_cache=False, with_vision=True)
        assert snap.screen == {"captured": False, "path": ""}
        assert snap.window == {"title": "", "pid": ""}
        assert snap.vision == {"text": "", "description": ""}

    def test_capture_malformed_osascript_output(self):
        engine = ContextEngine()
        with patch("modules.input.context._run_osascript", return_value="garbage without separators"):
            snap = engine.capture(use_cache=False)
        assert snap.app_name == "garbage without separators"
        assert snap.app_pid == 0

    def test_capture_user_activity_running_apps(self):
        engine = ContextEngine()
        def fake_run(script, timeout=5):
            if "frontmost is true" in script:
                return "Terminal|||com.apple.Terminal|||1"
            if "background only is false" in script:
                return "Safari, Terminal, Xcode"
            return ""
        with patch("modules.input.context._run_osascript", side_effect=fake_run):
            snap = engine.capture(use_cache=False)
        assert snap.user_activity["running_apps"] == ["Safari", "Terminal", "Xcode"]

    def test_capture_caching(self):
        engine = ContextEngine()
        counter = {"n": 0}
        def fake_run(script, timeout=5):
            if "frontmost is true" in script:
                counter["n"] += 1
                return "Terminal|||com.apple.Terminal|||1"
            return ""
        with patch("modules.input.context._run_osascript", side_effect=fake_run):
            engine.capture(use_cache=False)
            engine.capture(use_cache=True)
            engine.capture(use_cache=True)
        assert counter["n"] == 1  # cached after the first uncached call

    def test_timestamp_and_check_count(self):
        engine = ContextEngine()
        with patch("modules.input.context._run_osascript", return_value=""):
            snap = engine.capture(use_cache=False)
        assert snap.check_count == 1
        assert snap.timestamp  # ISO timestamp present
