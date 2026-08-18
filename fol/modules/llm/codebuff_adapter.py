"""Codebuff SDK Brain Adapter — uses @codebuff/sdk via Node.js subprocess.

This adapter wraps the Codebuff SDK (``@codebuff/sdk``) to provide a
``BrainInterface`` implementation. It runs Codebuff agents via a Node.js
subprocess and collects their output.

Requirements:
  - Node.js installed (``node`` on PATH)
  - ``@codebuff/sdk`` installed (``npm install -g @codebuff/sdk``)
  - ``CODEBUFF_API_KEY`` environment variable set

The adapter is ``available=True`` only when:
  1. ``CODEBUFF_API_KEY`` is set
  2. Node.js is available on PATH
  3. ``@codebuff/sdk`` is importable

Configuration (env vars):
  CODEBUFF_API_KEY    — required, your Codebuff API key
  CODEBUFF_AGENT      — agent ID (default: "codebuff/base@latest")
  CODEBUFF_TIMEOUT    — timeout in seconds (default: 120)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator

from modules.llm.brain import (
    BRAIN_INTENT_LABELS,
    BrainError,
    BrainInterface,
    BrainUnavailableError,
)
from modules.llm.freebuff import codebuff_config

logger = logging.getLogger(__name__)


class CodebuffSDKBrainAdapter(BrainInterface):
    """Brain adapter backed by the Codebuff SDK.

    Wraps ``@codebuff/sdk`` via a Node.js subprocess. The SDK is agent-based:
    each ``chat`` call runs a Codebuff agent with the user's prompt and
    returns the agent's output.

    This is a PAID integration — requires a Codebuff API key.
    Freebuff's free models are available through OpenRouter instead
    (set ``LLM_MODEL=openrouter/deepseek/deepseek-v4-flash``).
    """

    name = "codebuff"

    def __init__(self, *, config: dict[str, str] | None = None) -> None:
        self._config: dict[str, str] = dict(config or codebuff_config())
        self._node_available: bool | None = None
        self._sdk_available: bool | None = None

    @property
    def available(self) -> bool:
        """True when the adapter can actually be called."""
        if not self._config.get("api_key"):
            return False
        if self._node_available is None:
            self._node_available = shutil.which("node") is not None
        if not self._node_available:
            return False
        if self._sdk_available is None:
            self._sdk_available = self._check_sdk()
        return self._sdk_available

    def _check_sdk(self) -> bool:
        """Check if @codebuff/sdk is importable from Node.js."""
        try:
            result = subprocess.run(
                ["node", "-e", "require('@codebuff/sdk')"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.available,
            "agent": self._config.get("agent", "codebuff/base@latest"),
            "node_available": self._node_available,
            "sdk_available": self._sdk_available,
            "has_api_key": bool(self._config.get("api_key")),
        }

    def model_chain(self) -> list[str]:
        if not self.available:
            return []
        return ["codebuff/" + self._config.get("agent", "base")]

    def available_providers(self) -> list[str]:
        if not self.available:
            return []
        return ["codebuff"]

    def test_connection(self) -> str:
        if not self.available:
            reason = []
            if not self._config.get("api_key"):
                reason.append("no CODEBUFF_API_KEY")
            if self._node_available is False:
                reason.append("node not found")
            if self._sdk_available is False:
                reason.append("@codebuff/sdk not installed")
            return "❌ Codebuff unavailable: " + (", ".join(reason) or "unknown")
        return "✅ Codebuff SDK ready (agent=" + self._config.get("agent", "base") + ")"

    # -- internal -----------------------------------------------------------

    def _build_prompt(self, messages: list[dict[str, Any]], system: str | None) -> str:
        """Convert chat messages to a single prompt for the Codebuff agent."""
        parts: list[str] = []
        if system:
            parts.append("System: " + system)
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(str(block.get("text", "")))
                content = " ".join(text_parts)
            if content:
                parts.append(role.title() + ": " + content)
        return "\n".join(parts)

    async def _run_agent(self, prompt: str) -> dict[str, Any]:
        """Run a Codebuff agent via Node.js subprocess."""
        config = {
            "api_key": self._config.get("api_key", ""),
            "agent": self._config.get("agent", "codebuff/base@latest"),
            "prompt": prompt,
            "max_steps": 5,
            "cwd": str(Path.home()),
        }

        timeout = int(self._config.get("timeout", "120"))

        esm_script = (
            "import { CodebuffClient } from '@codebuff/sdk';\n"
            "\n"
            "const config = " + json.dumps(config) + ";\n"
            "const client = new CodebuffClient({\n"
            "    apiKey: config.api_key,\n"
            "    cwd: config.cwd,\n"
            "});\n"
            "\n"
            "try {\n"
            "    const result = await client.run({\n"
            "        agent: config.agent,\n"
            "        prompt: config.prompt,\n"
            "        maxAgentSteps: config.max_steps,\n"
            "    });\n"
            "    process.stdout.write(JSON.stringify({ ok: true, output: result.output }));\n"
            "} catch (err) {\n"
            "    process.stdout.write(JSON.stringify({ ok: false, error: err.message || String(err) }));\n"
            "}\n"
        )

        script_path = Path(tempfile.mktemp(suffix=".mjs"))
        try:
            script_path.write_text(esm_script)

            proc = await asyncio.create_subprocess_exec(
                "node", str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )

            output = (stdout or b"").decode("utf-8", errors="replace").strip()
            if not output:
                err_text = (stderr or b"").decode("utf-8", errors="replace").strip()
                return {"ok": False, "error": err_text or "empty output from Codebuff agent"}

            try:
                return json.loads(output)
            except json.JSONDecodeError:
                return {"ok": True, "output": output}

        except asyncio.TimeoutError:
            return {"ok": False, "error": "Codebuff agent timed out after %ds" % timeout}
        except FileNotFoundError:
            return {"ok": False, "error": "node not found on PATH"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except Exception:
                pass

    # -- conversational -----------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        if not self.available:
            raise BrainUnavailableError("Codebuff SDK not available")
        prompt = self._build_prompt(messages, system)
        result = _run_coro_sync(self._run_agent(prompt))
        if result.get("ok"):
            return str(result.get("output", ""))
        raise BrainError("Codebuff agent failed: " + str(result.get("error", "unknown")))

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if not self.available:
            yield {"type": "error", "message": "Codebuff SDK not available"}
            return
        prompt = self._build_prompt(messages, system)
        result = await self._run_agent(prompt)
        if result.get("ok"):
            output = str(result.get("output", ""))
            if output:
                yield {"type": "token", "text": output}
            yield {"type": "done", "stop_reason": "end_turn"}
        else:
            yield {"type": "error", "message": result.get("error", "Codebuff agent failed")}

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        if not self.available:
            raise BrainUnavailableError("Codebuff SDK not available")
        prompt = self._build_prompt(messages, system)
        result = await self._run_agent(prompt)
        if result.get("ok"):
            return {
                "content": str(result.get("output", "")),
                "tool_calls": [],
                "stop_reason": "end_turn",
            }
        return {
            "content": "",
            "tool_calls": [],
            "stop_reason": "error",
        }

    # -- reasoning capabilities --------------------------------------------

    def classify(self, text: str) -> str:
        labels = ", ".join(BRAIN_INTENT_LABELS)
        out = self.chat(
            [{"role": "user", "content": "Classify into one: %s\nText: %s" % (labels, text)}],
            max_tokens=10,
        )
        label = out.strip().rstrip(".").strip().lower()
        for candidate in BRAIN_INTENT_LABELS:
            if candidate in label:
                return candidate
        return "other"

    def plan(self, task: str, context: str = "") -> list[str]:
        ctx = "\nContext: " + context if context else ""
        out = self.chat(
            [{"role": "user", "content": "Plan: %s%s\nReturn numbered steps." % (task, ctx)}],
            max_tokens=200,
        )
        return [
            line.strip().lstrip("0123456789.)-").strip()
            for line in out.splitlines()
            if line.strip()
        ][:10]

    def select_tools(
        self, task: str, tools: list[dict[str, Any]]
    ) -> list[str]:
        known = {str(t.get("name", "")).strip() for t in tools if t.get("name")}
        if not known:
            return []
        catalog = "\n".join(
            "- %s: %s" % (t.get("name", ""), t.get("description", ""))
            for t in tools if t.get("name")
        )
        out = self.chat(
            [{"role": "user", "content": "Tools for: %s\nAvailable:\n%s\nReply with tool names only." % (task, catalog)}],
            max_tokens=60,
        )
        return [
            n for n in (line.strip().strip("*`").strip() for line in out.splitlines())
            if n in known
        ]

    def summarize(self, text: str, max_words: int = 80) -> str:
        return self.chat(
            [{"role": "user", "content": "Summarize in %d words:\n\n%s" % (max_words, text)}],
            max_tokens=max_words * 2,
        ).strip()

    def verify(self, claim: str, evidence: str) -> str:
        out = self.chat(
            [{"role": "user", "content": "Verdict: supported/partially supported/unsupported/insufficient evidence\nClaim: %s\nEvidence: %s" % (claim, evidence)}],
            max_tokens=10,
        )
        low = out.strip().rstrip(".").strip().lower()
        for v in ("partially supported", "insufficient evidence", "supported", "unsupported"):
            if v in low:
                return v
        return "insufficient evidence"


# ---------------------------------------------------------------------------
# Sync helper (run async from sync context)
# ---------------------------------------------------------------------------

def _run_coro_sync(coro: Any) -> Any:
    """Run a coroutine from a possibly-running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except Exception as exc:
            box["error"] = exc

    import threading
    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


__all__ = ["CodebuffSDKBrainAdapter"]
