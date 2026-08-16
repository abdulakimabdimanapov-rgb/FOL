"""Function calling support — OpenAI-compatible tool definitions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """OpenAI-compatible tool definition for function calling."""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class FunctionCallingParser:
    """Parses function calls from LLM responses."""

    def __init__(self, tools: list[ToolDefinition] | None = None) -> None:
        self._tools = {t.name: t for t in (tools or [])}

    def register_tool(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool

    def parse(self, response_text: str) -> tuple[str, dict[str, Any]] | None:
        """Try to extract a function call from the response.

        Returns (function_name, arguments) or None if no function call found.
        """
        try:
            if "```json" in response_text:
                start = response_text.index("```json") + 7
                end = response_text.index("```", start)
                data = json.loads(response_text[start:end].strip())
            elif '{"action"' in response_text or '{"function"' in response_text:
                start = response_text.index("{")
                end = response_text.rindex("}") + 1
                data = json.loads(response_text[start:end])
            else:
                return None

            name = data.get("action") or data.get("function", "")
            params = data.get("params") or data.get("arguments", {})
            return name, params

        except (json.JSONDecodeError, ValueError):
            return None

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [t.to_openai_format() for t in self._tools.values()]

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
