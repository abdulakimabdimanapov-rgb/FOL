"""Identity layers — multi-layered psychological profile (inspired by FOL).

Layer 1: identity.md      — Who you are (role, voice, interests, patterns)
Layer 2: preferences.md    — How you work (schedule, tools, communication style)
Layer 3: relationships.json — Who you know (contact graph with closeness)
Layer 4: episodic.md        — What happened (timestamped life events)
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FOL_DIR = Path.home() / ".fol"
IDENTITY_DIR = FOL_DIR / "identity"


class IdentityLayers:
    """Multi-layered identity profile system."""

    def __init__(self, identity_dir: Path | None = None) -> None:
        self._dir = identity_dir or IDENTITY_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

        self._identity_file = self._dir / "identity.md"
        self._preferences_file = self._dir / "preferences.md"
        self._relationships_file = self._dir / "relationships.json"
        self._episodic_file = self._dir / "episodic.md"

        self._load_all()

    def _load_all(self) -> None:
        self._identity = self._load_md(self._identity_file)
        self._preferences = self._load_md(self._preferences_file)
        self._relationships = self._load_json(self._relationships_file)
        self._episodes = self._load_md(self._episodic_file)

    # ─── Layer 1: Identity ──────────────────────────────────────────

    def update_identity(self, field: str, value: str) -> None:
        """Update identity layer (who user is)."""
        self._identity[field] = value
        self._save_identity()

    def get_identity(self) -> dict[str, str]:
        return self._identity.copy()

    def _save_identity(self) -> None:
        lines = ["# Identity Profile", ""]
        for k, v in self._identity.items():
            lines.append(f"## {k.replace('_', ' ').title()}")
            lines.append(v)
            lines.append("")
        self._identity_file.write_text("\n".join(lines), encoding="utf-8")

    # ─── Layer 2: Preferences ───────────────────────────────────────

    def update_preference(self, key: str, value: str) -> None:
        self._preferences[key] = value
        self._save_preferences()

    def get_preferences(self) -> dict[str, str]:
        return self._preferences.copy()

    def _save_preferences(self) -> None:
        lines = ["# Work Preferences", ""]
        for k, v in self._preferences.items():
            lines.append(f"- **{k.replace('_', ' ').title()}:** {v}")
        self._preferences_file.write_text("\n".join(lines), encoding="utf-8")

    # ─── Layer 3: Relationships ─────────────────────────────────────

    def add_relationship(self, name: str, role: str = "", closeness: float = 0.5) -> None:
        self._relationships[name] = {"role": role, "closeness": closeness, "last_mentioned": time.time()}
        self._save_relationships()

    def get_relationships(self) -> dict[str, Any]:
        return self._relationships.copy()

    def _save_relationships(self) -> None:
        self._relationships_file.write_text(
            json.dumps(self._relationships, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ─── Layer 4: Episodic ──────────────────────────────────────────

    def add_episode(self, event: str, importance: float = 0.5) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- [{now}] {event}"
        with open(self._episodic_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")

    def get_episodes(self, limit: int = 20) -> list[str]:
        if not self._episodic_file.exists():
            return []
        lines = self._episodic_file.read_text(encoding="utf-8").strip().split("\n")
        return [l for l in lines if l.strip().startswith("-")][-limit:]

    # ─── Auto-extract from conversation ─────────────────────────────

    def extract_from_conversation(self, text: str) -> int:
        """Analyze text and auto-fill identity layers."""
        count = 0
        lower = text.lower()

        # Extract name
        name_match = re.search(r"(?:my name is|меня зовут|i'm|i am|я)\s+([A-Za-zА-Яа-яёЁ]{2,20})", text, re.IGNORECASE)
        if name_match:
            self.update_identity("name", name_match.group(1).capitalize())
            count += 1

        # Extract role/job
        role_match = re.search(r"(?:i work as|i'm a|i am a|я работаю|я являюсь)\s+(.+?)(?:\.|,|$)", text, re.IGNORECASE)
        if role_match:
            self.update_identity("role", role_match.group(1).strip())
            count += 1

        # Extract preferences
        for pattern, field in [
            (r"(?:i prefer|i like|предпочитаю|нравится)\s+(.+?)(?:\.|,|$)", "preferences"),
            (r"(?:i hate|i don't like|не нравится|ненавижу)\s+(.+?)(?:\.|,|$)", "dislikes"),
        ]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                self.update_preference(field, match.group(1).strip())
                count += 1

        # Extract relationships
        rel_match = re.search(r"(?:my friend|мой друг|my colleague|мой коллега)\s+(.+?)(?:\.|,|$)", text, re.IGNORECASE)
        if rel_match:
            self.add_relationship(rel_match.group(1).strip(), "friend", 0.7)
            count += 1

        return count

    def get_context_for_query(self, query: str, max_tokens: int = 2000) -> str:
        """Build context string from all identity layers for RAG."""
        sections = []

        if self._identity:
            lines = [f"  {k}: {v}" for k, v in self._identity.items()]
            sections.append("Identity:\n" + "\n".join(lines))

        if self._preferences:
            lines = [f"  {k}: {v}" for k, v in self._preferences.items()]
            sections.append("Preferences:\n" + "\n".join(lines))

        if self._relationships:
            lines = [f"  {k}: {v.get('role', '')}" for k, v in self._relationships.items()]
            sections.append("Relationships:\n" + "\n".join(lines))

        episodes = self.get_episodes(5)
        if episodes:
            sections.append("Recent events:\n" + "\n".join(episodes))

        context = "\n\n".join(sections)
        if len(context) > max_tokens * 4:
            context = context[:max_tokens * 4] + "..."
        return context

    # ─── Utilities ──────────────────────────────────────────────────

    def _load_md(self, path: Path) -> dict[str, str]:
        data = {}
        if not path.exists():
            return data
        try:
            content = path.read_text(encoding="utf-8")
            current_key = ""
            current_val = []
            for line in content.split("\n"):
                if line.startswith("## "):
                    if current_key:
                        data[current_key] = "\n".join(current_val).strip()
                    current_key = line[3:].strip().lower().replace(" ", "_")
                    current_val = []
                elif line.startswith("- **"):
                    match = re.match(r"- \*\*(.+?):\*\*\s*(.+)", line)
                    if match:
                        if current_key:
                            data[current_key] = "\n".join(current_val).strip()
                        current_key = match.group(1).strip().lower().replace(" ", "_")
                        current_val = [match.group(2).strip()]
                else:
                    current_val.append(line)
            if current_key:
                data[current_key] = "\n".join(current_val).strip()
        except Exception as exc:
            logger.warning("Failed to load %s: %s", path, exc)
        return data

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
