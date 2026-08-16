"""SQLite-backed structured data store."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from config.constants import FOL_DIR
from modules.memory.base import AbstractMemoryStore, MemoryItem

logger = logging.getLogger(__name__)

try:
    import sqlite3
    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False


class SQLStore(AbstractMemoryStore):
    """SQLite-backed store for structured conversation data."""

    name = "sql_store"

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or (FOL_DIR / "conversations.db")
        self._conn: Any = None

    async def initialize(self) -> None:
        """Initialize SQLite database."""
        if not HAS_SQLITE:
            logger.warning("sqlite3 not available")
            return

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._create_tables()
            logger.info("SQLStore initialized", path=str(self._db_path))
        except Exception as exc:
            logger.error("Failed to init SQLStore", error=str(exc))

    def _create_tables(self) -> None:
        """Create required tables."""
        if self._conn is None:
            return
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_input TEXT NOT NULL,
                assistant_response TEXT NOT NULL,
                timestamp REAL NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp);
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 1.0,
                timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
        """)

    async def shutdown(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    async def store(self, content: str, metadata: dict[str, Any] | None = None) -> UUID:
        """Store a conversation turn."""
        if self._conn is None:
            return uuid4()

        import json
        item_id = uuid4()
        meta = metadata or {}
        try:
            self._conn.execute(
                "INSERT INTO conversations (id, user_input, assistant_response, timestamp, metadata) VALUES (?, ?, ?, ?, ?)",
                (
                    str(item_id),
                    meta.get("user_input", ""),
                    content,
                    time.time(),
                    json.dumps(meta),
                ),
            )
            self._conn.commit()
            return item_id
        except Exception as exc:
            logger.error("SQL store failed", error=str(exc))
            return uuid4()

    async def store_fact(self, content: str, category: str = "general", confidence: float = 1.0) -> UUID:
        """Store a fact in the knowledge base."""
        if self._conn is None:
            return uuid4()

        item_id = uuid4()
        try:
            self._conn.execute(
                "INSERT INTO facts (id, content, category, confidence, timestamp) VALUES (?, ?, ?, ?, ?)",
                (str(item_id), content, category, confidence, time.time()),
            )
            self._conn.commit()
            return item_id
        except Exception as exc:
            logger.error("SQL store_fact failed", error=str(exc))
            return uuid4()

    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Search conversations by content."""
        if self._conn is None:
            return []

        try:
            cursor = self._conn.execute(
                "SELECT * FROM conversations WHERE user_input LIKE ? OR assistant_response LIKE ? ORDER BY timestamp DESC LIMIT ?",
                (f"%{query}%", f"%{query}%", limit),
            )
            items = []
            for row in cursor.fetchall():
                items.append(MemoryItem(
                    content=row["assistant_response"],
                    metadata={"user_input": row["user_input"]},
                    timestamp=row["timestamp"],
                ))
            return items
        except Exception as exc:
            logger.error("SQL retrieve failed", error=str(exc))
            return []

    async def retrieve_facts(self, category: str | None = None, limit: int = 20) -> list[MemoryItem]:
        """Retrieve facts, optionally filtered by category."""
        if self._conn is None:
            return []

        try:
            if category:
                cursor = self._conn.execute(
                    "SELECT * FROM facts WHERE category = ? ORDER BY timestamp DESC LIMIT ?",
                    (category, limit),
                )
            else:
                cursor = self._conn.execute(
                    "SELECT * FROM facts ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            return [
                MemoryItem(
                    content=row["content"],
                    metadata={"category": row["category"], "confidence": row["confidence"]},
                    timestamp=row["timestamp"],
                )
                for row in cursor.fetchall()
            ]
        except Exception as exc:
            logger.error("SQL retrieve_facts failed", error=str(exc))
            return []

    async def delete(self, item_id: UUID) -> bool:
        """Delete a conversation by ID."""
        if self._conn is None:
            return False
        try:
            self._conn.execute("DELETE FROM conversations WHERE id = ?", (str(item_id),))
            self._conn.commit()
            return True
        except Exception:
            return False

    async def set_preference(self, key: str, value: str) -> None:
        """Set a user preference."""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO preferences (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, time.time()),
            )
            self._conn.commit()
        except Exception as exc:
            logger.error("SQL set_preference failed", error=str(exc))

    async def get_preference(self, key: str) -> str | None:
        """Get a user preference."""
        if self._conn is None:
            return None
        try:
            cursor = self._conn.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            return row["value"] if row else None
        except Exception:
            return None

    async def get_all_preferences(self) -> dict[str, str]:
        """Get all user preferences."""
        if self._conn is None:
            return {}
        try:
            cursor = self._conn.execute("SELECT key, value FROM preferences")
            return {row["key"]: row["value"] for row in cursor.fetchall()}
        except Exception:
            return {}
