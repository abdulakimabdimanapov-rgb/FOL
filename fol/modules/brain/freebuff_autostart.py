"""Freebuff Auto-Start Bridge — launches Freebuff CLI as background process.

When FOL starts with FOL_BRAIN=freebuff_auto, this module:
1. Starts Freebuff CLI as a background subprocess
2. Communicates via stdin/stdout (pipe mode, not PTY)
3. Falls back to the current LLM brain when Freebuff fails
4. Auto-restarts Freebuff on crash (up to FREEBUFF_RESTART_ATTEMPTS)

This is the simplest integration path — no tmux or PTY needed.
Freebuff runs in pipe mode (-p flag) which works without a real TTY.

Configuration (env vars):
    FOL_BRAIN=freebuff_auto       — select this brain
    FREEBUFF_AUTO_START=true      — auto-start on FOL boot
    FREEBUFF_BINARY=freebuff      — binary path
    FREEBUFF_START_TIMEOUT=15     — seconds to wait for CLI ready
    FREEBUFF_RESPONSE_TIMEOUT=300 — seconds to wait for a response
    FREEBUFF_RESTART_ATTEMPTS=2   — max restart attempts on crash
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any, AsyncIterator, Optional

from modules.llm.brain import (
    BRAIN_INTENT_LABELS,
    BrainError,
    BrainInterface,
    BrainConfigurationError,
)

logger = logging.getLogger(__name__)


def _config() -> dict[str, str]:
    """Read auto-start configuration from environment."""
    return {
        "binary": (os.environ.get("FREEBUFF_BINARY") or "freebuff").strip(),
        "auto_start": (os.environ.get("FREEBUFF_AUTO_START") or "true").strip().lower(),
        "start_timeout": (os.environ.get("FREEBUFF_START_TIMEOUT") or "15").strip(),
        "response_timeout": (os.environ.get("FREEBUFF_RESPONSE_TIMEOUT") or "300").strip(),
        "restart_attempts": (os.environ.get("FREEBUFF_RESTART_ATTEMPTS") or "2").strip(),
    }


class FreebuffAutoStartBridge(BrainInterface):
    """Brain backend that auto-starts Freebuff CLI in background.

    Uses pipe mode (-p) to communicate without a real TTY.
    Falls back to CurrentLLMAdapter when Freebuff is unavailable.
    """

    name = "freebuff_auto"

    def __init__(self) -> None:
        self._cfg = _config()
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._available: Optional[bool] = None
        self._restart_count = 0
        self._max_restarts = int(self._cfg["restart_attempts"])
        self._response_timeout = float(self._cfg["response_timeout"])
        self._start_timeout = float(self._cfg["start_timeout"])
        self._fallback: Optional[BrainInterface] = None
        self._started_at: float = 0

    @property
    def available(self) -> bool:
        """True if Freebuff binary exists and can be started."""
        if self._available is not None:
            return self._available

        binary = self._cfg["binary"]
        if binary in ("freebuff",):
            # Check if binary is on PATH
            self._available = shutil.which(binary) is not None
        else:
            self._available = os.path.isfile(binary) and os.access(binary, os.X_OK)

        if not self._available:
            logger.warning(
                "Freebuff auto-start unavailable: binary '%s' not found on PATH",
                binary,
            )
        return self._available

    def _get_fallback(self) -> BrainInterface:
        """Get or create the fallback brain (current LLM)."""
        if self._fallback is None:
            from modules.llm.brain import CurrentLLMAdapter
            self._fallback = CurrentLLMAdapter()
        return self._fallback

    def _start_process(self) -> bool:
        """Start Freebuff CLI as a background subprocess in pipe mode."""
        binary = self._cfg["binary"]
        cmd = [binary, "-p"]  # -p = pipe mode (no TTY needed)

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._started_at = time.time()
            logger.info(
                "Freebuff started (pid=%d, timeout=%ds)",
                self._process.pid, self._start_timeout,
            )
            return True
        except FileNotFoundError:
            logger.error("Freebuff binary not found: %s", binary)
            return False
        except Exception as exc:
            logger.error("Failed to start Freebuff: %s", exc)
            return False

    def _is_process_alive(self) -> bool:
        """Check if the Freebuff process is still running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def _send_and_receive(self, message: str) -> str:
        """Send a message to Freebuff and read the response.

        Uses pipe mode: writes to stdin, reads from stdout until timeout.
        """
        with self._lock:
            if not self._is_process_alive():
                if not self._start_process():
                    return ""

            if self._process is None or self._process.stdin is None or self._process.stdout is None:
                return ""

            try:
                # Send message
                self._process.stdin.write(message + "\n")
                self._process.stdin.flush()

                # Read response with timeout
                import select
                response_lines = []
                deadline = time.time() + self._response_timeout

                while time.time() < deadline:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break

                    # Use select for non-blocking read with timeout
                    ready, _, _ = select.select(
                        [self._process.stdout], [], [], min(remaining, 1.0)
                    )
                    if ready:
                        line = self._process.stdout.readline()
                        if not line:
                            # EOF — process ended
                            break
                        line = line.rstrip("\n\r")
                        # Skip empty lines and TUI artifacts
                        if line.strip():
                            response_lines.append(line)
                    else:
                        # No data for 1 second — check if we have enough
                        if response_lines:
                            # Had some response, silence means done
                            break

                return "\n".join(response_lines)

            except Exception as exc:
                logger.error("Freebuff communication error: %s", exc)
                return ""

    def _restart_if_needed(self) -> bool:
        """Restart Freebuff if it crashed, up to max attempts."""
        if self._restart_count >= self._max_restarts:
            logger.warning(
                "Freebuff restart limit reached (%d/%d)",
                self._restart_count, self._max_restarts,
            )
            return False

        self._restart_count += 1
        logger.info(
            "Restarting Freebuff (attempt %d/%d)",
            self._restart_count, self._max_restarts,
        )
        self._stop_process()
        return self._start_process()

    def _stop_process(self) -> None:
        """Stop the Freebuff process."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    # -- BrainInterface implementation -------------------------------------

    def status(self) -> dict[str, Any]:
        alive = self._is_process_alive()
        return {
            "backend": self.name,
            "available": self.available,
            "process_alive": alive,
            "pid": self._process.pid if self._process else None,
            "restart_count": self._restart_count,
            "uptime_s": round(time.time() - self._started_at, 1) if self._started_at else 0,
            "fallback": self._get_fallback().name if self._fallback else "current",
        }

    def model_chain(self) -> list[str]:
        return ["freebuff_cli"] + self._get_fallback().model_chain()

    def available_providers(self) -> list[str]:
        return ["freebuff_cli"] + self._get_fallback().available_providers()

    def test_connection(self) -> str:
        if not self.available:
            return f"❌ Freebuff binary not found: {self._cfg['binary']}"
        result = self._send_and_receive("Reply with just the word OK")
        if result:
            return f"✅ Freebuff responds: {result[:60]}"
        return f"⚠️ Freebuff no response, fallback to {self._get_fallback().name}"

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        # Extract the last user message
        last_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_msg = msg.get("content", "")
                break

        if not last_msg:
            return self._get_fallback().chat(
                messages, system=system, tools=tools,
                max_tokens=max_tokens, temperature=temperature,
            )

        # Try Freebuff
        response = self._send_and_receive(last_msg)
        if response:
            return response

        # Freebuff failed — restart if possible, then fallback
        if self._restart_if_needed():
            response = self._send_and_receive(last_msg)
            if response:
                return response

        logger.warning("Freebuff failed, falling back to %s", self._get_fallback().name)
        return self._get_fallback().chat(
            messages, system=system, tools=tools,
            max_tokens=max_tokens, temperature=temperature,
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # Try Freebuff first via chat(), then wrap result as stream events.
        # Freebuff pipe mode doesn't support true streaming, so we collect
        # the full response and yield it as a single token event.
        try:
            response = self.chat(
                messages, system=system, tools=tools,
                max_tokens=max_tokens,
            )
            if response:
                yield {"type": "token", "text": response}
                yield {"type": "done", "stop_reason": "end_turn"}
                return
        except Exception as exc:
            logger.warning("Freebuff stream via chat failed: %s — falling back", exc)

        # Freebuff failed — fall back to the current LLM brain
        async for event in self._get_fallback().chat_stream(
            messages, system=system, tools=tools, max_tokens=max_tokens,
        ):
            yield event

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        try:
            text = self.chat(
                messages, system=system, tools=tools,
                max_tokens=max_tokens, temperature=temperature,
            )
            return {"content": text, "tool_calls": [], "stop_reason": "end_turn"}
        except Exception as exc:
            logger.error("Freebuff auto-start acomplete failed: %s", exc)
            return await self._get_fallback().acomplete(
                messages, system=system, tools=tools,
                max_tokens=max_tokens, temperature=temperature,
            )

    def classify(self, text: str) -> str:
        try:
            return self._get_fallback().classify(text)
        except Exception:
            return "other"

    def plan(self, task: str, context: str = "") -> list[str]:
        return self._get_fallback().plan(task, context=context)

    def select_tools(self, task: str, tools: list[dict[str, Any]]) -> list[str]:
        return self._get_fallback().select_tools(task, tools)

    def summarize(self, text: str, max_words: int = 80) -> str:
        return self._get_fallback().summarize(text, max_words=max_words)

    def verify(self, claim: str, evidence: str) -> str:
        return self._get_fallback().verify(claim, evidence)

    async def cleanup(self) -> None:
        """Stop Freebuff process on shutdown."""
        self._stop_process()


__all__ = ["FreebuffAutoStartBridge"]
