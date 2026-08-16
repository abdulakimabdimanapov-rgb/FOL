"""Vault Manager — CRUD операции и управление структурой Obsidian vault.

Функции:
- init_vault(): создать структуру папок + _index.md
- save_note(): создать/обновить заметку с frontmatter
- get_note(): прочитать заметку
- create_project(): создать новый проект
- create_idea(): сохранить идею
- create_decision(): записать решение
- ensure_daily_note(): создать/открыть today's daily note
- append_to_section(): добавить текст в секцию заметки
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from obsidian.client import write_note, read_note, patch_note, search
from obsidian.client import ObsidianNotFoundError, check_connection
from obsidian.config import (
    VAULT_PATH,
    VAULT_STRUCTURE,
    INDEX_FOLDERS,
    TEMPLATES,
)

logger = logging.getLogger(__name__)


_FOLDER_DESCRIPTIONS = {
    "Profile": "Кто я и как я работаю",
    "Projects": "Проекты и их статусы",
    "Knowledge": "База знаний",
    "Goals": "Цели и roadmap",
    "Ideas": "Банк идей",
    "Tasks": "Задачи",
    "Decisions": "Архитектурные решения",
    "Conversations": "Диалоги с FOL",
    "Daily": "Ежедневные заметки",
    "Episodic": "Хронология событий",
    "Templates": "Шаблоны заметок",
    "Archive": "Архив",
}


def init_vault() -> None:
    """Create vault directory structure, indices, templates and Profile.

    Запускается при первом подключении к Obsidian (или вручную).
    Создаёт:
    - все папки из VAULT_STRUCTURE
    - _index.md для каждой основной папки
    - шаблоны заметок в Templates/
    - Profile/Profile.md (если нет)
    """
    if not check_connection():
        logger.warning(
            "Obsidian vault not connected. "
            "Install the Local REST API plugin and add OBSIDIAN_API_KEY to .env"
        )
        return False

    # Create folders via filesystem
    VAULT_PATH.mkdir(parents=True, exist_ok=True)

    for folder in VAULT_STRUCTURE:
        folder_path = VAULT_PATH / folder
        folder_path.mkdir(exist_ok=True)

    # Create _index.md for the main folders
    for folder in INDEX_FOLDERS:
        index_path = f"{folder}/_index"
        try:
            read_note(index_path)
            logger.debug("Index exists: %s", index_path)
        except ObsidianNotFoundError:
            desc = _FOLDER_DESCRIPTIONS.get(folder, "")
            content = (
                f"# {folder}\n\n"
                f"*{desc} — авто-сгенерировано FOL.*\n\n"
                "## Заметки\n\n"
                "## Links\n"
            )
            write_note(index_path, content)
            logger.info("Created _index.md for %s", folder)

    # Create note templates in Templates/
    for name, body in TEMPLATES.items():
        template_path = f"Templates/{name.replace('.md', '')}"
        try:
            read_note(template_path)
        except ObsidianNotFoundError:
            write_note(template_path, body)
            logger.info("Created template: %s", name)

    # Create Profile/Profile.md skeleton if missing
    try:
        read_note("Profile/Profile")
    except ObsidianNotFoundError:
        write_note(
            "Profile/Profile",
            "# Профиль\n\n"
            "## О себе\n\n"
            "## Предпочтения\n\n"
            "## Проекты\n\n"
            "## Цели\n\n"
            "## Links\n",
        )
        logger.info("Created Profile/Profile.md")

    logger.info(
        "Vault initialised with %d folders at %s",
        len(VAULT_STRUCTURE),
        VAULT_PATH,
    )
    return True


def refresh_indices() -> dict[str, str]:
    """Regenerate _index.md for each main folder from its current notes.

    Сканирует папку на диске и собирает список [[wikilinks]] на все заметки
    (кроме самого _index), сохраняя его в _index.md.

    Returns:
        {folder: "updated" | "error"}
    """
    results: dict[str, str] = {}
    for folder in INDEX_FOLDERS:
        folder_path = VAULT_PATH / folder
        if not folder_path.is_dir():
            continue
        notes = sorted(
            p for p in folder_path.rglob("*.md") if p.name != "_index.md"
        )
        lines = [f"# {folder}", ""]
        if notes:
            lines.append("## Заметки")
            for p in notes:
                rel = p.relative_to(VAULT_PATH).with_suffix("").as_posix()
                lines.append(f"- [[{rel}]]")
            lines.append("")
        desc = _FOLDER_DESCRIPTIONS.get(folder, "")
        lines.append(f"*{desc} — авто-сгенерировано FOL. Обновлено: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}*")
        try:
            write_note(f"{folder}/_index", "\n".join(lines))
            results[folder] = f"updated ({len(notes)} notes)"
        except Exception as exc:
            results[folder] = f"error: {exc}"
            logger.warning("Failed to refresh index %s: %s", folder, exc)
    return results


def bootstrap() -> dict[str, Any]:
    """One-shot setup: init structure + indices + sync ~/.secondself.

    Returns:
        {"initialised": bool, "indices": {...}, "sync": {...}}
    """
    ok = init_vault()
    indices = refresh_indices() if ok else {}
    try:
        from obsidian.sync import sync_to_obsidian
        sync = sync_to_obsidian()
    except Exception as exc:
        sync = {"_error": str(exc)}
    return {"initialised": ok, "indices": indices, "sync": sync}


def get_note(vault_path: str) -> str:
    """Read a note's markdown content.

    Args:
        vault_path: e.g. "Projects/FOL/architecture"

    Returns:
        Full markdown content
    """
    return read_note(vault_path)


def save_note(
    vault_path: str,
    content: str,
    tags: list[str] | None = None,
    source: str = "orchestrator",
    auto_link: bool = True,
) -> dict[str, Any]:
    """Write a note with YAML frontmatter.

    NEW: auto_link=True запускает Semantic Linker после сохранения.
    Это создаёт [[wikilinks]] между заметками — живая память.

    Args:
        vault_path: e.g. "Knowledge/obsidian-api"
        content: markdown body (without frontmatter)
        tags: optional tags
        source: "orchestrator" | "user" | "agent"
        auto_link: run semantic linker after write (default: True)

    Returns:
        API response from write_note
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Normalize tags: LLMs sometimes pass a string ("programming, AI") or
    # even a nested list instead of the documented list[str]. Defensive:
    # accept str, list, or None and always produce a flat list of strings.
    if isinstance(tags, str):
        normalized_tags = [tags]
    elif isinstance(tags, (list, tuple)):
        normalized_tags = []
        for t in tags:
            if isinstance(t, str):
                normalized_tags.append(t)
            elif isinstance(t, (list, tuple)):
                normalized_tags.extend(str(x) for x in t)
            else:
                normalized_tags.append(str(t))
    else:
        normalized_tags = []
    all_tags = normalized_tags + ["fol"]
    tag_str = ", ".join(all_tags)

    full_content = f"""---
created: {now}
updated: {now}
tags: [{tag_str}]
source: {source}
---

{content}
"""

    result = write_note(vault_path, full_content)

    # Живая память: авто-линковка после каждой записи
    # Запускается в background thread чтобы не блокировать event loop
    if auto_link:
        try:
            import threading
            threading.Thread(
                target=_run_auto_link,
                args=(vault_path, content),
                daemon=True,
            ).start()
        except Exception as exc:
            logger.debug("Auto-link thread start failed for %s: %s", vault_path, exc)

    return result


def _run_auto_link(vault_path: str, content: str) -> None:
    """Run auto-linking in a background thread."""
    try:
        from obsidian.linker import auto_link_note
        auto_link_note(vault_path, content)
        logger.debug("Auto-linked: %s", vault_path)
    except Exception as exc:
        logger.debug("Auto-link skipped for %s: %s", vault_path, exc)


def append_to_section(
    vault_path: str,
    section: str,
    content: str,
) -> dict[str, Any]:
    """Append content to a specific heading in a note.

    Args:
        vault_path: e.g. "Daily/2026-04-12"
        section: heading name, e.g. "Tasks" or "Notes"
        content: text to append, e.g. "- [ ] New task"

    Returns:
        API response from patch_note
    """
    heading = section.lstrip("#").strip()
    return patch_note(
        vault_path=vault_path,
        target_type="heading",
        target=[heading],
        operation="append",
        content=f"\n{content}",
    )


def create_project(name: str, description: str) -> str:
    """Create a new project folder and index note.

    Args:
        name: project name (used for slug and title)
        description: brief description

    Returns:
        vault path to the project index, e.g. "Projects/my-project"
    """
    slug = _slugify(name)
    vault_path = f"Projects/{slug}"

    # Create project folder via filesystem
    project_dir = VAULT_PATH / "Projects" / slug
    project_dir.mkdir(parents=True, exist_ok=True)

    content = f"""# {name}

{description}

## Status
🟡 In progress

## Tasks
- [ ] Initial setup

## Links
"""

    save_note(vault_path, content, tags=["project"])
    logger.info("Created project: %s", vault_path)
    return vault_path


def create_idea(title: str, body: str) -> str:
    """Save a new idea to the vault.

    Args:
        title: idea title
        body: idea description (markdown)

    Returns:
        vault path, e.g. "Ideas/2026-04-12-new-idea"
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title)
    vault_path = f"Ideas/{date}-{slug}"

    content = f"""# {title}

{body}

## Status
💡 Idea

## Links
"""

    save_note(vault_path, content, tags=["idea"])
    logger.info("Created idea: %s", vault_path)
    return vault_path


def create_decision(
    title: str,
    context: str,
    decision: str,
    alternatives: list[str],
) -> str:
    """Log an architectural or design decision.

    Args:
        title: decision title
        context: why this decision was needed
        decision: what was decided
        alternatives: other approaches considered

    Returns:
        vault path, e.g. "Decisions/2026-04-12-decision-title"
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = _slugify(title)
    vault_path = f"Decisions/{date}-{slug}"

    alts = "\n".join(f"- {a}" for a in alternatives)
    content = f"""# {title}

## Context
{context}

## Decision
{decision}

## Alternatives
{alts}

## Status
✅ Accepted
"""

    save_note(vault_path, content, tags=["decision"])
    logger.info("Created decision: %s", vault_path)
    return vault_path


def ensure_daily_note(date: str | None = None) -> str:
    """Get or create today's daily note.

    Args:
        date: "2026-04-12" format. Defaults to today UTC.

    Returns:
        Vault path to the daily note, e.g. "Daily/2026-04-12"
    """
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    vault_path = f"Daily/{date}"

    try:
        read_note(vault_path)
        logger.debug("Daily note exists: %s", vault_path)
    except ObsidianNotFoundError:
        weekday = datetime.now(timezone.utc).strftime("%A")
        content = f"""# {date} — {weekday}

## 🎯 Goals
- 

## ✅ Done
- 

## 📝 Notes
- 

## 🔗 Links
"""
        save_note(vault_path, content, tags=["daily"])
        logger.info("Created daily note: %s", vault_path)

    return vault_path


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text
