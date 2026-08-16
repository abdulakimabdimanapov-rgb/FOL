"""Freebuff Brain — persistent memory in Obsidian that survives model changes.

The Brain is FOL's long-term "second self": every interaction, decision and
model swap is written to markdown files in the Obsidian vault. When the user
switches the LLM model, the new model reads the Brain and already knows:

  - who the user is (User.md — profile digest)
  - how the user likes to communicate (Preferences.md)
  - what was done recently (Work-Log/YYYY-MM-DD.md — append-only journal)
  - which models were used before (Model-Log.md)
  - current projects and goals (Projects.md)

Layout inside the vault:

  Brain/
    _index.md            — entry point with links to everything
    User.md              — user profile (name, role, goals, projects)
    Preferences.md       — communication preferences
    Projects.md          — ongoing projects & goals
    Model-Log.md         — append-only model change history
    Work-Log/YYYY-MM-DD.md — append-only journal of everything we did

The Brain never raises: every write is best-effort and failures are logged
at debug level, so a broken vault can never break the chat.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_VAULT = str(Path.home() / "Documents" / "Obsidian Vault" / "FOL-Memory")


def _append_to_obsidian_daily(date: str, content: str) -> Any:
    """Best-effort write of the day's summary into the Obsidian Daily note.

    - Ensures the Daily/YYYY-MM-DD.md note exists first (REST API).
    - Appends under the standard ``## 📝 Notes`` section (present in the
      daily-note template) with a bold "Итоги дня" marker, instead of
      targeting a custom heading that may not exist.

    Isolated in a module-level function so tests can patch it without the
    ``obsidian`` package being importable in the test environment."""
    from obsidian.vault import append_to_section, ensure_daily_note
    ensure_daily_note(date)  # create Daily/YYYY-MM-DD.md if missing
    return append_to_section(
        f"Daily/{date}",
        "📝 Notes",
        f"\n### 🧠 Итоги дня\n\n{content}",
    )


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:80] or "note"


class Brain:
    """Freebuff Brain — append-only markdown memory in an Obsidian vault.

    Every method is best-effort and never raises. Writing to disk directly
    (no REST API dependency) means the Brain works even when the Obsidian
    app is closed — the files appear in the vault next time it opens.

    ``shared_vault`` (optional): path to the shared Brain vault
    (``~/Obsidian/Brain``) used by ALL AI assistants. When set, FOL mirrors
    its journal (turns, model changes, profile, preferences, projects) into
    the shared structure (Profile/ Goals/ Models/ Conversations/) and merges
    the shared context into ``get_brain_context()`` — so assistants and the
    FOL app share one memory.
    """

    def __init__(
        self,
        vault_path: str | Path | None = None,
        shared_vault: str | Path | None = None,
    ) -> None:
        self._vault = Path(vault_path or DEFAULT_VAULT).expanduser()
        self._brain_dir = self._vault / "Brain"
        self._work_dir = self._brain_dir / "Work-Log"
        self._shared_vault = Path(shared_vault).expanduser() if shared_vault else None
        try:
            self._brain_dir.mkdir(parents=True, exist_ok=True)
            self._work_dir.mkdir(exist_ok=True)
            self._ensure_index()
            self._ensure_file("User.md")
            self._ensure_file("Preferences.md")
            self._ensure_file("Projects.md")
            self._ensure_file("Model-Log.md")
            self._ensure_shared_dirs()
        except Exception as exc:
            logger.debug("Brain init failed: %s", exc)
        logger.info(
            "Freebuff Brain ready at %s (shared=%s)",
            self._brain_dir,
            self._shared_vault or "none",
        )

    # ─── Shared-vault helpers (best-effort, never raise) ─────────────────

    def _ensure_shared_dirs(self) -> None:
        """Create the shared Brain structure folders (Profile/Goals/Models/Conversations)."""
        if not self._shared_vault:
            return
        for folder in ("Profile", "Goals", "Models", "Conversations"):
            try:
                (self._shared_vault / folder).mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    def _shared_read(self, rel: str) -> str:
        """Read a file from the shared vault (best-effort)."""
        if not self._shared_vault:
            return ""
        try:
            p = self._shared_vault / rel
            return p.read_text(encoding="utf-8") if p.exists() else ""
        except Exception:
            return ""

    def _shared_write(self, rel: str, content: str) -> bool:
        """Write a file into the shared vault (best-effort)."""
        if not self._shared_vault:
            return False
        try:
            p = self._shared_vault / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return True
        except Exception as exc:
            logger.debug("Brain shared write %s failed: %s", rel, exc)
            return False

    def _shared_append_line(self, rel: str, line: str, max_lines: int = 500) -> bool:
        """Append a single line to a shared file, trimming old lines."""
        content = self._shared_read(rel)
        lines = [l for l in content.splitlines() if l.strip()]
        lines.extend(line.splitlines())
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return self._shared_write(rel, "\n".join(lines) + "\n")

    def _shared_upsert(self, rel: str, key: str, value: str) -> bool:
        """Upsert a ``key: value`` line in a shared markdown file.

        Matches both plain bullets (``- key: value`` — FOL style) and bold-key
        bullets (``- **key:** value`` — assistant style in Profile/), so the
        shared profile stays consistent whichever format wrote the entry.
        Matching is case-insensitive (the file may hold "Имя" while the key is
        slugified to "имя"), and the EXACT key casing + bullet style found in
        the file is preserved — an update never rewrites the key, only the value.
        """
        key = _slugify(key)
        content = self._shared_read(rel)
        # Match plain and bold-key bullet variants, case-insensitively.
        pat = re.compile(
            rf"^- (?:\*\*)?{re.escape(key)}(?:\*\*)?:.*$",
            re.MULTILINE | re.IGNORECASE,
        )

        # Keep the matched style AND key casing when replacing.
        def _repl(m: re.Match) -> str:
            body = m.group(0).lstrip("- ")
            if body.startswith("**"):
                # "**Имя:** ..." → key part "Имя" (preserve casing).
                key_part = body[2:].split(":**", 1)[0]
                return f"- **{key_part}:** {value}"
            # "имя: ..." → key part "имя" (preserve casing).
            key_part = body.split(":", 1)[0]
            return f"- {key_part}: {value}"

        if pat.search(content):
            content = pat.sub(_repl, content)
        else:
            content = content.rstrip() + f"\n- {key}: {value}\n"
        return self._shared_write(rel, content)

    # ─── Filesystem helpers (best-effort) ────────────────────────────────

    def _path(self, name: str) -> Path:
        return self._brain_dir / name

    def _ensure_file(self, name: str) -> None:
        path = self._path(name)
        if not path.exists():
            path.write_text(f"# {Path(name).stem}\n\n", encoding="utf-8")

    def _ensure_index(self) -> None:
        index = self._path("_index.md")
        if index.exists():
            return
        index.write_text(
            "# 🧠 Freebuff Brain — persistent memory\n\n"
            "> FOL's long-term memory. Survives model changes — a new model\n"
            "> reads these files and already knows the user.\n\n"
            "## Sections\n\n"
            "- [[User]] — who the user is\n"
            "- [[Preferences]] — how the user likes to communicate\n"
            "- [[Projects]] — ongoing projects and goals\n"
            "- [[Model-Log]] — model change history\n"
            "- [[Work-Log]] — journal of everything we did\n",
            encoding="utf-8",
        )

    def _read(self, name: str) -> str:
        try:
            return self._path(name).read_text(encoding="utf-8")
        except Exception:
            return ""

    def _write(self, name: str, content: str) -> bool:
        try:
            self._path(name).write_text(content, encoding="utf-8")
            return True
        except Exception as exc:
            logger.debug("Brain write %s failed: %s", name, exc)
            return False

    def _append(self, name: str, line: str, max_lines: int = 400) -> bool:
        """Append a line, trimming to ``max_lines`` so the journal never
        grows unbounded."""
        content = self._read(name)
        lines = [l for l in content.splitlines() if l.strip()]
        lines.append(line)
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        text = "\n".join(lines) + "\n"
        return self._write(name, text)

    # ─── Recording ───────────────────────────────────────────────────────

    def record_turn(
        self,
        user_input: str,
        response: str,
        *,
        source: str = "fol",
    ) -> bool:
        """Append one interaction to today's work log.

        This is the core of the Brain: EVERY turn is journaled, so a fresh
        model instance can reconstruct what was happening even after a swap.
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            ts = datetime.now().strftime("%H:%M")
            clean_user = " ".join((user_input or "").split())[:200]
            clean_resp = " ".join((response or "").split())[:300]
            log_path = self._work_dir / f"{today}.md"
            entry = f"- **{ts}** [{source}] **User:** {clean_user}\n  **FOL:** {clean_resp}"
            # Work log lives in its own file (not via _append which would
            # put it in Brain/, not Brain/Work-Log/).
            ok = False
            try:
                if log_path.exists():
                    with log_path.open("a", encoding="utf-8") as f:
                        f.write(entry + "\n")
                    ok = True
                else:
                    log_path.write_text(
                        f"# Work Log — {today}\n\n{entry}\n", encoding="utf-8"
                    )
                    ok = True
            except Exception as exc:
                logger.debug("Brain work-log append failed: %s", exc)
            # Mirror the turn into the shared Brain vault (Conversations/).
            self._mirror_turn_to_shared(user_input, response)
            return ok
        except Exception as exc:
            logger.debug("Brain record_turn failed: %s", exc)
            return False

    def _mirror_turn_to_shared(self, user_input: str, response: str) -> bool:
        """Append today's interaction into the shared Brain Conversations/.

        Format matches the assistant-style conversation log so any model can
        read what FOL did. Best-effort, never raises."""
        if not self._shared_vault:
            return False
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            ts = datetime.now().strftime("%H:%M")
            clean_user = " ".join((user_input or "").split())[:200]
            clean_resp = " ".join((response or "").split())[:300]
            rel = f"Conversations/{today}.md"
            existing = self._shared_read(rel).strip()
            header = (
                f"# {today} — Лог FOL\n\n"
                f"*Авто-журнал приложения FOL в общем Brain. Обновлено: {today}*\n\n"
            )
            if not existing:
                self._shared_write(rel, header)
            line = f"- **{ts}** [fol] **User:** {clean_user}\n  **FOL:** {clean_resp}"
            return self._shared_append_line(rel, line)
        except Exception as exc:
            logger.debug("Brain mirror turn failed: %s", exc)
            return False

    def record_model_change(self, model: str, *, reason: str = "") -> bool:
        """Append an entry to Model-Log.md when the active model changes.

        Consecutive identical models are not duplicated (a restart with the
        same model is not a change). Mirrored into the shared Brain
        Models/Change-Log.md when a shared vault is configured."""
        last = self._read("Model-Log.md").strip().splitlines()
        if last:
            last_line = last[-1]
            if f"`{model}`" in last_line:
                return True  # same model already recorded
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"- **{ts}** model → `{model}`" + (f" ({reason})" if reason else "")
        ok = self._append("Model-Log.md", line)
        self._mirror_model_change_to_shared(model, reason)
        return ok

    def _mirror_model_change_to_shared(self, model: str, reason: str = "") -> bool:
        """Append a model change into shared Models/Change-Log.md."""
        if not self._shared_vault:
            return False
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            line = f"- **{ts}** [FOL] model → `{model}`" + (f" ({reason})" if reason else "")
            return self._shared_append_line("Models/Change-Log.md", line)
        except Exception as exc:
            logger.debug("Brain mirror model change failed: %s", exc)
            return False

    def set_user_info(self, key: str, value: str) -> bool:
        """Upsert a key/value pair into User.md under '## Profile'."""
        key = _slugify(key)
        content = self._read("User.md")
        # Replace existing line "key: value" if present.
        pat = re.compile(rf"^- {re.escape(key)}:.*$", re.MULTILINE)
        line = f"- {key}: {value}"
        if pat.search(content):
            content = pat.sub(line, content)
        else:
            if "## Profile" in content:
                # Insert after the "## Profile" heading.
                content = content.replace("## Profile", f"## Profile\n{line}", 1)
            else:
                content += f"\n## Profile\n{line}\n"
        ok = self._write("User.md", content)
        self._shared_upsert("Profile/User.md", key, value)
        return ok

    def set_preference(self, key: str, value: str) -> bool:
        """Upsert a communication preference into Preferences.md."""
        ok = self._upsert_note("Preferences.md", key, value)
        self._shared_upsert("Profile/Preferences.md", key, value)
        return ok

    def _upsert_note(self, name: str, key: str, value: str) -> bool:
        key = _slugify(key)
        content = self._read(name)
        pat = re.compile(rf"^- {re.escape(key)}:.*$", re.MULTILINE)
        line = f"- {key}: {value}"
        if pat.search(content):
            content = pat.sub(line, content)
        else:
            content = content.rstrip() + f"\n{line}\n"
        return self._write(name, content)

    def record_project(self, title: str, status: str = "🟡 In progress") -> bool:
        """Add or update a project entry in Projects.md."""
        slug = _slugify(title)
        content = self._read("Projects.md")
        pat = re.compile(rf"^## {re.escape(title)}$", re.MULTILINE)
        if pat.search(content):
            return True  # already tracked
        content = content.rstrip() + f"\n## {title}\n- Status: {status}\n- [[Work-Log]]\n"
        ok = self._write("Projects.md", content)
        # Mirror into the shared Profile/Projects.md (project entry + status).
        if self._shared_vault:
            shared_projects = self._shared_read("Profile/Projects.md")
            pat = re.compile(rf"^## (?:\d+\.\s*)?{re.escape(title)}$", re.MULTILINE)
            if not pat.search(shared_projects):
                self._shared_write(
                    "Profile/Projects.md",
                    shared_projects.rstrip() + f"\n## {title}\n- Status: {status}\n",
                )
        return ok

    # ─── Daily summary ───────────────────────────────────────────────────

    def write_daily_summary(self, date: str | None = None) -> str:
        """Write an end-of-day summary of the work log into the vault.

        Builds a human-readable summary from the day's Work-Log entries and
        stores it in two places (both best-effort):

          - ``Brain/Daily-Summary/YYYY-MM-DD.md`` (always, direct write)
          - ``Daily/YYYY-MM-DD.md`` in the Obsidian vault (via the REST API
            when the Obsidian app is running)

        Idempotent for the Obsidian Daily note: the append happens only the
        first time a day is summarized (guarded by the existence of the
        ``Brain/Daily-Summary/YYYY-MM-DD.md`` marker file), so repeated calls
        (manual command + evening task + restart) never duplicate the note.

        Returns the summary markdown ("" when the day has no entries).
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        entries = self._work_log_entries(date)
        if not entries:
            return ""

        summary = self._build_daily_summary(date, entries)
        summary_file = self._brain_dir / "Daily-Summary" / f"{date}.md"

        # 1. Brain/Daily-Summary/YYYY-MM-DD.md — always written directly.
        #    Its existence doubles as the "already summarized today" marker.
        already_written = summary_file.exists()
        try:
            summary_file.parent.mkdir(exist_ok=True)
            summary_file.write_text(summary, encoding="utf-8")
        except Exception as exc:
            logger.debug("Brain daily-summary write failed: %s", exc)

        # 2. Obsidian Daily/YYYY-MM-DD.md — only on the FIRST write of the
        #    day, so restarts / re-runs never duplicate the note content.
        if not already_written:
            try:
                _append_to_obsidian_daily(date, summary)
            except Exception as exc:
                logger.debug("Obsidian daily-note append failed: %s", exc)

        logger.info(
            "Brain daily summary written for %s (%d entries, obsidian_append=%s)",
            date, len(entries), not already_written,
        )
        return summary

    def _work_log_entries(self, date: str) -> list[str]:
        """Parse a day's Work-Log file into full entries (bullet + continuations)."""
        log_path = self._work_dir / f"{date}.md"
        try:
            text = log_path.read_text(encoding="utf-8")
        except Exception:
            return []
        entries: list[str] = []
        current: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("-"):
                if current:
                    entries.append(" ".join(current))
                current = [line.lstrip("- ")]
            elif current:
                current.append(line)
        if current:
            entries.append(" ".join(current))
        return entries

    def _build_daily_summary(self, date: str, entries: list[str]) -> str:
        """Turn a day's journal entries into a concise markdown summary."""
        lines = [
            f"# Итоги дня — {date}",
            "",
            f"*Авто-сводка Freebuff Brain: {len(entries)} взаимодействий.*",
            "",
            "## 🧠 Что мы делали",
            "",
        ]
        for entry in entries[-40:]:  # keep the most recent 40
            # entry: "**HH:MM** [fol] **User:** … **FOL:** …"
            lines.append(f"- {entry}")
        lines += ["", "## 🔗 Links", "", f"- [[Brain/Work-Log/{date}]]"]
        return "\n".join(lines)

    # ─── Retrieval ───────────────────────────────────────────────────────

    def get_brain_context(self, max_chars: int = 1800) -> str:
        """Assemble a compact BRAIN CONTEXT block for the LLM prompt.

        This is what makes model swaps painless: the new model receives the
        user profile, preferences, current projects, model history and the
        tail of the work log — so it already knows the user.

        Priority order matters: the stable profile sections (User,
        Preferences, Projects) are kept FIRST, and if the total exceeds
        ``max_chars`` the volatile tail (recent activity) is truncated — so
        "who the user is" is never dropped for a fresh model.
        """
        sections: list[str] = []

        # Shared-vault context FIRST (assistants wrote this — profile,
        # goals, model changes, recent conversations). This is what makes
        # the FOL app and any assistant share one memory.
        sections.extend(self._get_shared_context_sections())

        user = self._read("User.md").strip()
        if user and user.count("\n") > 1:
            sections.append(user[:600])

        prefs = self._read("Preferences.md").strip()
        if prefs and prefs.count("\n") > 1:
            sections.append(prefs[:400])

        projects = self._read("Projects.md").strip()
        if projects and projects.count("\n") > 1:
            sections.append(projects[:400])

        model_log = self._read("Model-Log.md").strip()
        model_lines = [l for l in model_log.splitlines() if l.strip().startswith("-")]
        if model_lines:
            sections.append("Model history:\n" + "\n".join(model_lines[-5:]))

        work = self._recent_work_log(limit=10)
        if work:
            sections.append("Recent activity:\n" + "\n".join(work))

        # Assemble with stable-first priority: shared profile and local
        # profile sections are never dropped; only the volatile tails
        # (recent activity, shared conversations) are truncated, and when
        # they are, the NEWEST entries are kept (oldest dropped first).
        joined = "\n\n".join(sections)
        if len(joined) > max_chars:
            if work:
                activity = sections.pop()  # the "Recent activity:" section
                lines = activity.split("\n")
                # Drop the OLDEST activity lines (after the header) until fit.
                while len(joined) > max_chars and len(lines) > 1:
                    lines.pop(1)  # remove the second line = oldest entry
                    joined = "\n\n".join(sections + ["\n".join(lines)])
            # If still over budget, drop whole volatile sections from the END
            # (shared conversations → model history → …) before touching the
            # profile sections at the START — who the user is always survives.
            while len(sections) > 1 and len(joined) > max_chars:
                sections.pop()  # drop the least-stable trailing section
                joined = "\n\n".join(sections)
            if len(joined) > max_chars:
                # Even the profile alone is too big — hard-truncate the tail.
                joined = joined[:max_chars]
        return joined

    def _get_shared_context_sections(self, limit_chars: int = 1500) -> list[str]:
        """Assemble context sections from the shared Brain vault.

        Reads what the assistants wrote (Profile/, Goals/, Models/Change-Log.md)
        plus the most recent Conversations/ files, so the FOL app sees the
        same memory as any AI assistant. Best-effort — empty when no shared
        vault is configured or nothing is there yet.
        """
        if not self._shared_vault:
            return []
        sections: list[str] = []
        total = 0

        def _add(label: str, text: str, cap: int = 450) -> None:
            nonlocal total
            text = text.strip()
            if not text:
                return
            body = text[:cap]
            sections.append(f"## {label}\n{body}")
            total += len(body)

        # Profile (User + Preferences) — who the user is.
        user = self._shared_read("Profile/User.md")
        prefs = self._shared_read("Profile/Preferences.md")
        if user.strip():
            _add("Shared profile", user, cap=500)
        if prefs.strip():
            _add("Shared preferences", prefs, cap=350)

        # Goals — what the user wants.
        goals = self._shared_read("Goals/Wants.md")
        if goals.strip():
            _add("Shared goals", goals, cap=400)

        # Model changes — which models were used (from the shared log).
        model_log = self._shared_read("Models/Change-Log.md")
        model_lines = [
            l for l in model_log.splitlines()
            if l.strip().startswith("-") and "model →" in l
        ]
        if model_lines and total < limit_chars:
            _add("Shared model history", "\n".join(model_lines[-5:]), cap=300)

        # Recent conversations (latest 3 notes, last entries of each).
        if total < limit_chars and self._shared_vault:
            try:
                conv_dir = self._shared_vault / "Conversations"
                if conv_dir.exists():
                    files = sorted(
                        conv_dir.glob("*.md"), reverse=True
                    )
                    recent: list[str] = []
                    for f in files[:3]:
                        if f.name == "_index.md":
                            continue
                        try:
                            text = f.read_text(encoding="utf-8")
                        except Exception:
                            continue
                        bullets = [
                            l.strip() for l in text.splitlines()
                            if l.strip().startswith("-")
                        ]
                        if bullets:
                            recent.append(
                                f"### {f.stem}\n" + "\n".join(bullets[-4:])
                            )
                    if recent:
                        _add("Shared recent conversations", "\n\n".join(recent), cap=600)
            except Exception as exc:
                logger.debug("Brain shared conversations read failed: %s", exc)

        return sections

    def _recent_work_log(self, limit: int = 10) -> list[str]:
        """Return the tail of the newest work-log file(s).

        Each journal entry is a bullet line optionally followed by indented
        continuation lines ("  **FOL:** ...") — those continuations are
        folded into the entry so the context shows the full interaction.
        """
        try:
            files = sorted(self._work_dir.glob("*.md"), reverse=True)
        except Exception:
            return []
        if not files:
            return []
        entries: list[str] = []
        for f in files[:3]:
            try:
                text = f.read_text(encoding="utf-8")
                current: list[str] = []
                for raw in text.splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    if line.startswith("-"):
                        if current:
                            entries.append(" ".join(current))
                        current = [line.lstrip("- ")]
                    elif current:
                        # Continuation line (indented **FOL:** ...)
                        current.append(line)
                if current:
                    entries.append(" ".join(current))
                if len(entries) >= limit:
                    break
            except Exception:
                continue
        return entries[-limit:]

    # ─── Work-log queries (what did we do / what are we working on) ───────

    def work_log_for_date(self, date: str | None = None) -> list[str]:
        """Return the parsed journal entries for a specific date.

        Args:
            date: "YYYY-MM-DD". Defaults to today.

        Returns:
            List of full entries (user + FOL folded into one line each).
        """
        date = date or datetime.now().strftime("%Y-%m-%d")
        return self._work_log_entries(date)

    def recent_work(self, days: int = 7, limit: int = 20) -> list[dict[str, str]]:
        """Return recent journal entries across the last ``days`` days.

        Returns:
            List of {"date": "YYYY-MM-DD", "entry": "..."} — newest first.
        """
        from datetime import timedelta

        results: list[dict[str, str]] = []
        for offset in range(days):
            date = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
            # Newest entries of the day first (work_log_for_date stays
            # chronological; recent_work is newest-first for prompts/answers).
            day_entries = self._work_log_entries(date)
            for entry in reversed(day_entries):
                results.append({"date": date, "entry": entry})
                if len(results) >= limit:
                    return results
        return results

    def search_work_log(
        self,
        query: str,
        *,
        days: int = 14,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        """Full-text search across recent Work-Log entries.

        Case-insensitive substring match on the folded entry text. Returns
        {"date", "entry"} dicts, newest first, capped at ``limit``.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        matches: list[dict[str, str]] = []
        for item in self.recent_work(days=days, limit=10_000):
            if q in item["entry"].lower():
                matches.append(item)
                if len(matches) >= limit:
                    break
        return matches

    def get_projects(self) -> list[str]:
        """List project titles tracked in Projects.md."""
        projects: list[str] = []
        for line in self._read("Projects.md").splitlines():
            if line.startswith("## "):
                projects.append(line[3:].strip())
        return projects

    def get_stats(self) -> dict[str, int]:
        """Count notes in each Brain section."""
        stats: dict[str, int] = {}
        for name in ("User.md", "Preferences.md", "Projects.md", "Model-Log.md"):
            content = self._read(name)
            stats[Path(name).stem] = len(
                [l for l in content.splitlines() if l.strip().startswith("-")]
            )
        stats["work_log_entries"] = len(self._recent_work_log(limit=100000))
        stats["work_log_files"] = len(
            list(self._work_dir.glob("*.md")) if self._work_dir.exists() else []
        )
        return stats

    def summary(self) -> str:
        """Human-readable Brain status (for the «мозг» command)."""
        s = self.get_stats()
        model_log = self._read("Model-Log.md")
        models = [
            l.split("→ `", 1)[1].rstrip("`").strip()
            for l in model_log.splitlines()
            if "→ `" in l
        ]
        lines = [
            f"🧠 Freebuff Brain: {self._brain_dir}",
            f"  Profile entries: {s['User']}   Preferences: {s['Preferences']}",
            f"  Projects: {s['Projects']}   Model changes: {s['Model-Log']}",
            f"  Work log: {s['work_log_entries']} entries in {s['work_log_files']} file(s)",
        ]
        if models:
            lines.append(f"  Model history: {' → '.join(models[-5:])}")
        return "\n".join(lines)


__all__ = ["Brain", "DEFAULT_VAULT"]
