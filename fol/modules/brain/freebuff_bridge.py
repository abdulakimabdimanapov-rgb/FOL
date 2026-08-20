"""Freebuff PTY Bridge — BrainInterface backed by the Freebuff CLI via PTY.

This is the PRIMARY brain backend for FOL. It launches the Freebuff CLI
as a persistent child process in a real pseudo-terminal, communicates via
PTY I/O, and implements the full BrainInterface contract.

Architecture:
    FOL
     ↓
    FreebuffBridgeCLI (this module — BrainInterface)
     ↓
    FreebuffSession (real PTY session)
     ↓
    Freebuff CLI (TUI binary at ~/.config/manicode/freebuff)
     ↓
    Response
     ↓
    FreebuffParser (ANSI cleanup)
     ↓
    FOL Core

Configuration (env vars):
    FOL_BRAIN=freebuff_cli       — select this brain
    FREEBUFF_BINARY=freebuff     — binary name/path (default: "freebuff")
    FREEBUFF_CWD=<project>       — working directory
    FREEBUFF_AUTO_START=true     — auto-start on FOL boot
    FREEBUFF_START_TIMEOUT=15    — seconds to wait for CLI ready
    FREEBUFF_RESPONSE_TIMEOUT=300 — seconds to wait for a response
    FREEBUFF_SETTLE_MS=1500      — ms of silence = response complete
    FREEBUFF_RESTART_ATTEMPTS=2  — max restart attempts on crash

Safety:
    - Freebuff does NOT get direct access to system tools
    - All tool calls go through FOL's ToolRegistry → RiskScorer → ConfirmationGate
    - API keys and secrets are never logged
    - The bridge only manages the PTY I/O — no fake HTTP APIs
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from typing import Any, AsyncIterator, Optional

from modules.llm.brain import (
    BRAIN_INTENT_LABELS,
    BrainError,
    BrainInterface,
    BrainConfigurationError,
    BrainUnavailableError,
)
from modules.brain.freebuff_session import (
    FreebuffSession,
    SessionConfig,
    SessionState,
    create_session,
)
from modules.brain.freebuff_parser import extract_response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _bridge_config() -> dict[str, str]:
    """Read bridge configuration from environment."""
    return {
        "binary": (os.environ.get("FREEBUFF_BINARY") or "freebuff").strip(),
        "cwd": (os.environ.get("FREEBUFF_CWD") or "").strip(),
        "auto_start": (os.environ.get("FREEBUFF_AUTO_START") or "true").strip().lower(),
        "start_timeout": (os.environ.get("FREEBUFF_START_TIMEOUT") or "15").strip(),
        "response_timeout": (os.environ.get("FREEBUFF_RESPONSE_TIMEOUT") or "300").strip(),
        "settle_ms": (os.environ.get("FREEBUFF_SETTLE_MS") or "1500").strip(),
        "restart_attempts": (os.environ.get("FREEBUFF_RESTART_ATTEMPTS") or "2").strip(),
    }


# ---------------------------------------------------------------------------
# FreebuffBridgeCLI — BrainInterface via PTY
# ---------------------------------------------------------------------------

class FreebuffBridgeCLI(BrainInterface):
    """Brain backend backed by the Freebuff CLI via a real PTY session.

    This is the PRIMARY brain for FOL. It:
      1. Launches Freebuff CLI in a persistent PTY session
      2. Sends user messages via PTY stdin
      3. Reads responses from PTY stdout
      4. Cleans ANSI/TUI artifacts from output
      5. Returns clean text through the BrainInterface contract

    The session is persistent — one Freebuff process serves all requests
    for the lifetime of FOL. This preserves Freebuff's conversation context.

    Fallback: if the PTY session fails, the BrainRouter falls back to
    CurrentLLMAdapter (API providers).

    Configuration:
        FOL_BRAIN=freebuff_cli    — select this brain
        FREEBUFF_BINARY=freebuff  — binary name
        FREEBUFF_CWD=<project>    — working directory
    """

    name = "freebuff_cli"

    def __init__(self) -> None:
        self._config = _bridge_config()
        self._session: Optional[FreebuffSession] = None
        self._initialized = False
        self._init_error: Optional[str] = None
        self._restart_count = 0
        self._max_restarts = int(self._config.get("restart_attempts", "2"))
        self._request_count = 0
        self._total_latency: float = 0.0

    @property
    def available(self) -> bool:
        """True when Freebuff CLI is installed and the session is ready."""
        if self._session and self._session.is_alive:
            return True
        if self._initialized and self._session and self._session.state == SessionState.READY:
            return True
        # Check if binary is available at all
        return self._check_binary()

    def _check_binary(self) -> bool:
        """Check if the Freebuff binary is available."""
        binary = self._config.get("binary", "freebuff")
        if shutil.which(binary):
            return True
        # Also check via npx
        try:
            import subprocess
            result = subprocess.run(
                ["npx", binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        """Return current status (never contains secrets)."""
        session_state = self._session.state.value if self._session else "no_session"
        return {
            "backend": self.name,
            "available": self.available,
            "session_state": session_state,
            "pid": self._session.pid if self._session else None,
            "cwd": self._session._info.cwd if self._session else None,
            "request_count": self._request_count,
            "avg_latency_ms": (
                int(self._total_latency / self._request_count * 1000)
                if self._request_count > 0 else 0
            ),
            "restart_count": self._restart_count,
            "error": self._init_error,
        }

    def model_chain(self) -> list[str]:
        if not self.available:
            return []
        return ["freebuff_cli/" + self._config.get("binary", "freebuff")]

    def available_providers(self) -> list[str]:
        if not self.available:
            return []
        return ["freebuff_cli"]

    def test_connection(self) -> str:
        """Test if the Freebuff CLI is reachable."""
        if not self._check_binary():
            return "❌ Freebuff CLI not found. Install: npm install -g freebuff"
        if self._session and self._session.is_alive:
            return f"✅ Freebuff CLI ready (pid={self._session.pid})"
        return "⚠️ Freebuff CLI found but session not active"

    # -- Session management -------------------------------------------------

    async def ensure_session(self) -> FreebuffSession:
        """Ensure a PTY session is running. Create one if needed.

        Returns the active session.
        Raises BrainUnavailableError if session cannot be created.
        """
        if self._session and self._session.is_alive:
            return self._session

        if self._session and self._session.state == SessionState.ERROR:
            # Attempt restart
            if self._restart_count < self._max_restarts:
                self._restart_count += 1
                logger.info("Restarting Freebuff session (attempt %d/%d)", self._restart_count, self._max_restarts)
                await self._close_session()
            else:
                raise BrainUnavailableError(
                    f"Freebuff CLI crashed {self._restart_count} times. "
                    f"Max restart attempts ({self._max_restarts}) exceeded."
                )

        # Create new session
        config = SessionConfig(
            binary=self._config.get("binary", "freebuff"),
            cwd=self._config.get("cwd", ""),
            start_timeout=float(self._config.get("start_timeout", "15")),
            response_timeout=float(self._config.get("response_timeout", "300")),
            settle_ms=int(self._config.get("settle_ms", "1500")),
        )

        self._session = create_session(
            binary=config.binary,
            cwd=config.cwd,
            start_timeout=config.start_timeout,
            response_timeout=config.response_timeout,
            settle_ms=config.settle_ms,
        )

        # Start session
        if not await self._session.create():
            self._init_error = self._session._info.error_message or "Session creation failed"
            raise BrainUnavailableError(f"Failed to start Freebuff CLI: {self._init_error}")

        # Wait for ready
        if not await self._session.wait_ready():
            self._init_error = self._session._info.error_message or "Ready timeout"
            raise BrainUnavailableError(f"Freebuff CLI not ready: {self._init_error}")

        self._initialized = True
        self._init_error = None
        logger.info("Freebuff PTY session ready (pid=%d)", self._session.pid)
        return self._session

    async def _close_session(self) -> None:
        """Close the current session."""
        if self._session:
            await self._session.close()
            self._session = None

    # -- Prompt construction ------------------------------------------------

    def _build_prompt(self, messages: list[dict[str, Any]], system: str | None) -> str:
        """Convert chat messages to a single prompt for Freebuff.

        Freebuff CLI expects plain text input. We flatten the conversation
        into a single prompt with context.
        """
        parts: list[str] = []

        if system:
            parts.append(f"[System: {system}]")

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
                if role == "user":
                    parts.append(content)
                elif role == "assistant":
                    parts.append(f"Assistant: {content}")
                elif role == "system":
                    parts.append(f"[System: {content}]")

        return "\n".join(parts)

    # -- Core communication -------------------------------------------------

    async def _send_and_receive(
        self,
        text: str,
        timeout: Optional[float] = None,
    ) -> str:
        """Send a message to Freebuff and receive the response.

        This is the core communication method. It:
        1. Ensures a PTY session is active
        2. Sends the message via PTY stdin
        3. Reads the response from PTY stdout
        4. Returns the clean response text
        """
        start = time.time()
        try:
            session = await self.ensure_session()

            # Send message
            if not await session.send_message(text):
                raise BrainError("Failed to send message to Freebuff CLI")

            # Read response
            response = await session.read_response(
                timeout=timeout,
                input_text=text,
            )

            elapsed = time.time() - start
            self._request_count += 1
            self._total_latency += elapsed

            if not response:
                raise BrainError("Freebuff CLI returned empty response")

            return response

        except BrainUnavailableError:
            raise
        except BrainError:
            raise
        except Exception as exc:
            raise BrainError(f"Freebuff bridge error: {exc}") from exc

    # -- BrainInterface implementation --------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Complete a conversation via Freebuff CLI PTY."""
        prompt = self._build_prompt(messages, system)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in an async context — run in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self._send_and_receive(prompt),
                )
                return future.result(timeout=float(self._config.get("response_timeout", "300")))
        else:
            return asyncio.run(self._send_and_receive(prompt))

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream completion via Freebuff CLI PTY."""
        prompt = self._build_prompt(messages, system)
        try:
            session = await self.ensure_session()
        except BrainUnavailableError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        try:
            if not await session.send_message(prompt):
                yield {"type": "error", "message": "Failed to send message"}
                return

            async for event in session.read_response_streaming(input_text=prompt):
                if event["type"] == "chunk":
                    yield {"type": "token", "text": event["text"]}
                elif event["type"] == "done":
                    yield {"type": "done", "stop_reason": "end_turn"}
                elif event["type"] == "error":
                    yield {"type": "error", "message": event["message"]}
                    return

        except Exception as exc:
            yield {"type": "error", "message": f"Freebuff bridge error: {exc}"}

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Async completion via Freebuff CLI PTY."""
        prompt = self._build_prompt(messages, system)
        try:
            response = await self._send_and_receive(prompt)
            return {
                "content": response,
                "tool_calls": [],
                "stop_reason": "end_turn",
            }
        except BrainUnavailableError:
            raise
        except BrainError as exc:
            return {
                "content": "",
                "tool_calls": [],
                "stop_reason": "error",
            }

    # -- Reasoning capabilities (prompt wrappers) --------------------------

    def classify(self, text: str) -> str:
        labels = ", ".join(BRAIN_INTENT_LABELS)
        out = self.chat(
            [{"role": "user", "content": (
                f"Classify the user request into exactly one label: "
                f"{labels}.\nRequest: {text}\nAnswer with one label only."
            )}],
            max_tokens=10,
            temperature=0,
        )
        label = out.strip().strip(".").strip().lower()
        for candidate in BRAIN_INTENT_LABELS:
            if candidate in label:
                return candidate
        return "other"

    def plan(self, task: str, context: str = "") -> list[str]:
        ctx = f"\nContext:\n{context}" if context else ""
        out = self.chat(
            [{"role": "user", "content": (
                f"Plan how to accomplish the task. Return a concise "
                f"numbered list of steps (one step per line).\nTask: {task}{ctx}"
            )}],
            max_tokens=200,
        )
        steps = [
            line.strip().lstrip("0123456789.)-").strip()
            for line in out.splitlines()
            if line.strip()
        ]
        return [s for s in steps if s]

    def select_tools(
        self, task: str, tools: list[dict[str, Any]]
    ) -> list[str]:
        known = {str(t.get("name", "")).strip() for t in tools if t.get("name")}
        if not known:
            return []
        catalog = "\n".join(
            f"- {t.get('name')}: {t.get('description', '')}"
            for t in tools if t.get("name")
        )
        out = self.chat(
            [{"role": "user", "content": (
                f"Choose the tools needed for this task. Reply with "
                f"only the tool names, one per line.\nTask: {task}\n"
                f"Available tools:\n{catalog}"
            )}],
            max_tokens=60,
            temperature=0,
        )
        return [
            name
            for line in out.splitlines()
            if (name := line.strip().strip("*`").strip()) in known
        ]

    def summarize(self, text: str, max_words: int = 80) -> str:
        out = self.chat(
            [{"role": "user", "content": (
                f"Summarize the following in at most {max_words} words, "
                f"in the same language as the text.\n\n{text}"
            )}],
            max_tokens=max_words * 2,
        )
        return out.strip()

    def verify(self, claim: str, evidence: str) -> str:
        out = self.chat(
            [{"role": "user", "content": (
                f"Verdict: supported/partially supported/unsupported/"
                f"insufficient evidence.\nClaim: {claim}\nEvidence: {evidence}"
            )}],
            max_tokens=10,
            temperature=0,
        )
        low = out.strip().strip(".").strip().lower()
        for verdict in (
            "partially supported",
            "insufficient evidence",
            "supported",
            "unsupported",
        ):
            if verdict in low:
                return verdict
        return "insufficient evidence"

    # -- Cleanup ------------------------------------------------------------

    async def cleanup(self) -> None:
        """Gracefully shut down the PTY session."""
        await self._close_session()
        self._initialized = False


__all__ = [
    "FreebuffBridgeCLI",
    "_bridge_config",
]
