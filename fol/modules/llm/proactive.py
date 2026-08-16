"""Proactive assistant — suggests actions and reminders based on context.

Two layers, one module:

- :class:`ProactiveAssistant` — pure rules engine (time/session/context rules).
- :class:`ProactiveService` — runtime wrapper the FOL app uses: owns session
  stats (command counts, session length), the ON/OFF toggle, the cooldown and
  the per-hour cap (anti-nagging policy required by the ROADMAP), and
  delegates evaluation to the same assistant. No parallel system.
"""

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

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
