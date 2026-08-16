"""Daily Tracker — автоматическая запись действий пользователя.

Каждый день создаёт:
1. Запись в episodic.md: "User active on YYYY-MM-DD"
2. Сводку активности в конце дня
3. Отслеживает контекст (какое приложение, что делал)

Используется orchestrator-ом для автоматической записи.
Может быть вызван вручную через инструмент save_daily_summary.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# In-memory buffer for today's activities
_daily_activities: list[dict[str, Any]] = []
_last_app_log_time: dict[str, float] = {}  # app_name → timestamp, for debounce
_APP_LOG_DEBOUNCE_SECONDS: float = 60.0  # Don't log same app more than once per minute


def _log_to_obsidian_daily(summary: str, category: str, app_name: str) -> None:
    """Log activity to today's Obsidian daily note.

    Never raises — silently skips if Obsidian is unavailable.
    """
    try:
        from obsidian.daily import log_to_daily
        section_map = {
            "coding": "## ✅ Done",
            "learning": "## 📝 Notes",
            "writing": "## ✅ Done",
            "browsing": "## 📝 Notes",
            "communication": "## 📝 Notes",
            "daily": "## 📝 Notes",
            "planning": "## 🎯 Focus",
        }
        section = section_map.get(category, "## 📝 Notes")

        # Add app context if available
        log_summary = summary
        if app_name:
            log_summary = f"**{app_name}** — {summary}"

        log_to_daily(
            summary=log_summary,
            category=category,
            section=section,
        )
    except Exception:
        pass  # Silent fallback — Obsidian may not be available


def log_activity(
    summary: str,
    app_name: str = "",
    category: str = "daily",
) -> None:
    """Record a user activity in the daily buffer and episodic.md.
    
    Writes to:
    1. In-memory buffer (for get_today_summary)
    2. episodic.md (for build_system_prompt)
    3. Obsidian Daily/YYYY-MM-DD.md (living memory)

    Args:
        summary: What the user did (e.g. "Edited architecture.md in Obsidian")
        app_name: Active application name
        category: "work" | "learning" | "browsing" | "daily" | "coding"
    """
    from utils.episodic_writer import append_event
    
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%H:%M")
    
    activity = {
        "time": timestamp,
        "summary": summary,
        "app": app_name,
        "category": category,
    }
    _daily_activities.append(activity)
    
    # Write to episodic.md
    try:
        append_event(
            summary=f"[{timestamp}] {summary}",
            category=category,
            source="daily_tracker",
        )
    except Exception as exc:
        logger.warning("Failed to log daily activity: %s", exc)
    
    # Write to Obsidian daily note (living memory) — silent fallback
    _log_to_obsidian_daily(summary, category, app_name)
    
    logger.debug("Daily activity logged: %s", summary[:60])


def log_app_activity(app_name: str, window_title: str = "") -> None:
    """Log that the user switched to or is using an application.
    
    This is called periodically by the context engine.
    Debounced: same app won't be logged more than once per 60 seconds.
    
    Args:
        app_name: "Google Chrome", "Visual Studio Code", etc.
        window_title: Current window title for context
    """
    import time
    now = time.time()
    
    # Debounce: check if we logged this app recently
    last_logged = _last_app_log_time.get(app_name, 0.0)
    if now - last_logged < _APP_LOG_DEBOUNCE_SECONDS:
        return  # Too soon, skip
    
    # Update last logged time
    _last_app_log_time[app_name] = now
    
    # Check if this is a new/different activity (additional check)
    if _daily_activities:
        last = _daily_activities[-1]
        if last.get("app") == app_name and now - _last_app_log_time.get(app_name, 0) < _APP_LOG_DEBOUNCE_SECONDS:
            return  # Same app, skip
    
    # Determine category
    category = _categorize_app(app_name)
    
    # Build summary
    summary = f"Using {app_name}"
    if window_title:
        short_title = window_title[:80]
        summary = f"Using {app_name} — {short_title}"
    
    log_activity(
        summary=summary,
        app_name=app_name,
        category=category,
    )


def _categorize_app(app_name: str) -> str:
    """Categorize an application."""
    APP_CATEGORIES = {
        "Google Chrome": "browsing",
        "Safari": "browsing",
        "Arc": "browsing",
        "Visual Studio Code": "coding",
        "Code": "coding",
        "Xcode": "coding",
        "Terminal": "coding",
        "iTerm2": "coding",
        "Obsidian": "writing",
        "Notes": "writing",
        "Slack": "communication",
        "Discord": "communication",
        "Spotify": "media",
        "Music": "media",
        "Calendar": "planning",
        "ChatGPT": "learning",
    }
    return APP_CATEGORIES.get(app_name, "daily")


def get_today_summary() -> str:
    """Get a human-readable summary of today's activities.
    
    Returns:
        Markdown-formatted summary of what the user did today.
    """
    if not _daily_activities:
        return "No activity recorded today."
    
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"# Daily Summary — {today}", ""]
    
    # Group by category
    categories: dict[str, list[str]] = {}
    for act in _daily_activities:
        cat = act.get("category", "daily")
        if cat not in categories:
            categories[cat] = []
        time_str = act.get("time", "")
        summary = act.get("summary", "")
        categories[cat].append(f"- {time_str} — {summary}")
    
    # Sort categories: coding first, then learning, etc.
    category_order = ["coding", "learning", "writing", "browsing", "communication", "daily", "planning", "media"]
    for cat in category_order:
        if cat in categories:
            lines.append(f"## {cat.capitalize()}")
            lines.extend(categories[cat])
            lines.append("")
    
    return "\n".join(lines)


def reset_daily() -> None:
    """Reset the daily buffer (called at midnight or on new day)."""
    global _daily_activities
    _daily_activities = []
    _last_app_log_time.clear()


def get_recent_apps(n: int = 5) -> list[str]:
    """Get the N most recently used applications today."""
    apps = []
    for act in reversed(_daily_activities):
        app = act.get("app", "")
        if app and app not in apps:
            apps.append(app)
            if len(apps) >= n:
                break
    return apps
