"""Prompt manager — manages system prompts, templates, and personalization."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from config.constants import FOL_DIR

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are F.O.L. (Friendly Obedient Listener), a personal AI assistant inspired by JARVIS.
You are running on a MacBook Air M2. You are helpful, concise, and professional.
Always address the user as "sir". Respond in the same language the user uses.
If you need to perform actions on the computer, describe what you will do.

FOL is a personal AI assistant.
He communicates naturally and conversationally.
He is intelligent, calm, confident, friendly and occasionally humorous.
He behaves like a capable personal companion rather than an API.
He never exposes internal tool calls, JSON, reasoning, debug information or implementation details.
After completing an action, he gives a natural contextual response describing what actually happened.
For simple actions, keep responses concise. For conversations, behave naturally and engage with the user.
Use light humor when appropriate. Do not overuse JARVIS phrases or honorifics.
Always prioritize usefulness and context.
Never answer with a bare "Done.", "Готово.", "OK.", "Выполнено." or "Task completed." — describe the outcome instead.
Never respond with a generic offer of help ("How can I help you?", "Чем могу помочь?", "I'm here to help.") unless the user just greeted you.
When the user asks a concrete question, answer it DIRECTLY with a concrete, useful answer in the user's language.
If you genuinely cannot answer, say so and offer to search the web or check memory — never deflect with a generic greeting.
Keep answers concise and never repeat the same sentence twice."""


class PromptManager:
    """Manages system prompts, templates, and user-personalized prompts."""

    def __init__(self, prompts_dir: Path | None = None) -> None:
        self._dir = prompts_dir or (FOL_DIR / "prompts")
        self._custom_system_prompt: str = ""
        self._templates: dict[str, str] = {}

    async def initialize(self) -> None:
        """Load custom prompts from disk."""
        self._dir.mkdir(parents=True, exist_ok=True)
        custom_prompt = self._dir / "system.md"
        if custom_prompt.exists():
            self._custom_system_prompt = custom_prompt.read_text(encoding="utf-8")
            logger.info("Custom system prompt loaded")

    async def get_system_prompt(self, user_context: dict[str, Any] | None = None) -> str:
        """Get the system prompt, optionally personalized with user context."""
        prompt = self._custom_system_prompt or DEFAULT_SYSTEM_PROMPT

        if user_context:
            context_lines = []
            for key, value in user_context.items():
                context_lines.append(f"- {key}: {value}")
            if context_lines:
                prompt += "\n\nUser context:\n" + "\n".join(context_lines)

        return prompt

    async def set_system_prompt(self, prompt: str) -> None:
        """Set a custom system prompt."""
        self._custom_system_prompt = prompt
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / "system.md").write_text(prompt, encoding="utf-8")
            logger.info("System prompt saved")
        except Exception as exc:
            logger.error("Failed to save system prompt: %s", exc)

    async def get_template(self, name: str) -> str | None:
        """Get a named prompt template."""
        return self._templates.get(name)

    async def set_template(self, name: str, template: str) -> None:
        """Set a named prompt template."""
        self._templates[name] = template

    async def render_template(self, template_name: str, variables: dict[str, Any] | None = None) -> str:
        """Render a template with variables."""
        template = self._templates.get(template_name, "")
        if not template:
            return ""
        try:
            return template.format(**(variables or {}))
        except KeyError as exc:
            logger.warning("Template variable missing: %s", exc)
            return template

    async def shutdown(self) -> None:
        """No-op shutdown for interface compatibility."""
        pass

    @property
    def has_custom_prompt(self) -> bool:
        return bool(self._custom_system_prompt)
