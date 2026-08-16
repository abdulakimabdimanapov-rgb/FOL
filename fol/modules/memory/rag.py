"""RAG — Retrieval-Augmented Generation pipeline — with smarter retrieval and ranking."""

from __future__ import annotations

import logging
from typing import Any

from modules.memory.vector_store import VectorStore
from modules.memory.conversation import ConversationHistory
from modules.memory.knowledge_graph import KnowledgeGraph
from modules.memory.preferences import PreferencesStore

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Retrieval-Augmented Generation — combines memory sources with relevance ranking."""

    def __init__(
        self,
        vector_store: VectorStore,
        conversation_history: ConversationHistory,
        knowledge_graph: KnowledgeGraph,
        preferences: PreferencesStore,
    ) -> None:
        self._vector = vector_store
        self._history = conversation_history
        self._kg = knowledge_graph
        self._prefs = preferences

    async def retrieve_context(self, query: str, max_tokens: int = 2000) -> str:
        """Retrieve relevant context from all memory sources with relevance ranking.

        Assembles context from:
        1. Recent conversation (most relevant first)
        2. Semantic memory search (vector similarity)
        3. Knowledge graph relations
        4. User preferences and identity
        """
        sections = []

        # 1. Recent conversation context — prioritize recent + relevant
        recent = await self._history.get_recent(n=8)
        if recent:
            conv_lines = []
            for turn in recent[-6:]:  # Keep last 6 for context
                conv_lines.append(f"User: {turn.user_input}")
                conv_lines.append(f"FOL: {turn.assistant_response}")
            sections.append("Recent conversation:\n" + "\n".join(conv_lines))

        # 2. Vector search for relevant memories — rank by score
        if self._vector.count > 0:
            try:
                vector_results = await self._vector.retrieve(query, limit=10)
                if vector_results:
                    # Filter by minimum relevance score
                    relevant = [item for item in vector_results if getattr(item, 'score', 0) and item.score > 0.25]
                    if relevant:
                        # Take top 5 most relevant
                        mem_lines = []
                        for item in relevant[:5]:
                            score = getattr(item, 'score', 0) or 0
                            score_bar = "█" * int(score * 10)
                            mem_lines.append(f"- [{score_bar} {score:.2f}] {item.content}")
                        sections.append("Relevant memories:\n" + "\n".join(mem_lines))
            except Exception as exc:
                logger.debug("Vector retrieval failed: %s", exc)

        # 3. Knowledge graph relations — context-aware
        try:
            entities = await self._kg.search(query, limit=8)
            if entities:
                rel_lines = []
                for entity in entities[:5]:
                    relations = await self._kg.get_relations(entity.name)
                    if relations:
                        for _, r, t in relations[:3]:
                            rel_lines.append(f"{entity.name} —[{r.relation_type}]→ {t.name}")
                if rel_lines:
                    sections.append("Knowledge graph:\n" + "\n".join(rel_lines[:10]))
        except Exception as exc:
            logger.debug("KG retrieval failed: %s", exc)

        # 4. User preferences — identity-aware
        try:
            prefs = await self._prefs.get_all()
            if prefs:
                pref_lines = [f"  {k}: {v}" for k, v in list(prefs.items())[:8]]
                sections.append("User preferences:\n" + "\n".join(pref_lines))
        except Exception as exc:
            logger.debug("Preferences retrieval failed: %s", exc)

        if not sections:
            return ""

        full_context = "\n\n".join(sections)

        # Smart truncation — keep complete sections
        if len(full_context) > max_tokens * 4:  # Rough char estimate
            # Truncate from the end (oldest/least relevant)
            truncated = []
            char_count = 0
            for section in reversed(sections):
                if char_count + len(section) > max_tokens * 4:
                    break
                truncated.append(section)
                char_count += len(section)
            full_context = "\n\n".join(reversed(truncated))

        return full_context

    async def store_conversation(self, user_input: str, assistant_response: str) -> None:
        """Store a conversation turn in all relevant stores."""
        # Store in conversation history
        await self._history.add_turn(user_input, assistant_response)

        # Store in vector DB for semantic search
        await self._vector.store(
            f"User: {user_input}\nFOL: {assistant_response}",
            metadata={"type": "conversation", "user_input": user_input},
        )

        # Try to extract and store entities
        await self.extract_and_store_entities(user_input)
        await self.extract_and_store_entities(assistant_response)

    async def store_fact(self, fact: str, category: str = "general") -> None:
        """Store a fact in multiple memory stores."""
        await self._vector.store(fact, metadata={"type": "fact", "category": category})

    async def extract_and_store_entities(self, text: str) -> None:
        """Simple entity extraction and storage in knowledge graph."""
        import re

        # Look for "X is Y" patterns (bilingual)
        patterns = [
            r"(?:my name is|i'm|i am|меня зовут|я)\s+([A-Za-zА-Яа-яёЁ]+)",
            r"(?:name:?)\s+([A-Za-zА-Яа-яёЁ]+)",
            r"(?:you can call me|зови меня)\s+([A-Za-zА-Яа-яёЁ]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1)
                await self._kg.add_entity(name, "person", {"source": "conversation"})
                await self._kg.add_relation("user", name, "named")

        # Look for relationship patterns
        rel_patterns = [
            r"(?:my (?:friend|colleague|boss|partner))\s+(\w+)",
            r"(?:works at|учится в|работает в)\s+(.+?)(?:\.|$)",
        ]
        for pattern in rel_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                entity = match.group(1).strip()
                await self._kg.add_entity(entity, "organization", {"source": "conversation"})
