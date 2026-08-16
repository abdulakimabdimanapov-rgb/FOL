"""Session context and state management — with richer context assembly."""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Words that never carry topic information (RU + EN).
_STOPWORDS = frozenset("""
the a an and or but if then else this that these those with without for of on in at by
from to is are was were be been being do does did have has had can could will would
should may might must not no yes all any some each every both neither either
it its they their them he his him she her we our us you your i me my
what which who whom whose when where why how
так что как это эти эта этот и в на с со по из за для к от о об при под над перед
не ни да нет ну вот еще ещё уже только тоже также то или а но если же бы у меня тебя
него неё нам вас кто где когда почему зачем сколько какой какие какая который
оно ему её его них ими им
# Command verbs — never topic content, but they sit at sentence starts and
# would otherwise be mistaken for entities ("Найди", "Открыл").
найди найти открой открыл открыл открыт открыть покажи показал сделай сделал создай
создал напиши написал включи включил запусти запустил посмотри посмотрел скажи сказал
помоги помог расскажи рассказал выведи прочитай повтори продолжи перейди перейти
search find open opened show make create write run launch start play tell read look
help continue go set get remove add open_app
""".split())

# Phrase prefixes that ALWAYS signal a continuation (unambiguous reference).
# Checked against the punctuation-stripped, lowercased input.
_FOLLOWUP_STRONG_PREFIXES = (
    # Russian — question-word references ("а какая из них?") and commands
    "а что ", "а какая ", "а какие ", "а какой ", "а почему ",
    "а где ", "а когда ", "а кто ", "а зачем ", "а сколько ", "а можно ",
    "и что ", "и где ", "дальше ", "продолжай ", "продолжи ",
    "кстати ", "а кстати ", "и кстати ", "расскажи подробнее ", "подробнее ",
    "а дальше ", "а потом ", "и потом ", "а ещё ", "а еще ", "вот ещё ",
    "вот еще ", "ещё раз ", "еще раз ", "повтори ",
    # English — unambiguous continuations
    "and what ", "and how ", "and why ", "and where ", "and when ", "and who ",
    "what about ", "how about ", "but what ", "but how ", "but why ",
    "but where ", "tell me more ", "continue ", "go on ", "more about ",
    "what about the ", "and is ", "and are ", "and does ", "and did ",
    "what else ", "and then ", "then what ",
)

# Generic conjunction prefixes ("а ", "и ", "and ", "but "...). These also
# start brand-new topics ("А вчера я ходил в кино"), so they only count as a
# follow-up for SHORT messages (≤ _FOLLOWUP_MAX_WORDS words).
_FOLLOWUP_PREFIXES = (
    "а ", "и ", "но ", "ещё ", "еще ", "так а ", "ну а ", "а также ",
    "а вообще ", "кстати а ", "а при чём ", "а при чем ",
    # "а как…" / "и как…" are ambiguous (can pivot: "А как тебе iPhone?"),
    # so they only count for short messages.
    "а как ", "и как ",
    "and ", "but ", "also ", "then ", "and also ",
)

# Longer messages that merely START with a conjunction are new topics, not
# follow-ups (e.g. "А вчера я ходил в кино с друзьями").
_FOLLOWUP_MAX_WORDS = 6

# Complete short messages that continue the previous topic.
_FOLLOWUP_EXACT = frozenset({
    "дальше", "продолжи", "продолжай", "кстати", "ещё", "еще", "а", "и",
    "continue", "go on", "more", "and then", "then what", "tell me more",
    "what else", "и что дальше", "а что дальше", "расскажи ещё", "расскажи еще",
    "расскажи подробнее", "подробнее", "расскажи дальше", "а потом", "и потом",
    "а кстати", "и кстати", "что дальше", "расскажи", "еще раз", "ещё раз",
})


@dataclass
class ConversationTurn:
    """A single turn in a conversation."""

    user_input: str = ""
    assistant_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0
    emotional_tone: str = ""  # Detected emotional tone of user input
    tool_used: str = ""       # Which tool was used (if any)

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class ContextManager:
    """Manages conversation context and session state — with rich context assembly."""

    def __init__(self, max_history: int = 50) -> None:
        self._max_history = max_history
        self._history: list[ConversationTurn] = []
        self._working_memory: dict[str, Any] = {}
        self._session_metadata: dict[str, Any] = {
            "session_start": time.time(),
            "total_turns": 0,
        }

    def add_turn(
        self,
        user_input: str,
        assistant_response: str,
        metadata: dict[str, Any] | None = None,
        emotional_tone: str = "",
        tool_used: str = "",
    ) -> None:
        """Add a conversation turn to history."""
        turn = ConversationTurn(
            user_input=user_input,
            assistant_response=assistant_response.strip(),
            metadata=metadata or {},
            emotional_tone=emotional_tone,
            tool_used=tool_used,
        )
        self._history.append(turn)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        self._session_metadata["total_turns"] = self._session_metadata.get("total_turns", 0) + 1
        logger.debug("Turn added to context", history_length=len(self._history))

    def get_recent_context(self, n: int = 8) -> str:
        """Get recent conversation as formatted context string with timestamps."""
        recent = self._history[-n:]
        if not recent:
            return "No recent context available."
        lines = []
        for i, turn in enumerate(recent):
            age = len(recent) - i
            time_prefix = ""
            if turn.timestamp:
                elapsed = time.time() - turn.timestamp
                if elapsed < 60:
                    time_prefix = " (just now)"
                elif elapsed < 3600:
                    time_prefix = f" ({int(elapsed/60)}m ago)"
                else:
                    time_prefix = f" ({int(elapsed/3600)}h ago)"
            lines.append(f"[Turn {i+1}{time_prefix}] User: {turn.user_input}")
            lines.append(f"  Assistant: {turn.assistant_response}")
            if turn.emotional_tone:
                lines.append(f"  [Tone: {turn.emotional_tone}]")
        return "Recent conversation:\n" + "\n".join(lines)

    def is_follow_up(self, user_input: str) -> bool:
        """Detect whether the message continues a previous topic (RU/EN).

        A message is treated as a follow-up when it is short and starts with a
        continuation marker ("а ", "и ", "but ", "what about ", ...) or is one
        of the exact continuation commands ("дальше", "continue", ...).
        Without history there is nothing to continue, so this returns False.
        """
        if not self._history:
            return False
        text = re.sub(r"[?!.…]+$", "", " ".join(user_input.split())).strip()
        text = (
            text.replace(",", " ")
            .replace(";", " ")
            .replace(":", " ")
            .replace("—", " ")
            .replace("–", " ")
        )
        text = re.sub(r"\s+", " ", text).strip().lower()
        if not text:
            return False
        if text in _FOLLOWUP_EXACT:
            return True
        # Unambiguous reference phrases always count.
        if any(text.startswith(p) for p in _FOLLOWUP_STRONG_PREFIXES):
            return True
        # Generic conjunctions only count for short messages — a long "А вчера
        # я ходил в кино…" starts a new topic and must not be forced back into
        # the previous one.
        if len(text.split()) <= _FOLLOWUP_MAX_WORDS:
            return any(text.startswith(p) for p in _FOLLOWUP_PREFIXES)
        return False

    def get_current_topic(self, n: int = 4, max_topics: int = 6) -> str:
        """Extract the salient topics/entities from the recent turns.

        Proper nouns (e.g. "OpenAI") are strong entity signals — a capitalized
        word that never appears lowercase is treated as a named entity.
        Frequent common nouns are ranked next. Returns a comma-separated string
        ("" when there is nothing meaningful).
        """
        recent = self._history[-n:]
        if not recent:
            return ""

        lowered_counts: Counter = Counter()
        entity_counts: Counter = Counter()
        for turn in recent:
            text = f"{turn.user_input} {turn.assistant_response}"
            for word in re.findall(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9-]{2,}", text):
                low = word.lower()
                lowered_counts[low] += 1
                if word[0].isupper():
                    entity_counts[word] += 1

        # Named entities: capitalized, never lowercase, not a stopword.
        entities = [
            word
            for word, count in entity_counts.most_common(max_topics)
            if lowered_counts.get(word.lower(), 0) <= count
            and word.lower() not in _STOPWORDS
            and len(word.lower()) >= 3
        ]
        entity_lows = {e.lower() for e in entities}
        # Frequent common nouns fill the remaining slots.
        common = [
            word
            for word, _count in lowered_counts.most_common()
            if word not in _STOPWORDS
            and len(word) >= 4
            and word not in entity_lows
        ]
        topics = (entities + common)[:max_topics]
        return ", ".join(topics) if topics else ""

    def get_follow_up_context(self, n: int = 4) -> str:
        """Build a prompt block that grounds a follow-up in the ongoing topic.

        Used when :meth:`is_follow_up` returned True: the LLM gets an explicit
        "current topic" pointer plus the previous user message, so short
        references ("it", "they", "них", "его") resolve to the right referent
        even for small/local models. Wording is conditional so a genuine topic
        pivot is not forced back onto the previous subject.
        """
        if not self._history:
            return ""
        lines = []
        topic = self.get_current_topic(n=n)
        if topic:
            lines.append(f"The conversation is currently about: {topic}")
        lines.append(f"Previous user message: {self._history[-1].user_input}")
        lines.append(
            "The current message may be a follow-up to this conversation. "
            'If it references the previous topic (pronouns like "it", "they", '
            '"них", "его", "эта"), resolve them against the topic above. If it '
            "introduces a new subject, answer the new question normally."
        )
        return "\n".join(lines)

    def clear_history(self) -> None:
        """Clear the conversation history (used by the 'clear' command)."""
        self._history.clear()
        self._session_metadata["total_turns"] = 0

    def get_topic_context(self) -> str:
        """Extract the main topics being discussed in the current session."""
        if len(self._history) < 2:
            return ""

        # Simple keyword extraction from recent turns
        recent_words: dict[str, int] = {}
        for turn in self._history[-10:]:
            for word in turn.user_input.lower().split():
                if len(word) > 3 and word.isalpha():
                    recent_words[word] = recent_words.get(word, 0) + 1

        if not recent_words:
            return ""

        # Get top recurring topics
        top_topics = sorted(recent_words.items(), key=lambda x: x[1], reverse=True)[:8]
        return "Session topics: " + ", ".join(f"{w}({c})" for w, c in top_topics)

    def get_emotional_context(self) -> str:
        """Get the emotional trajectory of the conversation."""
        if not self._history:
            return ""

        tones = [t.emotional_tone for t in self._history[-5:] if t.emotional_tone]
        if not tones:
            return ""

        from collections import Counter
        tone_counts = Counter(tones)
        dominant = tone_counts.most_common(1)[0][0]
        return f"Emotional context: user seems {dominant} (detected from recent {len(tones)} messages)"

    def get_working_memory(self, key: str) -> Any:
        """Get a value from working memory."""
        return self._working_memory.get(key)

    def set_working_memory(self, key: str, value: Any) -> None:
        """Set a value in working memory."""
        self._working_memory[key] = value

    def clear_working_memory(self) -> None:
        """Clear all working memory."""
        self._working_memory.clear()

    @property
    def last_user_input(self) -> str:
        """Get the last user input."""
        return self._history[-1].user_input if self._history else ""

    @property
    def last_assistant_response(self) -> str:
        """Get the last assistant response."""
        return self._history[-1].assistant_response if self._history else ""

    @property
    def history_length(self) -> int:
        """Number of conversation turns."""
        return len(self._history)

    @property
    def session_duration_minutes(self) -> float:
        """How long the current session has been active."""
        start = self._session_metadata.get("session_start", time.time())
        return (time.time() - start) / 60
