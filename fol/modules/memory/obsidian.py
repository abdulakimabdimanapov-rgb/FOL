"""Obsidian memory integration for FOL.

Stores permanent memories as markdown files in an Obsidian vault.
When context limit is reached, memories survive in Obsidian and can be
reloaded into any new session — FOL never truly forgets.

Each memory category gets its own folder:
  FOL-Memory/
    ├── People/        — who the user is, names, relationships
    ├── Preferences/   — likes, dislikes, habits
    ├── Knowledge/     — facts, things learned
    ├── Conversations/ — important conversation summaries
    ├── Projects/      — ongoing work, goals
    └── Episodes/      — what happened when
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ObsidianMemory:
    """Persistent memory stored as markdown files in Obsidian vault."""

    CATEGORIES = [
        "People",
        "Preferences",
        "Knowledge",
        "Conversations",
        "Projects",
        "Episodes",
    ]

    def __init__(self, vault_path: str | Path | None = None) -> None:
        if vault_path:
            self._vault = Path(vault_path).expanduser()
        else:
            from config.settings import settings
            self._vault = Path(
                getattr(settings, "obsidian_vault", "~/Documents/Obsidian Vault/FOL-Memory")
            ).expanduser()

        self._vault.mkdir(parents=True, exist_ok=True)

        # Create category folders
        for cat in self.CATEGORIES:
            (self._vault / cat).mkdir(exist_ok=True)

        # Create index file
        self._index_file = self._vault / "FOL-Memory-Index.md"
        if not self._index_file.exists():
            self._write_index()

        logger.info("Obsidian memory initialized", vault=str(self._vault))

    # ─── Store Methods ───────────────────────────────────────────────────

    def store(
        self,
        content: str,
        category: str = "Knowledge",
        title: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a memory as a markdown file in Obsidian.

        Args:
            content: Memory content (markdown supported)
            category: One of CATEGORIES
            title: Note title (auto-generated if empty)
            tags: Obsidian tags
            metadata: Extra metadata for frontmatter

        Returns:
            Path to the created note
        """
        if category not in self.CATEGORIES:
            category = "Knowledge"

        if not title:
            title = self._generate_title(content)

        # Sanitize filename
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title)[:100]
        filepath = self._vault / category / f"{safe_title}.md"

        # Build frontmatter
        now = datetime.now()
        frontmatter_tags = ["fol", category.lower()]
        if tags:
            frontmatter_tags.extend(tags)

        frontmatter_lines = [
            "---",
            f"created: {now.isoformat()}",
            f"category: {category}",
            f"tags: [{', '.join(frontmatter_tags)}]",
        ]
        if metadata:
            for k, v in metadata.items():
                frontmatter_lines.append(f"{k}: {v}")
        frontmatter_lines.append("---")
        frontmatter_lines.append("")

        body = f"# {title}\n\n{content}\n"

        filepath.write_text("\n".join(frontmatter_lines) + body, encoding="utf-8")

        # Update index
        self._update_index(category, title, filepath.name)

        logger.info("Memory stored in Obsidian", category=category, title=title)
        return str(filepath)

    def store_conversation_summary(
        self,
        user_input: str,
        fol_response: str,
        summary: str = "",
    ) -> str:
        """Store a conversation summary in Obsidian."""
        now = datetime.now()
        title = f"Chat {now.strftime('%Y-%m-%d %H:%M')}"
        content = summary or f"**User:** {user_input}\n\n**FOL:** {fol_response}"
        return self.store(content, category="Conversations", title=title)

    def store_episode(
        self,
        event: str,
        context: str = "",
        importance: float = 0.5,
    ) -> str:
        """Store an episodic memory."""
        now = datetime.now()
        title = f"{now.strftime('%Y-%m-%d %H:%M')} — {event[:60]}"
        content = f"**Event:** {event}\n\n**Context:** {context}\n\n**Importance:** {importance}"
        return self.store(content, category="Episodes", title=title)

    # ─── Retrieval Methods ───────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        """Search all notes in the vault for a query."""
        query_lower = query.lower()
        results = []

        for md_file in self._vault.rglob("*.md"):
            if md_file.name == "FOL-Memory-Index.md":
                continue
            try:
                text = md_file.read_text(encoding="utf-8").lower()
                if query_lower in text:
                    # Extract category from path
                    rel = md_file.relative_to(self._vault)
                    category = rel.parts[0] if len(rel.parts) > 1 else "Unknown"
                    title = md_file.stem
                    results.append({
                        "path": str(md_file),
                        "category": category,
                        "title": title,
                    })
            except Exception:
                continue

        return results[:limit]

    def get_all_notes(self, category: str | None = None) -> list[dict[str, str]]:
        """List all notes, optionally filtered by category."""
        notes = []
        search_dir = self._vault / category if category else self._vault

        for md_file in search_dir.rglob("*.md"):
            if md_file.name == "FOL-Memory-Index.md":
                continue
            rel = md_file.relative_to(self._vault)
            cat = rel.parts[0] if len(rel.parts) > 1 else "Unknown"
            notes.append({
                "path": str(md_file),
                "category": cat,
                "title": md_file.stem,
            })

        return notes

    def read_note(self, filepath: str | Path) -> str:
        """Read a note's content."""
        path = Path(filepath)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def get_context_for_query(self, query: str, max_tokens: int = 2000) -> str:
        """Get relevant Obsidian context for a query (RAG)."""
        results = self.search(query, limit=5)
        if not results:
            return ""

        sections = []
        total_chars = 0
        char_limit = max_tokens * 4  # ~4 chars per token

        for r in results:
            content = self.read_note(r["path"])
            if total_chars + len(content) > char_limit:
                remaining = char_limit - total_chars
                if remaining > 100:
                    content = content[:remaining] + "..."
                else:
                    break
            sections.append(f"[{r['category']}] {r['title']}:\n{content}")
            total_chars += len(content)

        return "\n\n---\n\n".join(sections)

    # ─── Cleanup ─────────────────────────────────────────────────────────

    def delete_note(self, filepath: str | Path) -> bool:
        """Delete a note."""
        path = Path(filepath)
        if path.exists() and path.parent.parent == self._vault:
            path.unlink()
            return True
        return False

    def get_stats(self) -> dict[str, int]:
        """Get vault statistics."""
        stats = {}
        for cat in self.CATEGORIES:
            cat_dir = self._vault / cat
            stats[cat] = len(list(cat_dir.glob("*.md")))
        stats["total"] = sum(stats.values())
        return stats

    # ─── Internal Methods ────────────────────────────────────────────────

    def _generate_title(self, content: str) -> str:
        """Generate a title from content."""
        # Use first line or first 60 chars
        first_line = content.strip().split("\n")[0]
        first_line = re.sub(r"^#+\s*", "", first_line)  # Remove markdown headers
        return first_line[:60] if first_line else f"Memory {int(time.time())}"

    def _write_index(self) -> None:
        """Write the vault index file."""
        now = datetime.now()
        content = f"""# F.O.L. Memory Index

> Persistent memory vault for F.O.L. (Friendly Obedient Listener)
> Created: {now.strftime('%Y-%m-%d %H:%M')}

## Categories

| Category | Description |
|----------|-------------|
| [[People/]] | User identity, names, relationships |
| [[Preferences/]] | Likes, dislikes, habits |
| [[Knowledge/]] | Facts, things learned |
| [[Conversations/]] | Important conversation summaries |
| [[Projects/]] | Ongoing work, goals |
| [[Episodes/]] | What happened when |

## How It Works

FOL stores permanent memories here as markdown files.
When the AI context window fills up, memories survive in this vault.
Any new FOL session can read these files and恢复full context.

You can manually edit any file — FOL will respect your changes.
"""
        self._index_file.write_text(content, encoding="utf-8")

    def _update_index(self, category: str, title: str, filename: str) -> None:
        """Update the index with a new entry."""
        try:
            stem = Path(filename).stem
            link = f"- [[{category}/{stem}]] — {title}"
            content = self._index_file.read_text(encoding="utf-8")

            # Add under the appropriate category section
            marker = f"## {category}"
            if marker in content:
                # Find the end of the category section
                idx = content.find(marker)
                # Find next ## or end
                next_section = content.find("\n## ", idx + len(marker))
                if next_section == -1:
                    next_section = len(content)
                content = content[:next_section] + f"\n{link}\n" + content[next_section:]
            else:
                content += f"\n{link}\n"

            self._index_file.write_text(content, encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to update index: %s", exc)
