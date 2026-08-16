"""Central orchestrator that dispatches tasks and manages modules — with chain-of-thought reasoning."""

from __future__ import annotations

import logging
from typing import Any

from core.event_bus import Event, EventBus, EventType
from core.context_manager import ContextManager
from core.pipeline import ExecutionPipeline, PipelineResult, PipelineStage
from core.task_manager import TaskManager, TaskStatus

logger = logging.getLogger(__name__)

THINKING_PROMPT = """You are F.O.L., a brilliant AI assistant. Before answering, think step by step.

## Reasoning Process
1. **Understand**: What exactly is the user asking? Identify the core intent.
2. **Context**: What relevant information do I have from context, memories, and conversation history?
3. **Plan**: What's the best approach to answer this? Do I need tools? Should I search for more info?
4. **Execute**: If tools are needed, use them. Otherwise, compose your answer.
5. **Verify**: Is my answer accurate, complete, and in the right language?

## Rules
- If the question is ambiguous, ask a smart clarifying question.
- If you're not sure about something, say so honestly.
- For coding questions, think about edge cases.
- For creative tasks, consider multiple approaches.
- Always respond in the user's language.
- Never expose tool calls, JSON, reasoning, or debug information.
- After completing an action, give a natural contextual response describing what actually happened.
- Never answer with a bare "Done.", "Готово.", "OK.", "Выполнено." or "Task completed."
- Behave like a capable personal companion: intelligent, calm, confident, friendly, occasionally humorous.
- For simple actions, keep responses concise. For conversations, behave naturally and engage with the user.
- Do not overuse JARVIS phrases or honorifics.

## Context
{context}

## Task
{task}"""


class Orchestrator:
    """Central dispatcher coordinating input, LLM, tools, memory, and output — with reasoning."""

    def __init__(
        self,
        event_bus: EventBus,
        task_manager: TaskManager,
        context_manager: ContextManager,
    ) -> None:
        self._event_bus = event_bus
        self._task_manager = task_manager
        self._context_manager = context_manager
        self._modules: dict[str, Any] = {}
        self._reasoning_enabled = True  # Enable chain-of-thought by default
        # Most recent explicit pipeline run (for observability/tests).
        self._last_pipeline: PipelineResult | None = None

    def register_module(self, name: str, module: Any) -> None:
        """Register a module with the orchestrator."""
        self._modules[name] = module
        logger.info("Module registered", module=name)

    def get_module(self, name: str) -> Any | None:
        """Get a registered module by name."""
        return self._modules.get(name)

    async def process_input(self, user_input: str) -> str:
        """Process user input through the explicit execution pipeline.

        The runtime flow is made explicit and deterministic through
        ``core.pipeline.ExecutionPipeline`` (USER REQUEST → INTENT → CONTEXT →
        MEMORY RETRIEVAL → PLAN → TOOL/AGENT SELECTION → EXECUTION →
        VERIFICATION → RESPONSE → MEMORY UPDATE). Stage handlers are bound in
        ``_build_pipeline`` and behave exactly like the previous inline flow;
        the last run is available via ``orchestrator.last_pipeline``.
        """
        task = self._task_manager.create_task("process_input", f"Process: {user_input[:50]}...")

        try:
            # 1. Publish input received event
            await self._event_bus.publish(Event(
                type=EventType.USER_INPUT_RECEIVED,
                source="orchestrator",
                payload={"text": user_input},
            ))

            # 2. Run the explicit pipeline (intent → … → memory update)
            pipeline = self._build_pipeline()
            result = await pipeline.run(user_input)
            self._last_pipeline = result
            response = result.response

            # 3. Publish response event
            await self._event_bus.publish(Event(
                type=EventType.LLM_RESPONSE_READY,
                source="orchestrator",
                payload={"response": response},
            ))

            self._task_manager.update_status(task.id, TaskStatus.COMPLETED, result=response)
            return response

        except Exception as exc:
            logger.error("Input processing failed", error=str(exc))
            self._task_manager.update_status(task.id, TaskStatus.FAILED, error=str(exc))
            return f"Error processing input: {exc}"

    def _is_complex_query(self, user_input: str) -> bool:
        """Heuristic: is this query complex enough for chain-of-thought?"""
        return (
            len(user_input) > 15
            or "?" in user_input
            or any(w in user_input.lower() for w in [
                "why", "how", "explain", "почему", "как", "объясни",
                "help", "помоги", "сделай", "реши", "fix", "create",
                "open", "открой", "run", "запусти", "напиши", "write",
            ])
        )

    def _build_pipeline(self) -> ExecutionPipeline:
        """Build the explicit execution pipeline with the live stage handlers.

        TOOL_SELECTION / EXECUTION have no handler in the core orchestrator:
        tool execution happens in the app layer (``core.app.FOL.process``),
        which runs before the LLM path. They are recorded as skipped so the
        flow stays explicit and observable.
        """
        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.INTENT)
        async def _intent(state: dict[str, Any]) -> dict[str, Any]:
            user_input = state["user_input"]
            is_follow_up = self._context_manager.is_follow_up(user_input)
            state["is_follow_up"] = is_follow_up
            state["intent"] = "follow_up" if is_follow_up else "general"
            return {"intent": state["intent"], "is_follow_up": is_follow_up}

        @pipeline.on(PipelineStage.MEMORY_RETRIEVAL)
        async def _memory_retrieval(state: dict[str, Any]) -> str:
            user_input = state["user_input"]
            rag = self._modules.get("rag")
            rag_context = ""
            if rag is not None:
                try:
                    rag_context = await rag.retrieve_context(user_input, max_tokens=1500)
                except Exception as exc:
                    logger.debug("RAG context failed: %s", exc)
            state["rag_context"] = rag_context
            return rag_context

        @pipeline.on(PipelineStage.CONTEXT)
        async def _context(state: dict[str, Any]) -> str:
            user_input = state["user_input"]
            context = await self._assemble_context(
                user_input,
                is_follow_up=state.get("is_follow_up", False),
                rag_context=state.get("rag_context"),
            )
            state["context"] = context
            return context

        @pipeline.on(PipelineStage.PLAN)
        async def _plan(state: dict[str, Any]) -> str | None:
            user_input = state["user_input"]
            if not (self._reasoning_enabled and self._is_complex_query(user_input)):
                state["plan"] = None
                return None
            state["plan"] = THINKING_PROMPT.format(
                context=state.get("context", ""),
                task=user_input,
            )
            return state["plan"]

        @pipeline.on(PipelineStage.VERIFICATION)
        async def _verification(state: dict[str, Any]) -> bool:
            # Deterministic verification: is the plan executable? When no LLM
            # is registered the plan is dropped so RESPONSE falls back to the
            # rule-based path.
            if state.get("plan") and self._modules.get("llm") is None:
                state["plan"] = None
                state["verified"] = False
            else:
                state["verified"] = True
            return state["verified"]

        @pipeline.on(PipelineStage.RESPONSE)
        async def _response(state: dict[str, Any]) -> str:
            user_input = state["user_input"]
            llm = self._modules.get("llm")
            response = None
            if llm is not None:
                try:
                    if state.get("plan"):
                        response = await llm.generate(
                            user_input,
                            context=state.get("context", ""),
                            system_prompt=state["plan"],
                        )
                    else:
                        response = await llm.generate(user_input, context=state.get("context", ""))
                except Exception as exc:
                    logger.warning("LLM generation failed: %s", exc)
                    response = None
            # Final-response gate: fall back to rule-based if LLM unavailable
            # or returned an unusable answer.
            if not response or response.startswith("[") or response.startswith("All LLM"):
                response = self._simple_process(user_input)
            state["response"] = response
            return response

        @pipeline.on(PipelineStage.MEMORY_UPDATE)
        async def _memory_update(state: dict[str, Any]) -> None:
            user_input = state["user_input"]
            response = state.get("response", "")
            # Store in context
            self._context_manager.add_turn(user_input, response)
            # Store in RAG pipeline if available
            rag = self._modules.get("rag")
            if rag is not None:
                try:
                    await rag.store_conversation(user_input, response)
                except Exception as exc:
                    logger.debug("RAG store failed: %s", exc)

        return pipeline

    @property
    def last_pipeline(self) -> PipelineResult | None:
        """The most recent explicit pipeline run (None before the first).

        NOTE: this is shared mutable state on the orchestrator — safe for the
        current sequential usage, but concurrent ``process_input`` calls would
        race on it. Per-request pipeline results are always returned directly
        from ``process_input``.
        """
        return self._last_pipeline

    async def _assemble_context(
        self,
        user_input: str,
        is_follow_up: bool = False,
        rag_context: str | None = None,
    ) -> str:
        """Assemble rich context from all available sources.

        Gathers: conversation history, behavioral patterns, memories, preferences, RAG.
        When ``is_follow_up`` is True, an explicit follow-up grounding block
        (current topic + previous message) is placed first — this lets FOL
        resolve "а какая из них?" / "what about it?" against the ongoing topic.

        ``rag_context`` may be passed in from the pipeline's MEMORY_RETRIEVAL
        stage (avoiding a second retrieval); when ``None`` the RAG pipeline is
        queried here for backward compatibility.
        """
        sections = []

        # 0. Follow-up grounding — most important context for continuations
        if is_follow_up:
            follow_up_block = self._context_manager.get_follow_up_context(n=6)
            if follow_up_block:
                sections.append(follow_up_block)

        # 1. Recent conversation context
        recent = self._context_manager.get_recent_context(n=6)
        if recent and recent != "No recent context available.":
            sections.append(recent)

        # 2. RAG pipeline (memories, knowledge graph, preferences)
        rag = self._modules.get("rag")
        if rag is not None:
            try:
                if rag_context is None:
                    rag_context = await rag.retrieve_context(user_input, max_tokens=1500)
                if rag_context:
                    sections.append(rag_context)
            except Exception as exc:
                logger.debug("RAG context failed: %s", exc)

        # 3. Behavioral patterns
        # (behavioral_learner is accessed via the app, not directly here)

        # 4. Working memory
        wm = self._context_manager.get_working_memory("current_task")
        if wm:
            sections.append(f"Current task context: {wm}")

        # 5. Session metadata
        metadata = self._context_manager._session_metadata
        if metadata:
            meta_lines = [f"{k}: {v}" for k, v in metadata.items()]
            sections.append("Session info:\n" + "\n".join(meta_lines))

        return "\n\n".join(sections) if sections else ""

    def _simple_process(self, user_input: str) -> str:
        """Simple rule-based processing when no LLM is available."""
        lower = user_input.lower().strip()
        if lower in ("hello", "hi", "hey fol", "fol"):
            return "I'm here and fully online. What do you need?"
        if lower in ("help", "commands"):
            return (
                "F.O.L. commands:\n"
                "- status\n- time\n- date\n- remember <text>\n"
                "- remind me to <task> at <time>\n"
                "- list reminders\n- next reminder\n"
                "- open <AppName>\n- run <command>\n"
                "- scan screen\n- screen status\n- screen summary\n"
                "- notes\n- shutdown\n"
            )
        if lower in ("time", "what time is it"):
            from datetime import datetime
            return f"The current time is {datetime.now().strftime('%H:%M:%S')}."
        if lower in ("date", "today"):
            from datetime import datetime
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}."
        return "I didn't catch that. Try 'help' for available commands."

    @property
    def modules(self) -> dict[str, Any]:
        return self._modules.copy()
