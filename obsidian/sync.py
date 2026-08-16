"""Memory Sync — синхронизация ~/.secondself/ ↔ Obsidian vault.

Двусторонняя синхронизация:
- → Obsidian: identity.md, preferences.md, episodic.md
- ← Obsidian: файлы, которые пользователь редактировал в Obsidian

Синхронизация односторонняя: .secondself → Obsidian (машина → человек).
Obsidian → .secondself только когда пользователь явно редактирует файл.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from obsidian.client import read_note, write_note, check_connection

logger = logging.getLogger(__name__)

MEMORY_DIR = Path.home() / ".secondself"

# Mapping: ~/.secondself/ file → Obsidian vault path
SYNC_MAP: dict[str, str] = {
    "identity.md": "Profile/identity",
    "preferences.md": "Profile/preferences",
    "episodic.md": "Episodic/events",
}


def sync_to_obsidian() -> dict[str, str]:
    """Sync all ~/.secondself/ files to Obsidian vault.

    One-way: .secondself → Obsidian.
    Obsidian is for human editing; .secondself is machine-generated.

    Returns:
        {filename: "synced" | "skipped: reason" | "error: reason"}
    """
    if not check_connection():
        logger.warning("Cannot sync: Obsidian not connected")
        return {"_error": "Obsidian not connected"}

    results: dict[str, str] = {}

    for filename, vault_path in SYNC_MAP.items():
        file_path = MEMORY_DIR / filename
        if not file_path.exists():
            results[filename] = "skipped (not found)"
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Add YAML frontmatter
            stem = Path(filename).stem
            full_content = f"""---
created: {now}
updated: {now}
tags: [fol, synced, {stem}]
source: identity-pipeline
---

{content}
"""
            write_note(vault_path, full_content)
            results[filename] = "synced"
            logger.info("Synced %s → Obsidian %s", filename, vault_path)

        except Exception as exc:
            results[filename] = f"error: {exc}"
            logger.error("Failed to sync %s: %s", filename, exc)

    return results


def sync_from_obsidian(target_file: str) -> bool:
    """Sync a single file from Obsidian back to ~/.secondself/.

    Useful when user edits a note in Obsidian and we want to
    pick up the changes.

    Args:
        target_file: "identity.md" | "preferences.md" | "episodic.md"

    Returns:
        True if synced successfully
    """
    vault_path = SYNC_MAP.get(target_file)
    if not vault_path:
        logger.warning("Unknown sync target: %s", target_file)
        return False

    if not check_connection():
        logger.warning("Cannot sync from Obsidian: not connected")
        return False

    try:
        content = read_note(vault_path)

        # Strip YAML frontmatter if present
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                content = parts[2].strip()

        file_path = MEMORY_DIR / target_file
        file_path.write_text(content, encoding="utf-8")
        logger.info("Synced from Obsidian: %s → ~/.secondself/%s", vault_path, target_file)
        return True

    except Exception as exc:
        logger.error("Failed to sync from Obsidian %s: %s", vault_path, exc)
        return False


def get_sync_status() -> dict[str, str | bool]:
    """Check sync status of all files.

    Returns:
        {
            "connected": True/False,
            "identity.md": "found" | "missing",
            "preferences.md": "found" | "missing",
            "episodic.md": "found" | "missing",
        }
    """
    status: dict[str, str | bool] = {
        "connected": check_connection(),
    }

    for filename in SYNC_MAP:
        file_path = MEMORY_DIR / filename
        status[filename] = "found" if file_path.exists() else "missing"

    return status
