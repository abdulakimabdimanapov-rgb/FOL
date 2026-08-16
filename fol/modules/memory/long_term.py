"""Long-term memory system for FOL.

Persistent memory with:
- Conversation history
- Knowledge base (facts, entities, relationships)
- Episodic memory (what happened when)
- Vector search (semantic similarity)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

FOL_DIR = Path.home() / ".fol"
MEMORY_DB_DIR = FOL_DIR / "memory_db"


@dataclass
class MemoryEntry:
    """A single memory entry."""

    id: str = field(default_factory=lambda: str(uuid4()))
    content: str = ""
    category: str = "general"
    importance: float = 0.5
    timestamp: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeTriple:
    """A knowledge triple (subject, predicate, object)."""

    subject: str = ""
    predicate: str = ""
    object: str = ""
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)


class LongTermMemory:
    """Long-term memory system with persistence and search."""

    def __init__(self, db_dir: Path | None = None) -> None:
        self._db_dir = db_dir or MEMORY_DB_DIR
        self._db_dir.mkdir(parents=True, exist_ok=True)

        self._memories: list[MemoryEntry] = []
        self._conversations: list[dict[str, Any]] = []
        self._knowledge: list[KnowledgeTriple] = []
        self._episodes: list[dict[str, Any]] = []

        self._memories_file = self._db_dir / "memories.jsonl"
        self._conversations_file = self._db_dir / "conversations.jsonl"
        self._knowledge_file = self._db_dir / "knowledge.jsonl"
        self._episodes_file = self._db_dir / "episodes.jsonl"
        self._index_file = self._db_dir / "index.json"

        self._load_all()

    def store_memory(
        self,
        content: str,
        category: str = "general",
        importance: float = 0.5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            content=content,
            category=category,
            importance=importance,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._memories.append(entry)
        self._append_to_file(self._memories_file, entry)
        self._update_index()
        return entry

    def store_conversation(
        self,
        user_input: str,
        fol_response: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "id": str(uuid4()),
            "user_input": user_input,
            "fol_response": fol_response,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self._conversations.append(entry)
        self._append_to_file(self._conversations_file, entry)
        return entry

    def store_knowledge(
        self, subject: str, predicate: str, obj: str, confidence: float = 1.0
    ) -> KnowledgeTriple:
        triple = KnowledgeTriple(
            subject=subject, predicate=predicate, object=obj, confidence=confidence
        )
        self._knowledge.append(triple)
        self._append_to_file(self._knowledge_file, triple)
        return triple

    def store_episode(
        self,
        event: str,
        context: str = "",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry = {
            "id": str(uuid4()),
            "event": event,
            "context": context,
            "importance": importance,
            "timestamp": time.time(),
            "metadata": metadata or {},
        }
        self._episodes.append(entry)
        self._append_to_file(self._episodes_file, entry)
        return entry

    def search_memories(self, query: str, category: str | None = None, limit: int = 10) -> list[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for memory in self._memories:
            if category and memory.category != category:
                continue
            score = self._calculate_similarity(query_lower, memory.content.lower())
            if score > 0.1:
                results.append((score, memory))
        results.sort(key=lambda x: x[0] * x[1].importance, reverse=True)
        for _, memory in results[:limit]:
            memory.last_accessed = time.time()
            memory.access_count += 1
        return [memory for _, memory in results[:limit]]

    def search_conversations(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for conv in self._conversations:
            score = 0
            if query_lower in conv.get("user_input", "").lower():
                score += 0.6
            if query_lower in conv.get("fol_response", "").lower():
                score += 0.4
            if score > 0:
                results.append((score, conv))
        results.sort(key=lambda x: x[0], reverse=True)
        return [conv for _, conv in results[:limit]]

    def search_knowledge(self, query: str, limit: int = 10) -> list[KnowledgeTriple]:
        query_lower = query.lower()
        results = []
        for triple in self._knowledge:
            score = 0
            if query_lower in triple.subject.lower():
                score += 0.4
            if query_lower in triple.predicate.lower():
                score += 0.2
            if query_lower in triple.object.lower():
                score += 0.4
            if score > 0:
                results.append((score, triple))
        results.sort(key=lambda x: x[0] * x[1].confidence, reverse=True)
        return [triple for _, triple in results[:limit]]

    def search_episodes(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query_lower = query.lower()
        results = []
        for episode in self._episodes:
            score = 0
            if query_lower in episode.get("event", "").lower():
                score += 0.7
            if query_lower in episode.get("context", "").lower():
                score += 0.3
            if score > 0:
                results.append((score, episode))
        results.sort(key=lambda x: x[0] * x[1].get("importance", 0.5), reverse=True)
        return [ep for _, ep in results[:limit]]

    def get_recent_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._conversations[-limit:]

    def get_recent_memories(self, limit: int = 20) -> list[MemoryEntry]:
        return self._memories[-limit:]

    def get_context_for_query(self, query: str, max_tokens: int = 2000) -> str:
        """Get relevant context for a query (RAG)."""
        sections = []

        conv_results = self.search_conversations(query, limit=5)
        if conv_results:
            lines = []
            for conv in conv_results:
                lines.append(f"User: {conv['user_input']}")
                lines.append(f"FOL: {conv['fol_response']}")
            sections.append("Past conversations:\n" + "\n".join(lines))

        mem_results = self.search_memories(query, limit=5)
        if mem_results:
            lines = [f"- [{m.category}] {m.content}" for m in mem_results]
            sections.append("Memories:\n" + "\n".join(lines))

        kb_results = self.search_knowledge(query, limit=5)
        if kb_results:
            lines = [f"- {t.subject} {t.predicate} {t.object}" for t in kb_results]
            sections.append("Knowledge:\n" + "\n".join(lines))

        ep_results = self.search_episodes(query, limit=3)
        if ep_results:
            lines = [f"- {e['event']}" for e in ep_results]
            sections.append("Recent events:\n" + "\n".join(lines))

        if not sections:
            return ""

        context = "\n\n".join(sections)
        if len(context) > max_tokens * 4:
            context = context[: max_tokens * 4] + "..."
        return context

    def extract_and_store(self, text: str) -> int:
        """Extract entities and facts from text and store them."""
        count = 0

        name_patterns = [
            r"(?:my name is|i'm|i am|меня зовут|я)\s+([A-Za-zА-Яа-яёЁ]+)",
        ]
        for pattern in name_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).capitalize()
                self.store_knowledge("user", "named", name)
                count += 1

        fact_patterns = [
            r"(\w+)\s+(?:is|are|was|were)\s+(.+?)(?:\.|$)",
        ]
        for pattern in fact_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                subject = match.group(1)
                obj = match.group(2).strip()
                if 2 < len(obj) < 200:
                    self.store_knowledge(subject, "is", obj, confidence=0.7)
                    count += 1

        pref_patterns = [
            r"(?:i prefer|i like|я люблю|мне нравится)\s+(.+?)(?:\.|$)",
        ]
        for pattern in pref_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                pref = match.group(1).strip()
                self.store_memory(pref, category="preference", importance=0.7)
                count += 1

        return count

    def _calculate_similarity(self, query: str, text: str) -> float:
        query_words = set(query.split())
        text_words = set(text.split())
        if not query_words:
            return 0.0
        intersection = query_words & text_words
        return len(intersection) / len(query_words)

    def _append_to_file(self, filepath: Path, data: Any) -> None:
        try:
            if hasattr(data, "__dict__"):
                entry = {k: v for k, v in data.__dict__.items() if not k.startswith("_")}
            else:
                entry = data
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.error("Failed to append to %s: %s", filepath, exc)

    def _load_all(self) -> None:
        self._memories = self._load_jsonl(self._memories_file, MemoryEntry)
        self._conversations = self._load_jsonl(self._conversations_file)
        self._knowledge = self._load_jsonl(self._knowledge_file, KnowledgeTriple)
        self._episodes = self._load_jsonl(self._episodes_file)

    def _load_jsonl(self, filepath: Path, model_class: type | None = None) -> list[Any]:
        data = []
        if not filepath.exists():
            return data
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if model_class:
                            valid_fields = {f.name for f in model_class.__dataclass_fields__.values()}
                            filtered = {k: v for k, v in entry.items() if k in valid_fields}
                            data.append(model_class(**filtered))
                        else:
                            data.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            logger.error("Failed to load %s: %s", filepath, exc)
        return data

    def _update_index(self) -> None:
        try:
            index = {
                "total_memories": len(self._memories),
                "total_conversations": len(self._conversations),
                "total_knowledge": len(self._knowledge),
                "total_episodes": len(self._episodes),
                "last_updated": time.time(),
            }
            self._index_file.write_text(json.dumps(index, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to update index: %s", exc)

    def clear_all(self) -> None:
        self._memories.clear()
        self._conversations.clear()
        self._knowledge.clear()
        self._episodes.clear()
        for fp in [self._memories_file, self._conversations_file, self._knowledge_file, self._episodes_file]:
            if fp.exists():
                fp.unlink()
        self._update_index()

    @property
    def stats(self) -> dict[str, int]:
        return {
            "memories": len(self._memories),
            "conversations": len(self._conversations),
            "knowledge": len(self._knowledge),
            "episodes": len(self._episodes),
        }

    @property
    def total_size(self) -> int:
        return sum(self.stats.values())
