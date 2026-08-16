"""Multi-model router — chooses the best model for each task."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Any

from modules.llm.base import AbstractLLMBackend, LLMResponse

logger = logging.getLogger(__name__)


class TaskComplexity(enum.Enum):
    """Task complexity levels."""

    SIMPLE = "simple"       # Greetings, time, date — use fast/cheap model
    MODERATE = "moderate"   # General questions, conversation — use balanced model
    COMPLEX = "complex"     # Coding, analysis, multi-step — use powerful model


@dataclass
class ModelProfile:
    """Profile for a model backend."""

    name: str
    complexity: TaskComplexity
    speed: float = 1.0       # Relative speed (higher = faster)
    quality: float = 1.0     # Relative quality (higher = better)
    cost: float = 0.0        # Cost per 1K tokens (0 = free)
    max_tokens: int = 4096


class ModelRouter:
    """Routes requests to the best model based on task complexity."""

    def __init__(self, backends: dict[str, AbstractLLMBackend] | None = None) -> None:
        self._backends = backends or {}
        self._profiles: dict[str, ModelProfile] = {}
        self._complexity_detector = ComplexityDetector()

    def register_model(self, name: str, backend: AbstractLLMBackend, profile: ModelProfile) -> None:
        """Register a model with its profile."""
        self._backends[name] = backend
        self._profiles[name] = profile

    def detect_complexity(self, query: str) -> TaskComplexity:
        """Detect task complexity from the query."""
        return self._complexity_detector.detect(query)

    async def route(self, query: str, **kwargs: Any) -> LLMResponse:
        """Route a query to the best available model."""
        complexity = self.detect_complexity(query)
        best_model = self._select_model(complexity)

        if best_model is None:
            return LLMResponse(text="[No models available]")

        backend = self._backends.get(best_model)
        if backend is None:
            return LLMResponse(text=f"[Model {best_model} not found]")

        messages = kwargs.get("messages", [{"role": "user", "content": query}])
        max_tokens = kwargs.get("max_tokens", self._profiles[best_model].max_tokens)
        temperature = kwargs.get("temperature", 0.7)

        logger.info("Routing to model", model=best_model, complexity=complexity.value)
        return await backend.generate(messages, max_tokens=max_tokens, temperature=temperature)

    def _select_model(self, complexity: TaskComplexity) -> str | None:
        """Select the best model for the given complexity."""
        candidates = []
        for name, profile in self._profiles.items():
            if name in self._backends:
                # Score based on complexity match
                if complexity == TaskComplexity.SIMPLE:
                    score = profile.speed * 2 + profile.quality - profile.cost * 10
                elif complexity == TaskComplexity.COMPLEX:
                    score = profile.quality * 2 + profile.speed - profile.cost * 5
                else:
                    score = profile.quality + profile.speed - profile.cost * 7
                candidates.append((name, score))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    @property
    def available_models(self) -> list[str]:
        return list(self._backends.keys())

    @property
    def model_profiles(self) -> dict[str, ModelProfile]:
        return self._profiles.copy()


class ComplexityDetector:
    """Detects task complexity from user input."""

    COMPLEX_KEYWORDS = {
        "code", "write", "implement", "debug", "fix", "error", "refactor",
        "analyze", "compare", "explain how", "why does", "design", "architect",
        "наиший", "реализуй", "отладь", "исправь", "ошибка", "сравни",
        "объясни", "почему", "спроектируй",
    }

    SIMPLE_KEYWORDS = {
        "hello", "hi", "hey", "time", "date", "status", "help",
        "привет", "время", "дата", "помощь",
    }

    def detect(self, query: str) -> TaskComplexity:
        """Detect complexity of a query."""
        lower = query.lower().strip()

        # Check simple keywords
        words = set(lower.split())
        if words & self.SIMPLE_KEYWORDS:
            return TaskComplexity.SIMPLE

        # Check complex keywords
        if any(kw in lower for kw in self.COMPLEX_KEYWORDS):
            return TaskComplexity.COMPLEX

        # Length-based heuristic
        if len(lower.split()) > 20:
            return TaskComplexity.COMPLEX
        if len(lower.split()) < 5:
            return TaskComplexity.SIMPLE

        return TaskComplexity.MODERATE
