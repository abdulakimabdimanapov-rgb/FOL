"""Daily Notes Manager — ежедневные заметки в Obsidian vault.

Каждый день:
1. Авто-создание Daily/YYYY-MM-DD.md при старте orchestrator
2. Логирование активности пользователя в Daily note
3. Авто-сводка дня (summary)
4. Семантическая связь с Episodic/events.md

Используется:
- orchestrator/server.py: на старте вызывает ensure_daily()
- utils/daily_tracker.py: логирует активность в Obsidian
- LLM tools: для записи и чтения ежедневных заметок
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from obsidian.client import read_note, write_note, patch_note, check_connection
from obsidian.client import ObsidianNotFoundError
from obsidian.linker import auto_link_note

logger = logging.getLogger(__name__)

# Cache: today's vault path (avoid re-checking every call)
_today_vault_path: str = ""
_today_date: str = ""


def _today() -> str:
    """Get today's date string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _weekday() -> str:
    """Get today's weekday name."""
    return datetime.now(timezone.utc).strftime("%A")


def ensure_daily_note() -> str:
    """Create today's daily note if it doesn't exist.

    Returns:
        Vault path to today's daily note, e.g. "Daily/2026-07-27"
    """
    global _today_vault_path, _today_date

    date = _today()
    vault_path = f"Daily/{date}"

    # Return cached if still today
    if _today_date == date and _today_vault_path:
        return _today_vault_path

    _today_date = date
    _today_vault_path = vault_path

    # Check if Obsidian is connected
    if not check_connection():
        logger.debug("Obsidian not connected — skipping daily note creation")
        return vault_path

    try:
        read_note(vault_path)
        logger.debug("Daily note exists: %s", vault_path)
        return vault_path
    except ObsidianNotFoundError:
        pass

    # Create daily note with template
    weekday = _weekday()
    content = f"""# {date} — {weekday}

## 🎯 Focus
- 

## ✅ Done
- 

## 📝 Notes
- 

## 🔗 Links
"""

    try:
        write_note(vault_path, content)
        logger.info("Created daily note in Obsidian: %s", vault_path)

        # Auto-link with Episodic/events
        try:
            auto_link_note(vault_path, content)
        except Exception as exc:
            logger.debug("Auto-link skipped for daily note: %s", exc)
    except Exception as exc:
        logger.warning("Failed to create daily note in Obsidian: %s", exc)

    return vault_path


def log_to_daily(
    summary: str,
    category: str = "notes",
    section: str = "## 📝 Notes",
    timestamp: str | None = None,
) -> bool:
    """Log an activity/note to today's Daily note in Obsidian.

    Args:
        summary: What happened (e.g. "Learned about Obsidian API - [[Knowledge/obsidian-api]]")
        category: "notes" | "done" | "focus" | "links"
        section: Which heading to append to. Default "## 📝 Notes".
                 Other options: "## ✅ Done", "## 🎯 Focus", "## 🔗 Links"
        timestamp: Optional time override. Defaults to current HH:MM UTC.

    Returns:
        True if logged successfully, False if Obsidian unavailable.
    """
    vault_path = ensure_daily_note()

    if not check_connection():
        logger.debug("Obsidian not connected — skipping daily log")
        return False

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%H:%M")

    # Clean section name for API
    section_name = section.lstrip("#").strip()

    line = f"- [{timestamp}] {summary}"

    try:
        patch_note(
            vault_path=vault_path,
            target_type="heading",
            target=[section_name],
            operation="append",
            content=f"\n{line}",
        )
        logger.debug("Logged to daily note %s: %s", vault_path, line[:60])
        return True
    except Exception as exc:
        logger.warning("Failed to log to daily note %s: %s", vault_path, exc)
        return False


def log_app_usage(app_name: str, window_title: str = "", url: str = "") -> bool:
    """Log that the user used an application to today's daily note.

    Args:
        app_name: "Visual Studio Code", "Google Chrome", etc.
        window_title: Current window/file title
        url: Browser URL if applicable

    Returns:
        True if logged successfully.
    """
    parts = [app_name]
    if window_title:
        parts.append(window_title[:80])
    if url:
        parts.append(url[:100])

    summary = " — ".join(parts)
    return log_to_daily(summary=summary, category="done", section="## ✅ Done")


def log_learning(topic: str, insights: str) -> bool:
    """Log a learning moment to today's daily note.

    Args:
        topic: What was learned
        insights: Key takeaways

    Returns:
        True if logged successfully.
    """
    summary = f"**{topic}**: {insights[:200]}"
    return log_to_daily(summary=summary, category="notes", section="## 📝 Notes")


def get_daily_note(date: str | None = None) -> str:
    """Read a daily note's content from Obsidian.

    Args:
        date: "2026-07-27" format. Defaults to today.

    Returns:
        Full markdown content of the daily note, or empty string.
    """
    if date is None:
        date = _today()

    vault_path = f"Daily/{date}"

    if not check_connection():
        return ""

    try:
        return read_note(vault_path)
    except ObsidianNotFoundError:
        return ""
    except Exception as exc:
        logger.warning("Failed to read daily note %s: %s", vault_path, exc)
        return ""


def get_daily_summary(date: str | None = None) -> str:
    """Get a concise summary of a day's activities.

    Reads the Daily note and extracts the Done section.

    Args:
        date: "2026-07-27" format. Defaults to today.

    Returns:
        Summary of what was done that day, or "No entries."
    """
    content = get_daily_note(date)
    if not content:
        return "No activity recorded."

    # Extract "Done" section
    lines = content.splitlines()
    in_done = False
    done_items = []
    for line in lines:
        if line.strip().startswith("## ✅ Done"):
            in_done = True
            continue
        if in_done:
            if line.startswith("## "):
                break
            if line.strip().startswith("-"):
                done_items.append(line.strip())

    if not done_items:
        return "No completed tasks logged."

    return "\n".join(done_items)


def get_week_summary() -> str:
    """Get a summary of the last 7 days.

    Returns:
        Markdown summary of the week.
    """
    from datetime import timedelta

    if not check_connection():
        return ""

    today = datetime.now(timezone.utc)
    sections = [f"# Week Summary — {(today - timedelta(days=7)).strftime('%Y-%m-%d')} to {today.strftime('%Y-%m-%d')}", ""]

    for i in range(7):
        day = today - timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        summary = get_daily_summary(date_str)
        if summary and summary != "No activity recorded.":
            sections.append(f"## {date_str} ({day.strftime('%A')})")
            sections.append(summary)
            sections.append("")

    if len(sections) <= 2:
        return "No activity this week."

    return "\n".join(sections)
