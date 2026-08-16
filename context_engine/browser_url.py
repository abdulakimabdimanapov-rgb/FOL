"""Browser URL Parser — получает URL из активного браузера через AppleScript.

Поддерживает: Chrome, Safari, Arc, Edge
"""

import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# AppleScript для каждого браузера
BROWSER_SCRIPTS: dict[str, str] = {
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


def get_browser_url(app_name: str) -> dict[str, Any]:
    """Get the URL and page title from the specified browser.
    
    Args:
        app_name: "Google Chrome" | "Safari" | "Arc" | etc.
    
    Returns:
        {"url": "https://github.com/...", "title": "Page Title", "domain": "github.com"}
    """
    script = BROWSER_SCRIPTS.get(app_name)
    if not script:
        return {"url": "", "title": "", "domain": ""}
    
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"url": "", "title": "", "domain": ""}
        
        parts = result.stdout.strip().split("|||")
        url = parts[0] if len(parts) > 0 else ""
        
        # Extract domain from URL
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
    except subprocess.TimeoutExpired:
        return {"url": "", "title": "", "domain": ""}
    except Exception as exc:
        logger.debug("get_browser_url(%s) failed: %s", app_name, exc)
        return {"url": "", "title": "", "domain": ""}


def classify_url_domain(domain: str) -> str:
    """Classify a URL domain into a category."""
    CATEGORIES: dict[str, str] = {
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
    
    for key, category in CATEGORIES.items():
        if key in domain:
            return category
    return "browsing"
