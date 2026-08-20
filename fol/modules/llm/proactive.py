"""Proactive assistant — suggests actions and reminders based on context.

One module, three layers:

- :class:`ProactiveAssistant` — pure rules engine (time/session/context rules).
- :class:`ProactiveLLMEngine` — LLM-based suggestion generation (profile /
  pattern / ambient triggers). This is the canonical home of the behavior
  previously implemented in ``orchestrator/suggestion_engine.py``; the
  orchestrator module is now a thin compatibility wrapper delegating here.
- :class:`ProactiveService` — runtime wrapper the FOL app uses: owns session
  stats (command counts, session length), the ON/OFF toggle, the cooldown and
  the per-hour cap (anti-nagging policy required by the ROADMAP), and
  delegates evaluation to the same assistant.
- :class:`ProactiveEngine` — the UNIFIED runtime engine: rule-based and
  LLM-based sources behind ONE toggle / cooldown / hourly-cap policy, with
  duplicate prevention and subscriber-based event emission. The FOL API
  (WebSocket) and the orchestrator SSE transport both hook this single
  engine — there is no second proactive system.
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ProactiveSuggestion:
    """A proactive suggestion for the user."""

    title: str = ""
    description: str = ""
    action: str = ""
    priority: float = 0.5
    context: str = ""
    timestamp: float = 0.0
    category: str = "general"  # "productivity", "health", "reminder", "automation"

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class ProactiveAssistant:
    """Generates intelligent proactive suggestions based on context and patterns."""

    def __init__(self) -> None:
        self._suggestions: list[ProactiveSuggestion] = []
        self._rules: list[dict[str, Any]] = []
        self._dismissed: set[str] = set()
        self._setup_default_rules()

    def _setup_default_rules(self) -> None:
        """Set up comprehensive proactive rules."""
        self._rules = [
            # ─── Time-based rules ───────────────────────────────────
            {
                "trigger": "time_morning",
                "condition": lambda ctx: 6 <= ctx.get("hour", 12) <= 9,
                "suggestion": ProactiveSuggestion(
                    title="Доброе утро! ☀️",
                    description="Хотите посмотреть расписание на сегодня?",
                    action="show_schedule",
                    priority=0.3,
                    category="productivity",
                ),
            },
            {
                "trigger": "time_lunch",
                "condition": lambda ctx: 12 <= ctx.get("hour", 12) <= 13,
                "suggestion": ProactiveSuggestion(
                    title="Обеденное время 🍽️",
                    description="Пора сделать перерыв! Хотите напомнить через 30 минут?",
                    action="set_reminder",
                    priority=0.35,
                    category="health",
                ),
            },
            {
                "trigger": "time_evening",
                "condition": lambda ctx: 22 <= ctx.get("hour", 12) or ctx.get("hour", 12) < 1,
                "suggestion": ProactiveSuggestion(
                    title="Поздний вечер 🌙",
                    description="Вы работаете допоздна. Может, стоит отдохнуть?",
                    action="none",
                    priority=0.4,
                    category="health",
                ),
            },
            {
                "trigger": "time_weekend",
                "condition": lambda ctx: ctx.get("is_weekend", False),
                "suggestion": ProactiveSuggestion(
                    title="Выходной день 🎉",
                    description="Сегодня выходной. Могу помочь с хобби или отдыхом!",
                    action="none",
                    priority=0.2,
                    category="general",
                ),
            },

            # ─── Session-based rules ────────────────────────────────
            {
                "trigger": "repeated_command",
                "condition": lambda ctx: ctx.get("repeated_count", 0) >= 3,
                "suggestion": ProactiveSuggestion(
                    title="Автоматизация 🔁",
                    description="Вы повторяете это действие. Автоматизировать?",
                    action="suggest_automation",
                    priority=0.6,
                    category="automation",
                ),
            },
            {
                "trigger": "long_session",
                "condition": lambda ctx: ctx.get("session_minutes", 0) > 60,
                "suggestion": ProactiveSuggestion(
                    title="Время для перерыва ⏸️",
                    description="Вы работаете уже больше часа. 5-минутный перерыв улучшит концентрацию.",
                    action="none",
                    priority=0.45,
                    category="health",
                ),
            },
            {
                "trigger": "very_long_session",
                "condition": lambda ctx: ctx.get("session_minutes", 0) > 120,
                "suggestion": ProactiveSuggestion(
                    title="Долгая сессия ⚠️",
                    description="Более 2 часов без перерыва! Встаньте, разомнитесь, попейте воды.",
                    action="suggest_break",
                    priority=0.55,
                    category="health",
                ),
            },
            {
                "trigger": "first_command",
                "condition": lambda ctx: ctx.get("total_commands", 0) == 1,
                "suggestion": ProactiveSuggestion(
                    title="Привет! 👋",
                    description="Чем могу помочь сегодня?",
                    action="none",
                    priority=0.25,
                    category="general",
                ),
            },

            # ─── Context-aware rules ────────────────────────────────
            {
                "trigger": "coding_context",
                "condition": lambda ctx: any(
                    w in ctx.get("last_command", "").lower()
                    for w in ["python", "swift", "code", "git", "build", "compile", "пайтон", "код"]
                ),
                "suggestion": ProactiveSuggestion(
                    title="Разработка 💻",
                    description="Нужна помощь с кодом? Могу открыть редактор, запустить тесты или помочь с отладкой.",
                    action="open_editor",
                    priority=0.35,
                    category="productivity",
                ),
            },
            {
                "trigger": "email_mention",
                "condition": lambda ctx: any(
                    w in ctx.get("last_command", "").lower()
                    for w in ["email", "письмо", "mail", "письма", "inbox"]
                ),
                "suggestion": ProactiveSuggestion(
                    title="Почта 📧",
                    description="Могу открыть почту или помочь написать ответ.",
                    action="open_mail",
                    priority=0.4,
                    category="productivity",
                ),
            },
            {
                "trigger": "meeting_mention",
                "condition": lambda ctx: any(
                    w in ctx.get("last_command", "").lower()
                    for w in ["встреча", "meeting", "совещание", "call", "звонок"]
                ),
                "suggestion": ProactiveSuggestion(
                    title="Встреча 📅",
                    description="Поставить напоминание за 5 минут до встречи?",
                    action="set_meeting_reminder",
                    priority=0.5,
                    category="reminder",
                ),
            },
            {
                "trigger": "file_operations",
                "condition": lambda ctx: ctx.get("recent_tool_count", {}).get("search_files", 0) >= 2,
                "suggestion": ProactiveSuggestion(
                    title="Поиск файлов 📁",
                    description="Вы часто ищете файлы. Может, стоит организовать рабочее пространство?",
                    action="suggest_organization",
                    priority=0.3,
                    category="productivity",
                ),
            },
            {
                "trigger": "browser_heavy",
                "condition": lambda ctx: ctx.get("recent_tool_count", {}).get("browser_search", 0) >= 3,
                "suggestion": ProactiveSuggestion(
                    title="Много поисков 🔍",
                    description="Могу сохранить полезные ссылки или создать закладки.",
                    action="suggest_bookmarks",
                    priority=0.3,
                    category="productivity",
                ),
            },

            # ─── Emotional rules ────────────────────────────────────
            {
                "trigger": "frustrated_user",
                "condition": lambda ctx: any(
                    w in ctx.get("last_command", "").lower()
                    for w in ["не работает", "broken", "error", "ошибка", "баг", "bug", "фигня", "сломал"]
                ),
                "suggestion": ProactiveSuggestion(
                    title="Помогу разобраться 🔧",
                    description="Похоже, что-то пошло не так. Опишите проблему подробнее, и я помогу найти решение.",
                    action="none",
                    priority=0.5,
                    category="general",
                ),
            },
        ]

    async def evaluate(self, context: dict[str, Any]) -> ProactiveSuggestion | None:
        """Evaluate context and return the best suggestion if appropriate."""
        triggered = []
        for rule in self._rules:
            try:
                if rule["condition"](context):
                    suggestion = rule["suggestion"]
                    if suggestion.title not in self._dismissed:
                        triggered.append(suggestion)
            except Exception:
                continue

        if triggered:
            # Return highest priority suggestion
            triggered.sort(key=lambda s: s.priority, reverse=True)
            suggestion = triggered[0]
            self._suggestions.append(suggestion)
            return suggestion
        return None

    async def evaluate_all(self, context: dict[str, Any]) -> list[ProactiveSuggestion]:
        """Evaluate context and return all matching suggestions."""
        triggered = []
        for rule in self._rules:
            try:
                if rule["condition"](context):
                    suggestion = rule["suggestion"]
                    if suggestion.title not in self._dismissed:
                        triggered.append(suggestion)
            except Exception:
                continue
        triggered.sort(key=lambda s: s.priority, reverse=True)
        self._suggestions.extend(triggered)
        return triggered

    async def add_rule(self, trigger: str, condition: Any, suggestion: ProactiveSuggestion) -> None:
        """Add a custom proactive rule."""
        self._rules.append({
            "trigger": trigger,
            "condition": condition,
            "suggestion": suggestion,
        })

    async def get_recent_suggestions(self, limit: int = 10) -> list[ProactiveSuggestion]:
        """Get recent suggestions."""
        return self._suggestions[-limit:]

    async def dismiss_suggestion(self, title: str) -> bool:
        """Dismiss a suggestion by title."""
        self._dismissed.add(title)
        for i, s in enumerate(self._suggestions):
            if s.title == title:
                self._suggestions.pop(i)
                return True
        return False

    @property
    def rule_count(self) -> int:
        return len(self._rules)


class ProactiveService:
    """Runtime layer over :class:`ProactiveAssistant`.

    Owns everything the runtime needs that the rules engine should not know
    about: session statistics (command counts, session length), the ON/OFF
    toggle (ROADMAP Etap 5 requires it — FOL must never become an annoying
    assistant), a cooldown between suggestions and a cap on suggestions per
    hour. ``check()`` builds the evaluation context and delegates to the same
    ``ProactiveAssistant`` — the rules stay in one place.

    Usage (ambient tick, every N minutes):

        svc = ProactiveService(enabled=settings.proactive_enabled)
        svc.record_command(user_input)      # on every user turn
        suggestion = await svc.check()      # None when suppressed
    """

    def __init__(
        self,
        assistant: ProactiveAssistant | None = None,
        *,
        enabled: bool = False,
        cooldown_minutes: int = 5,
        max_per_hour: int = 3,
        session_start: float | None = None,
    ) -> None:
        self._assistant = assistant or ProactiveAssistant()
        self._enabled = enabled
        self._cooldown_seconds = max(cooldown_minutes, 0) * 60
        self._max_per_hour = max(max_per_hour, 0)
        self._session_start = session_start if session_start is not None else time.time()
        self._command_counts: Counter[str] = Counter()
        self._tool_counts: Counter[str] = Counter()
        self._total_commands = 0
        self._last_command = ""
        self._emission_times: deque[float] = deque()
        self._last_emitted_at: float | None = None
        self._last_suggestion: ProactiveSuggestion | None = None

    # ─── Session stats ───────────────────────────────────────────────────

    def record_command(self, command: str) -> None:
        """Record one user command — feeds the repeated/long-session rules."""
        command = (command or "").strip()
        if not command:
            return
        self._total_commands += 1
        self._command_counts[command] += 1
        self._last_command = command

    def record_tool_use(self, tool_name: str) -> None:
        """Record a tool execution — feeds the recent_tool_count rules."""
        if tool_name:
            self._tool_counts[tool_name] += 1

    @property
    def total_commands(self) -> int:
        return self._total_commands

    def session_minutes(self) -> int:
        """Whole minutes elapsed since the service started."""
        return int((time.time() - self._session_start) / 60)

    # ─── Toggle (ROADMAP: mandatory ON/OFF switch) ──────────────────────

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable proactive suggestions.

        Re-enabling (a real OFF→ON transition) clears the hourly emission
        window so the cap does not leak across sessions, and resets the
        cooldown so the user can immediately try a suggestion. Calling
        ``set_enabled(True)`` when already enabled does NOT reset anything —
        otherwise a repeated "proactive on" command (or REST toggle) could
        spam-reset the anti-nagging policy.
        """
        was_enabled = self._enabled
        self._enabled = enabled
        if enabled and not was_enabled:
            self._emission_times.clear()
            self._last_emitted_at = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ─── Evaluation ─────────────────────────────────────────────────────

    async def check(
        self,
        context_extra: dict[str, Any] | None = None,
        *,
        force: bool = False,
    ) -> ProactiveSuggestion | None:
        """Evaluate the rules against current session context.

        Returns ``None`` when the feature is off, a suggestion was emitted
        too recently (cooldown), the hourly cap is exhausted, or no rule
        fired. On a hit, the suggestion is recorded for observability and the
        anti-nagging timers advance.

        ``force=True`` (explicit user request — "предложи что-нибудь")
        bypasses the cooldown and the hourly cap: an explicit ask is never
        "nagging". The feature toggle is still respected.
        """
        if not self._enabled:
            return None
        now = time.time()
        # Keep the 1-hour emission window bounded — pruned on every call so
        # forced checks cannot grow the deque without limit.
        self._emission_times = deque(
            t for t in self._emission_times if now - t < 3600
        )
        if not force:
            if (
                self._last_emitted_at is not None
                and now - self._last_emitted_at < self._cooldown_seconds
            ):
                return None
            # Hourly cap: only count emissions within the last 60 minutes.
            if len(self._emission_times) >= self._max_per_hour:
                return None

        context = self._build_context()
        if context_extra:
            context.update(context_extra)
        suggestion = await self._assistant.evaluate(context)
        if suggestion is None:
            return None
        self._emission_times.append(now)
        self._last_emitted_at = now
        self._last_suggestion = suggestion
        return suggestion

    def _build_context(self) -> dict[str, Any]:
        """Build the evaluation context from session state + clock."""
        now = datetime.now()
        repeated = 0
        if self._last_command:
            repeated = self._command_counts[self._last_command]
        return {
            "hour": now.hour,
            "is_weekend": now.weekday() >= 5,
            "total_commands": self._total_commands,
            "session_minutes": self.session_minutes(),
            "repeated_count": repeated,
            "last_command": self._last_command,
            "recent_tool_count": dict(self._tool_counts),
        }

    async def dismiss(self, title: str) -> bool:
        """Dismiss a suggestion by title (stops it firing again)."""
        return await self._assistant.dismiss_suggestion(title)

    @property
    def last_suggestion(self) -> ProactiveSuggestion | None:
        """The most recent suggestion emitted (None before the first)."""
        return self._last_suggestion

    def stats(self) -> dict[str, Any]:
        """Observability snapshot for the status command / API."""
        return {
            "enabled": self._enabled,
            "total_commands": self._total_commands,
            "session_minutes": self.session_minutes(),
            "cooldown_minutes": int(self._cooldown_seconds / 60),
            "max_per_hour": self._max_per_hour,
            "emitted_this_hour": len(self._emission_times),
            "rules": self._assistant.rule_count,
            "last_suggestion": self._last_suggestion.title if self._last_suggestion else None,
        }


# ---------------------------------------------------------------------------
# LLM-based suggestion sources (canonical — moved from suggestion_engine)
# ---------------------------------------------------------------------------

class ProactiveLLMEngine:
    """LLM-based proactive suggestion generation.

    This is the canonical implementation of the behavior that used to live in
    ``orchestrator/suggestion_engine.py`` (profile / pattern / ambient
    triggers). The orchestrator module is now a thin compatibility wrapper
    delegating here, so there is exactly ONE proactive generator.

    ``llm_fn(system_prompt, user_content) -> str`` is injectable: the
    orchestrator wrapper passes its own (test-patchable) sync caller; the
    default goes through the canonical ``BrainInterface`` (``get_brain()`` →
    ``CurrentLLMAdapter`` → ``LiteLLMRouter``, or → Freebuff once an official
    interface ships).
    """

    CONFIDENCE_THRESHOLD = 0.7
    MAX_SUGGESTIONS = 3
    DEFAULT_REWARDS_PATH = pathlib.Path.home() / ".secondself" / "rewards.jsonl"
    DEFAULT_SCREENSHOT_URL = "http://localhost:8421/screenshot"

    def __init__(
        self,
        llm_fn: Callable[[str, Any], str] | None = None,
        *,
        rewards_path: str | pathlib.Path | None = None,
        screenshot_url: str | None = None,
    ) -> None:
        self._llm_fn = llm_fn if llm_fn is not None else self._default_llm
        self._rewards_path = pathlib.Path(rewards_path) if rewards_path else self.DEFAULT_REWARDS_PATH
        self._screenshot_url = screenshot_url or self.DEFAULT_SCREENSHOT_URL
        self._recently_emitted: deque[str] = deque(maxlen=50)

    @staticmethod
    def _default_llm(system_prompt: str, user_content: Any) -> str:
        """Default sync LLM caller — the canonical brain (never raises)."""
        try:
            from modules.llm.brain import get_brain

            messages = [{"role": "user", "content": user_content}]
            return get_brain().chat(
                messages=messages, system=system_prompt, max_tokens=2048
            )
        except Exception as exc:
            logger.debug("ProactiveLLMEngine default LLM failed: %s", exc)
            return ""

    # -- parsing ----------------------------------------------------------

    def parse_suggestions(self, text: str | None) -> list[dict[str, Any]]:
        """Parse a model text response into suggestion dicts.

        Same contract as the former ``suggestion_engine._parse_suggestions``:
        JSON array or ``{"suggestions": [...]}`` (markdown fences tolerated),
        confidence filtered at ``CONFIDENCE_THRESHOLD``, context values
        stringified for the SwiftUI ``[String: String]`` contract.
        """
        if not text:
            return []
        try:
            content = text.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            parsed = json.loads(content)
            if isinstance(parsed, list):
                suggestions = parsed
            elif isinstance(parsed, dict) and "suggestions" in parsed:
                suggestions = parsed["suggestions"]
            else:
                return []

            result = []
            for s in suggestions:
                try:
                    confidence = float(s.get("confidence", 0.5))
                except (TypeError, ValueError):
                    confidence = 0.0
                if confidence < self.CONFIDENCE_THRESHOLD:
                    continue
                raw_context = s.get("context", {})
                context = (
                    {str(k): str(v) for k, v in raw_context.items()}
                    if isinstance(raw_context, dict)
                    else {}
                )
                result.append({
                    "id": f"sug_{uuid.uuid4().hex[:8]}",
                    "title": s.get("title", "Suggestion"),
                    "description": s.get("description", ""),
                    "confidence": confidence,
                    "action_id": s.get("action_id", "general"),
                    "context": context,
                })
            return result
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return []

    # -- rewards ----------------------------------------------------------

    def load_rewards(self) -> list[dict[str, Any]]:
        """Load reward history from disk (best-effort)."""
        if not self._rewards_path.exists():
            return []
        rewards = []
        try:
            with open(self._rewards_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rewards.append(json.loads(line))
        except (IOError, json.JSONDecodeError):
            pass
        return rewards

    # -- screenshot (ambient context) --------------------------------------

    def _fetch_screenshot(self) -> str | None:
        """Fetch the latest desktop screenshot from the agent server as
        base64 JPEG (best-effort — None when unavailable)."""
        import urllib.error
        import urllib.request

        try:
            req = urllib.request.Request(self._screenshot_url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return data.get("image")
        except Exception as exc:
            logger.debug("ProactiveLLMEngine screenshot fetch failed: %s", exc)
            return None

    # -- triggers ---------------------------------------------------------

    def _call_llm(self, system_prompt: str, user_content: Any) -> str:
        """Call the injected LLM function; never raises."""
        try:
            return self._llm_fn(system_prompt, user_content)
        except Exception as exc:
            logger.debug("ProactiveLLMEngine LLM call failed: %s", exc)
            return ""

    def profile_trigger(self, profile: dict | None) -> list[dict[str, Any]]:
        """Layer 1: suggestions from a Tavily profile. Source tag ``profile``."""
        if not profile:
            return []

        name = profile.get("name", "the user")
        title = profile.get("title", "")
        company = profile.get("company", "")
        interests = profile.get("interests", [])
        recent_activity = profile.get("recent_activity", "")
        bio = profile.get("bio", "")

        prompt = (
            "You are a proactive digital twin. A new user just arrived. "
            "Based on their profile, generate 2-3 specific, actionable workflow suggestions.\n\n"
            "Each suggestion should be something you can execute on a macOS desktop "
            "(browser research, document creation, data compilation).\n\n"
            f"User profile:\n"
            f"  Name: {name}\n"
            f"  Title: {title}\n"
            f"  Company: {company}\n"
            f"  Interests: {', '.join(interests) if interests else 'general technology'}\n"
            f"  Recent activity: {recent_activity}\n"
            f"  Bio: {bio}\n\n"
            "Return a JSON object with a 'suggestions' array. Each suggestion has:\n"
            "  title (short, action-oriented), description (1-2 sentences, used as task prompt),\n"
            "  confidence (0.0-1.0), action_id (semantic label like 'research_competitors'),\n"
            "  context (dict with relevant details like company, industry).\n"
            "Only suggest things with confidence >= 0.7."
        )

        text = self._call_llm(prompt, "Generate suggestions for this user.")
        suggestions = self.parse_suggestions(text)
        for s in suggestions:
            s["source"] = "profile"
        return suggestions

    def pattern_trigger(
        self,
        conversation_history: list[dict[str, Any]],
        profile: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Layer 2: detect repeated verb+object patterns (3+ shared requests).
        Source tag ``pattern``."""
        user_messages = [
            m["content"]
            for m in conversation_history
            if m.get("role") == "user" and m.get("source", "user") == "user"
        ]
        if len(user_messages) < 3:
            return []

        profile_summary = ""
        if profile:
            profile_summary = f"User: {profile.get('name', '')}, {profile.get('title', '')} at {profile.get('company', '')}"

        prompt = (
            "You are a proactive digital twin analyzing conversation patterns.\n\n"
            "Here are the user's recent requests (oldest first):\n"
            + "\n".join(f"  {i+1}. {msg}" for i, msg in enumerate(user_messages[-10:]))
            + "\n\n"
            + (f"User profile: {profile_summary}\n\n" if profile_summary else "")
            + "Look for patterns: repeated request types, similar themes, escalating specificity.\n"
            "ONLY suggest a pattern if 3+ requests clearly share the same verb + object type.\n"
            "If no clear pattern exists, return {\"suggestions\": []}.\n"
            "If a pattern exists, return a JSON object with a 'suggestions' array containing ONE suggestion:\n"
            "  title, description (what to automate), confidence (0.7-1.0), action_id, context."
        )

        text = self._call_llm(prompt, "Analyze for patterns.")
        suggestions = self.parse_suggestions(text)
        for s in suggestions:
            s["source"] = "pattern"
        return suggestions

    def ambient_tick(
        self,
        conversation_history: list[dict[str, Any]],
        profile: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Layer 3: ambient awareness tick (screenshot + history + rewards).
        Source tag ``ambient``."""
        screenshot_b64 = self._fetch_screenshot()

        profile_summary = ""
        if profile:
            profile_summary = (
                f"User: {profile.get('name', '')}, "
                f"{profile.get('title', '')} at {profile.get('company', '')}. "
                f"Interests: {', '.join(profile.get('interests', []))}."
            )

        recent_messages = []
        for m in conversation_history[-10:]:
            role = m.get("role", "unknown")
            content = m.get("content", "")[:200]
            recent_messages.append(f"  [{role}]: {content}")
        conversation_text = "\n".join(recent_messages) if recent_messages else "(no conversation yet)"

        rewards = self.load_rewards()
        reward_summary = ""
        if rewards:
            accepted = sum(1 for r in rewards if r.get("action") == "accept")
            dismissed = sum(1 for r in rewards if r.get("action") == "dismiss")
            reward_summary = f"Past suggestions: {accepted} accepted, {dismissed} dismissed."

        prompt = (
            "You are a proactive digital twin running on a separate macOS desktop.\n"
            "You are always watching and thinking about how to help.\n\n"
            f"User profile: {profile_summary}\n\n"
            f"Conversation history:\n{conversation_text}\n\n"
            f"{reward_summary}\n\n"
        )

        if screenshot_b64:
            prompt += (
                "Above is a screenshot of your desktop. Based on what you see, "
                "what you know about the user, and the conversation so far, "
                "is there something proactive you should suggest?\n\n"
            )
        else:
            prompt += (
                "You don't have a screenshot right now. Based on the user's profile "
                "and conversation history, is there something proactive you should suggest?\n\n"
            )

        prompt += (
            "Only suggest if confidence > 0.7. If nothing valuable to suggest, "
            "return {\"suggestions\": []}.\n"
            "If you have a suggestion, return a JSON object with a 'suggestions' array "
            "containing ONE suggestion: title, description, confidence, action_id, context."
        )

        if screenshot_b64:
            user_content = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": screenshot_b64}},
                {"type": "text", "text": "Analyze my desktop and suggest something proactive."},
            ]
        else:
            user_content = "Suggest something proactive based on the context above."

        text = self._call_llm(prompt, user_content)
        suggestions = self.parse_suggestions(text)
        for s in suggestions:
            s["source"] = "ambient"
        return suggestions

    # -- duplicate prevention ----------------------------------------------

    def dedupe(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop suggestions already emitted this session (by source+title)."""
        fresh = []
        for s in suggestions:
            key = f"{s.get('source', '?')}:{s.get('title', '')}"
            if key in self._recently_emitted:
                continue
            self._recently_emitted.append(key)
            fresh.append(s)
        return fresh


# ---------------------------------------------------------------------------
# Unified runtime engine — rules + LLM sources, one policy, one emission path
# ---------------------------------------------------------------------------

class ProactiveEngine(ProactiveService):
    """The ONE proactive engine: rule-based (inherited ``ProactiveService``)
    and LLM-based (``ProactiveLLMEngine``) suggestion sources share a single
    toggle, cooldown and hourly cap, plus duplicate prevention and
    subscriber-based event emission. Both the FOL API/WebSocket path and the
    orchestrator SSE transport hook this engine — there is no second
    proactive system.
    """

    def __init__(
        self,
        assistant: ProactiveAssistant | None = None,
        llm_engine: ProactiveLLMEngine | None = None,
        *,
        enabled: bool = False,
        cooldown_minutes: int = 5,
        max_per_hour: int = 3,
        session_start: float | None = None,
    ) -> None:
        super().__init__(
            assistant=assistant,
            enabled=enabled,
            cooldown_minutes=cooldown_minutes,
            max_per_hour=max_per_hour,
            session_start=session_start,
        )
        self._llm_engine = llm_engine if llm_engine is not None else ProactiveLLMEngine()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []

    # -- event emission ---------------------------------------------------

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register an event sink (WebSocket broadcaster, SSE broadcaster, …)."""
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _emit(self, payload: dict[str, Any]) -> None:
        """Push an event to every subscriber — best-effort, never raises."""
        for cb in list(self._subscribers):
            try:
                cb(payload)
            except Exception:
                logger.debug("ProactiveEngine subscriber raised", exc_info=True)

    # -- rule-based path ---------------------------------------------------

    async def suggest_rules(
        self,
        context_extra: dict[str, Any] | None = None,
        *,
        force: bool = False,
    ) -> ProactiveSuggestion | None:
        """Evaluate the deterministic rules and emit the result (if any)."""
        suggestion = await self.check(context_extra=context_extra, force=force)
        if suggestion is not None:
            self._emit({
                "kind": "proactive",
                "source": "rules",
                "id": f"sug_{uuid.uuid4().hex[:8]}",
                "title": suggestion.title,
                "description": suggestion.description,
                "action_id": suggestion.action,
                "context": {"category": suggestion.category, "priority": suggestion.priority},
            })
        return suggestion

    # -- LLM-based path ----------------------------------------------------

    async def suggest_llm(
        self,
        mode: str,
        data: Any,
        *,
        profile: dict | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """Generate LLM suggestions for ``mode`` (profile/pattern/ambient)
        through the single anti-nagging policy, dedupe and emission.

        Returns the suggestions actually emitted this call ([] when the
        feature is off, in cooldown, over the hourly cap, or nothing fired).
        """
        if not self._enabled and not force:
            return []
        now = time.time()
        self._emission_times = deque(t for t in self._emission_times if now - t < 3600)
        if not force:
            if (
                self._last_emitted_at is not None
                and now - self._last_emitted_at < self._cooldown_seconds
            ):
                return []
            if len(self._emission_times) >= self._max_per_hour:
                return []

        if mode == "profile":
            raw = self._llm_engine.profile_trigger(data)
        elif mode == "pattern":
            raw = self._llm_engine.pattern_trigger(data, profile)
        elif mode == "ambient":
            raw = self._llm_engine.ambient_tick(data, profile)
        else:
            logger.warning("ProactiveEngine unknown LLM mode %r", mode)
            return []

        emitted = self._llm_engine.dedupe(raw)
        for s in emitted:
            self._emission_times.append(now)
            self._last_emitted_at = now
            self._emit({
                "kind": "proactive",
                **s,
            })
        return emitted

    def stats(self) -> dict[str, Any]:
        base = super().stats()
        base["llm_sources"] = ["profile", "pattern", "ambient"]
        return base
