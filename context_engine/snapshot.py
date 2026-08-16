"""Context Snapshot — полный снимок контекста пользователя.

Главный API: get_snapshot() — объединяет app_monitor + browser_url.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from context_engine.app_monitor import get_active_app, get_active_app_cached, get_app_category
from context_engine.browser_url import get_browser_url, classify_url_domain

logger = logging.getLogger(__name__)

# Count how many times we've checked context (for stats)
_context_check_count: int = 0


@dataclass
class ContextSnapshot:
    """Полный снимок контекста пользователя в данный момент."""
    
    # Active application
    app_name: str = ""
    app_bundle_id: str = ""
    app_pid: int = 0
    app_category: str = "other"
    
    # Browser (if applicable)
    browser_url: str = ""
    browser_page_title: str = ""
    browser_domain: str = ""
    url_category: str = ""
    
    # Metadata
    timestamp: str = ""
    check_count: int = 0


def get_snapshot(use_cache: bool = False) -> ContextSnapshot:
    """Get a complete context snapshot.
    
    Args:
        use_cache: If True, uses 1-second cache for app detection.
                   Default False for on-demand, True for polling loops.
    
    Returns:
        ContextSnapshot with current app and browser info.
    """
    global _context_check_count
    _context_check_count += 1
    
    snapshot = ContextSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        check_count=_context_check_count,
    )
    
    try:
        # 1. Active app (fast, ~10ms)
        if use_cache:
            app = get_active_app_cached()
        else:
            app = get_active_app()
        
        snapshot.app_name = app.get("name", "")
        snapshot.app_bundle_id = app.get("bundle_id", "")
        snapshot.app_pid = app.get("pid", 0)
        snapshot.app_category = get_app_category(snapshot.app_bundle_id)
        
        # 2. Browser URL (~100ms, only if browser is active)
        if snapshot.app_category == "browser":
            url_info = get_browser_url(snapshot.app_name)
            snapshot.browser_url = url_info.get("url", "")
            snapshot.browser_page_title = url_info.get("title", "")
            snapshot.browser_domain = url_info.get("domain", "")
            snapshot.url_category = classify_url_domain(snapshot.browser_domain)
        
    except Exception as exc:
        logger.warning("Context snapshot failed: %s", exc)
    
    return snapshot


def format_context_for_prompt(snapshot: ContextSnapshot) -> str:
    """Format the context snapshot for LLM system prompt insertion."""
    parts = []
    
    parts.append(f"Active: {snapshot.app_name} ({snapshot.app_category})")
    
    if snapshot.browser_url:
        parts.append(f"URL: {snapshot.browser_url}")
        if snapshot.browser_page_title:
            parts.append(f"Page: {snapshot.browser_page_title[:60]}")
        if snapshot.url_category:
            parts.append(f"URL category: {snapshot.url_category}")
    
    return " | ".join(parts)
