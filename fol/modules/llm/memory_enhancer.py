"""Memory enhancer — extracts and enhances memories from conversations with better accuracy."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class MemoryEnhancer:
    """Extracts and enhances memories from conversations — supports English and Russian."""

    # ─── Name extraction patterns ───────────────────────────────────
    NAME_PATTERNS = [
        r"(?:my name is|i'm|i am|叫我|我是)\s+([A-Za-zА-Яа-яёЁ]+)",
        r"(?:меня зовут|я)\s+([А-Яа-яёЁ]+)",
        r"(?:name:?)\s*([A-Za-zА-Яа-яёЁ]+)",
        r"(?:you can call me|зови меня|называй меня)\s+([A-Za-zА-Яа-яёЁ]+)",
    ]

    # ─── Preference patterns (bilingual) ────────────────────────────
    PREFERENCE_PATTERNS = [
        r"(?:i prefer|i like|i love|я люблю|я предпочитаю|мне нравится|обожаю)\s+(.+?)(?:\.|$)",
        r"(?:don't like|hate|не люблю|не нравится|ненавижу)\s+(.+?)(?:\.|$)",
        r"(?:favorite|любимый|любимая|любимое|лучший|лучшая|лучше)\s+\w+\s+(?:is|это|=)\s+(.+?)(?:\.|$)",
        r"(?:i use|i work with|я использую|я работаю с)\s+(.+?)(?:\s+every|usually|обычно|often|часто)(?:\.|$)",
        r"(?:always|всегда|usually|обычно)\s+(?:use|use|использую|открываю)\s+(.+?)(?:\.|$)",
    ]

    # ─── Fact patterns ──────────────────────────────────────────────
    FACT_PATTERNS = [
        r"(\w+)\s+(?:is|are|was|were)\s+(.+?)(?:\.|$)",
        r"(?:fact|факт|важно|note|запомни|remember):\s*(.+?)(?:\.|$)",
        r"(?:i work at|я работаю в|i study at|учусь в)\s+(.+?)(?:\.|$)",
        r"(?:i live in|живу в|я из)\s+(.+?)(?:\.|$)",
        r"(?:i'm currently|сейчас я)\s+(.+?)(?:\.|$)",
    ]

    # ─── Intent patterns (what user wants to do) ────────────────────
    INTENT_PATTERNS = [
        r"(?:want to|хочу|need to|нужно|must|надо|планирую)\s+(.+?)(?:\.|$)",
        r"(?:going to|собираюсь|will)\s+(.+?)(?:\s+(?:tomorrow|завтра|soon|скоро|next|следующий))(?:\.|$)",
    ]

    # ─── Relationship patterns ──────────────────────────────────────
    RELATIONSHIP_PATTERNS = [
        r"(?:my (?:friend|colleague|coworker|boss|manager|partner|wife|husband)|мой (?:друг|коллега|начальник|партнёр))\s+(?:said|says|told me|сказал|говорит)\s+(.+?)(?:\.|$)",
    ]

    def extract_facts(self, text: str) -> list[dict[str, str]]:
        """Extract facts from text."""
        facts = []
        for pattern in self.FACT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                content = match.group(0).strip()
                if len(content) > 10:  # Skip very short matches
                    facts.append({
                        "content": content,
                        "category": "fact",
                        "confidence": 0.75,
                    })
        return facts

    def extract_preferences(self, text: str) -> list[dict[str, str]]:
        """Extract user preferences from text."""
        prefs = []
        for pattern in self.PREFERENCE_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                content = match.group(0).strip()
                if len(content) > 5:
                    # Determine sentiment (positive/negative)
                    is_negative = any(
                        neg in content.lower()
                        for neg in ["don't like", "не люблю", "не нравится", "hate", "ненавижу"]
                    )
                    prefs.append({
                        "content": content,
                        "category": "preference",
                        "sentiment": "negative" if is_negative else "positive",
                        "confidence": 0.85,
                    })
        return prefs

    def extract_names(self, text: str) -> list[str]:
        """Extract person names from text."""
        names = []
        for pattern in self.NAME_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                name = match.group(1).strip()
                if len(name) > 1 and name[0].isupper():
                    names.append(name)
        return list(set(names))

    def extract_intents(self, text: str) -> list[dict[str, str]]:
        """Extract user intents (what they want to do)."""
        intents = []
        for pattern in self.INTENT_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                content = match.group(1).strip()
                if len(content) > 5:
                    intents.append({
                        "content": content,
                        "category": "intent",
                        "confidence": 0.7,
                    })
        return intents

    def extract_relationships(self, text: str) -> list[dict[str, str]]:
        """Extract relationship information."""
        rels = []
        for pattern in self.RELATIONSHIP_PATTERNS:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                content = match.group(0).strip()
                rels.append({
                    "content": content,
                    "category": "relationship",
                    "confidence": 0.8,
                })
        return rels

    def extract_all(self, text: str) -> dict[str, list[Any]]:
        """Extract all entities from text."""
        return {
            "facts": self.extract_facts(text),
            "preferences": self.extract_preferences(text),
            "names": self.extract_names(text),
            "intents": self.extract_intents(text),
            "relationships": self.extract_relationships(text),
        }

    async def enhance_memory(self, user_input: str, assistant_response: str, rag_pipeline: Any) -> None:
        """Enhance memory from a conversation turn."""
        if not hasattr(rag_pipeline, "store_fact"):
            return

        # Extract from user input
        user_entities = self.extract_all(user_input)

        for fact in user_entities["facts"]:
            try:
                await rag_pipeline.store_fact(fact["content"], fact["category"])
            except Exception:
                pass

        for pref in user_entities["preferences"]:
            try:
                await rag_pipeline.store_fact(pref["content"], "preference")
            except Exception:
                pass

        for name in user_entities["names"]:
            try:
                await rag_pipeline.store_fact(f"User's name might be {name}", "name")
            except Exception:
                pass

        for intent in user_entities["intents"]:
            try:
                await rag_pipeline.store_fact(f"User wants to: {intent['content']}", "intent")
            except Exception:
                pass

        for rel in user_entities["relationships"]:
            try:
                await rag_pipeline.store_fact(rel["content"], "relationship")
            except Exception:
                pass

        # Extract from assistant response (for facts stated by assistant)
        resp_entities = self.extract_all(assistant_response)
        for fact in resp_entities["facts"]:
            try:
                await rag_pipeline.store_fact(fact["content"], "confirmed_fact")
            except Exception:
                pass
