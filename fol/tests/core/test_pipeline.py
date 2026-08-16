"""Regression tests for the explicit execution pipeline (core/pipeline.py).

Verifies the canonical request flow is deterministic, ordered, observable
and resilient to stage failures.
"""

from __future__ import annotations

import pytest

from core.pipeline import ExecutionPipeline, PipelineResult, PipelineStage, StageResult


class TestStageOrder:
    def test_canonical_order(self):
        assert [s.value for s in ExecutionPipeline.ORDER] == [
            "intent",
            "context",
            "memory_retrieval",
            "plan",
            "tool_selection",
            "execution",
            "verification",
            "response",
            "memory_update",
        ]

    def test_order_is_user_request_to_memory_update(self):
        order = ExecutionPipeline.ORDER
        assert order[0] is PipelineStage.INTENT
        assert order[-1] is PipelineStage.MEMORY_UPDATE


class TestPipelineRun:
    async def test_unwired_stages_are_skipped(self):
        result = await ExecutionPipeline().run("hello")
        assert result.response == ""
        assert len(result.stages) == len(ExecutionPipeline.ORDER)
        assert all(r.status == "skipped" for r in result.stages)

    async def test_handlers_run_in_order(self):
        pipeline = ExecutionPipeline()
        order: list[str] = []

        @pipeline.on(PipelineStage.INTENT)
        async def _intent(state):
            order.append("intent")
            state["intent"] = "general"

        @pipeline.on(PipelineStage.RESPONSE)
        async def _response(state):
            order.append("response")
            state["response"] = f"answer:{state['user_input']}"

        @pipeline.on(PipelineStage.MEMORY_UPDATE)
        async def _update(state):
            order.append("memory_update")

        result = await pipeline.run("hi")
        assert order == ["intent", "response", "memory_update"]
        assert result.response == "answer:hi"

    async def test_state_is_shared_across_stages(self):
        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.CONTEXT)
        async def _context(state):
            state["context"] = "ctx-data"

        @pipeline.on(PipelineStage.RESPONSE)
        async def _response(state):
            state["response"] = state.get("context", "missing")

        result = await pipeline.run("x")
        assert result.response == "ctx-data"

    async def test_stage_error_is_recorded_and_pipeline_continues(self):
        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.CONTEXT)
        async def _boom(state):
            raise RuntimeError("context exploded")

        @pipeline.on(PipelineStage.RESPONSE)
        async def _response(state):
            state["response"] = "still answered"

        result = await pipeline.run("x")
        context_result = result.stage(PipelineStage.CONTEXT)
        assert context_result is not None
        assert context_result.status == "error"
        assert "exploded" in context_result.error
        assert result.response == "still answered"
        assert result.succeeded is False

    async def test_succeeded_flag(self):
        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.RESPONSE)
        async def _response(state):
            state["response"] = "fine"

        assert (await pipeline.run("x")).succeeded is True


class TestPipelineResult:
    async def test_stage_lookup_by_enum_and_string(self):
        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.INTENT)
        async def _intent(state):
            state["intent"] = "follow_up"

        result = await pipeline.run("а какая?")
        assert result.stage(PipelineStage.INTENT).status == "ok"
        assert result.stage("intent").status == "ok"
        assert result.stage("nope") is None

    async def test_summary_is_serialisable(self):
        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.RESPONSE)
        async def _response(state):
            state["response"] = "short answer"

        summary = (await pipeline.run("x")).summary()
        assert summary["input"] == "x"
        assert summary["response"] == "short answer"
        assert any(s["stage"] == "response" and s["status"] == "ok" for s in summary["stages"])

    async def test_initial_state_seeded(self):
        pipeline = ExecutionPipeline()

        @pipeline.on(PipelineStage.INTENT)
        async def _intent(state):
            state["intent"] = state["seed"]

        result = await pipeline.run("x", initial_state={"seed": "custom"})
        assert result.state["intent"] == "custom"


class TestRegistration:
    def test_register_and_has_stage(self):
        pipeline = ExecutionPipeline()

        async def _h(state):
            return None

        pipeline.register(PipelineStage.PLAN, _h)
        assert pipeline.has_stage(PipelineStage.PLAN)
        assert not pipeline.has_stage(PipelineStage.EXECUTION)

    def test_register_rejects_non_callable(self):
        pipeline = ExecutionPipeline()
        with pytest.raises(TypeError):
            pipeline.register(PipelineStage.PLAN, 42)  # type: ignore[arg-type]
