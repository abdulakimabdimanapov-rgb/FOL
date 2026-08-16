"""Explicit execution pipeline — the canonical request flow of FOL.

The pipeline makes the intended runtime flow explicit and deterministic:

    USER REQUEST → INTENT → CONTEXT → MEMORY RETRIEVAL → PLAN →
    TOOL / AGENT SELECTION → EXECUTION → VERIFICATION → RESPONSE →
    MEMORY UPDATE

Stages are run strictly in order. A stage with no registered handler is
recorded as ``skipped`` (with a reason) and the pipeline continues — so
e.g. TOOL_SELECTION/EXECUTION are no-ops when no tool executor is wired
(they live in the app layer today). Every stage result is recorded with its
duration, making the pipeline observable and unit-testable.

This is NOT a fake AGI layer: each stage is a plain async handler bound to
real modules (context manager, RAG memory, LLM, …) — see
``core.orchestrator.Orchestrator._build_pipeline`` for the live wiring.
"""

from __future__ import annotations

import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[Any]]


class PipelineStage(str, enum.Enum):
    """Canonical pipeline stages, in execution order."""

    INTENT = "intent"                    # what the user wants / follow-up?
    CONTEXT = "context"                  # assemble conversation + session context
    MEMORY_RETRIEVAL = "memory_retrieval"  # RAG / long-term memory retrieval
    PLAN = "plan"                        # decide approach (thinking prompt)
    TOOL_SELECTION = "tool_selection"    # pick tools/agents (app layer today)
    EXECUTION = "execution"              # run the chosen tools
    VERIFICATION = "verification"        # validate the produced response
    RESPONSE = "response"                # LLM generation / final answer
    MEMORY_UPDATE = "memory_update"      # persist the turn / episodes


@dataclass
class StageResult:
    """Outcome of one pipeline stage."""

    stage: PipelineStage
    status: str                      # "ok" | "skipped" | "error"
    output: Any = None
    error: str = ""
    duration_ms: float = 0.0
    note: str = ""


@dataclass
class PipelineResult:
    """Outcome of a full pipeline run."""

    user_input: str
    response: str = ""
    stages: list[StageResult] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)

    def stage(self, name: PipelineStage | str) -> StageResult | None:
        """Get the result of a stage by enum or string name."""
        key = name.value if isinstance(name, PipelineStage) else name
        for result in self.stages:
            if result.stage.value == key:
                return result
        return None

    @property
    def succeeded(self) -> bool:
        return bool(self.response) and not any(
            r.status == "error" for r in self.stages
        )

    def summary(self) -> dict[str, Any]:
        """Compact, serialisable summary for logs / dashboards."""
        return {
            "input": self.user_input,
            "response": self.response[:200],
            "stages": [
                {"stage": r.stage.value, "status": r.status, "ms": round(r.duration_ms, 1)}
                for r in self.stages
            ],
        }


class ExecutionPipeline:
    """Deterministic multi-stage pipeline.

    Usage::

        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.INTENT)
        async def intent(state): ...

        result = await pipeline.run("hello")
    """

    ORDER: list[PipelineStage] = [
        PipelineStage.INTENT,
        PipelineStage.CONTEXT,
        PipelineStage.MEMORY_RETRIEVAL,
        PipelineStage.PLAN,
        PipelineStage.TOOL_SELECTION,
        PipelineStage.EXECUTION,
        PipelineStage.VERIFICATION,
        PipelineStage.RESPONSE,
        PipelineStage.MEMORY_UPDATE,
    ]

    def __init__(self) -> None:
        self._handlers: dict[PipelineStage, Handler] = {}

    def on(self, stage: PipelineStage) -> Callable[[Handler], Handler]:
        """Decorator registering a handler for a stage."""

        def decorator(handler: Handler) -> Handler:
            self.register(stage, handler)
            return handler

        return decorator

    def register(self, stage: PipelineStage, handler: Handler) -> None:
        if not callable(handler):
            raise TypeError(f"Handler for {stage.value} must be callable")
        self._handlers[stage] = handler

    def has_stage(self, stage: PipelineStage) -> bool:
        return stage in self._handlers

    async def run(
        self, user_input: str, *, initial_state: dict[str, Any] | None = None
    ) -> PipelineResult:
        """Run every stage in order over a shared mutable ``state`` dict.

        Handlers read/write ``state``; the conventional contract is that the
        RESPONSE (or VERIFICATION) stage writes ``state["response"]``.
        """
        state: dict[str, Any] = dict(initial_state or {})
        state["user_input"] = user_input
        results: list[StageResult] = []

        for stage in self.ORDER:
            handler = self._handlers.get(stage)
            if handler is None:
                results.append(
                    StageResult(
                        stage=stage,
                        status="skipped",
                        note="no handler registered",
                    )
                )
                continue

            started = time.perf_counter()
            try:
                output = await handler(state)
                results.append(
                    StageResult(
                        stage=stage,
                        status="ok",
                        output=output,
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                    )
                )
            except Exception as exc:
                logger.error("Pipeline stage %s failed: %s", stage.value, exc)
                results.append(
                    StageResult(
                        stage=stage,
                        status="error",
                        error=str(exc),
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                    )
                )

        return PipelineResult(
            user_input=user_input,
            response=str(state.get("response", "") or ""),
            stages=results,
            state=state,
        )


__all__ = [
    "PipelineStage",
    "StageResult",
    "PipelineResult",
    "ExecutionPipeline",
]
