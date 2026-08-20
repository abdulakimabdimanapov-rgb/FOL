"""ReAct Agent — multi-step reasoning with tool use."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from modules.llm.engine import LLMEngine

logger = logging.getLogger(__name__)

AGENT_PROMPT = """You are F.O.L., a brilliant personal AI assistant. You can use tools to perform actions on the user's Mac.

## How to reason
Think step by step. For each step:
1. **Thought**: Analyze what you know and what you need. Consider alternatives.
2. **Action**: Choose the best tool and parameters.
3. **Observation**: Review the tool result carefully before proceeding.

## Response format
When you need to use a tool, respond with EXACTLY this format:
```json
{"thought": "your step-by-step reasoning", "action": "tool_name", "params": {"param": "value"}}
```

When you have the final answer (no more tools needed), respond naturally without JSON.

## Few-shot examples

User: "Открой Safari и найди погоду в Москве"
Step 1:
```json
{"thought": "Нужно открыть Safari, а затем найти погоду. Начну с открытия браузера.", "action": "open_app", "params": {"name": "Safari"}}
```
Observation: Safari opened
Step 2:
```json
{"thought": "Safari открыт. Теперь перейду на Google и найду погоду.", "action": "browser_search", "params": {"query": "погода в Москве"}}
```
Observation: Search results loaded
Final: "Safari открыт, погода в Москве показана в поисковой выдаче! 🌤️"

## Available tools
{tools}

## Rules
- Maximum {max_iterations} steps
- If a tool fails, analyze the error and try an alternative approach
- Always explain what you're doing in your thoughts
- Prefer the simplest solution that works
- If a task requires multiple tools, plan the sequence first in your thoughts
- After getting tool results, always evaluate if you need more steps or have the answer

## Communication (MANDATORY)
- Never expose tool calls or JSON structures to the user.
- Always communicate using natural language.
- Tools are internal actions only — never mention tool names, arguments, or JSON.
- Never show your reasoning or internal step-by-step process.
- After using tools, confirm what you did in one short natural sentence.
- Never answer with a bare "Done.", "Готово.", "OK.", "Выполнено." or "Task completed." — describe the outcome instead.
- Never respond with a generic offer of help ("How can I help you?", "Чем могу помочь?") unless the user just greeted you.
- When the user asks a concrete question, answer it DIRECTLY with a concrete, useful answer.
- If you cannot answer, say so and offer to search — do not deflect with a greeting.
- Behave like a capable personal companion: intelligent, calm, confident, friendly, occasionally humorous.
- For simple actions, keep responses concise. For conversations, behave naturally and engage with the user.
- Do not overuse JARVIS phrases or honorifics."""


@dataclass
class AgentStep:
    """One step in the agent's reasoning."""

    thought: str = ""
    action: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    observation: str = ""
    id: UUID = field(default_factory=uuid4)
    success: bool = True


class ReActAgent:
    """Multi-step reasoning agent using Think → Act → Observe loop."""

    def __init__(
        self,
        llm_engine: LLMEngine,
        tool_registry: Any = None,
        max_iterations: int = 10,
    ) -> None:
        self._llm = llm_engine
        self._tools = tool_registry
        self._max_iterations = max_iterations
        self._steps: list[AgentStep] = []

    async def run(self, task: str) -> str:
        """Execute a task through multi-step reasoning."""
        self._steps = []
        context = f"Task: {task}\n\n"

        tools_desc = self._get_tools_description()
        system = AGENT_PROMPT.format(
            tools=tools_desc,
            max_iterations=self._max_iterations,
        )

        for i in range(self._max_iterations):
            logger.debug("Agent step", step=i + 1)

            # Build a rich prompt with full context
            if i == 0:
                user_prompt = task
            else:
                # Include all previous steps for full context
                step_history = "\n".join(
                    f"Step {j + 1}:\n  Thought: {s.thought}\n  Action: {s.action}({s.params})\n  Result: {s.observation}"
                    for j, s in enumerate(self._steps)
                )
                user_prompt = f"{context}\n\nPrevious steps:\n{step_history}\n\nWhat should I do next?"

            response_text = await self._llm.generate(
                user_prompt,
                context=context,
                system_prompt=system,
            )

            # Try to parse tool call
            parsed = self._parse_action(response_text)
            if parsed is None:
                # Final answer
                logger.info("Agent completed", steps=len(self._steps))
                return response_text

            # Execute tool
            step = AgentStep(
                thought=parsed.get("thought", ""),
                action=parsed.get("action", ""),
                params=parsed.get("params", {}),
            )

            observation = await self._execute_tool(step.action, step.params)
            step.observation = observation
            step.success = not observation.startswith("Tool") or "failed" not in observation.lower()
            self._steps.append(step)

            context += f"\nStep {i + 1}: Thought: {step.thought}\nAction: {step.action}({step.params})\nObservation: {observation}\n"

            # If tool failed, add a retry hint
            if not step.success:
                context += f"The tool failed. Consider trying a different approach.\n"

        return f"I completed {len(self._steps)} steps but reached the maximum iteration limit. Here's what I accomplished:\n" + "\n".join(
            f"- {s.thought}" for s in self._steps
        )

    def _parse_action(self, text: str) -> dict[str, Any] | None:
        """Try to extract a JSON action block from the response."""
        try:
            if "```json" in text:
                start = text.index("```json") + 7
                end = text.index("```", start)
                return json.loads(text[start:end].strip())
            if '{"thought"' in text or '{"action"' in text:
                start = text.index("{")
                end = text.rindex("}") + 1
                return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    async def _execute_tool(self, action: str, params: dict[str, Any]) -> str:
        """Execute a tool by name."""
        if self._tools is None:
            return f"Tool '{action}' not available (no tool registry)."

        tool = self._tools.get(action)
        if tool is None:
            # Try fuzzy matching
            available = [t.name for t in self._tools.list_all()] if self._tools else []
            close = [t for t in available if action.lower() in t.lower() or t.lower() in action.lower()]
            if close:
                return f"Tool '{action}' not found. Did you mean: {', '.join(close)}?"
            return f"Tool '{action}' not found. Available: {', '.join(available[:10])}"

        try:
            result = await tool.execute(params)
            return str(result)
        except Exception as exc:
            return f"Tool '{action}' failed: {exc}"

    def _get_tools_description(self) -> str:
        """Get formatted description of available tools."""
        if self._tools is None:
            return "No tools available."
        tools = self._tools.list_all()
        if not tools:
            return "No tools registered."
        lines = []
        for tool in tools:
            # Include parameter info for better tool selection
            param_info = ""
            if hasattr(tool, "parameters") and tool.parameters:
                props = tool.parameters.get("properties", {})
                required = tool.parameters.get("required", [])
                param_names = list(props.keys())
                if param_names:
                    param_info = f" — params: {', '.join(param_names)}"
                    if required:
                        param_info += f" (required: {', '.join(required)})"
            lines.append(f"- {tool.name}: {tool.description}{param_info}")
        return "\n".join(lines)

    @property
    def steps(self) -> list[AgentStep]:
        return self._steps.copy()
