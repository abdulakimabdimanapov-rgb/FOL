"""Freebuff Tmux Bridge — BrainInterface backed by Freebuff CLI via tmux.

Architecture:
    FOL
     ↓
    FreebuffTmuxBridge (this module — BrainInterface)
     ↓
    FreebuffTmuxSession (tmux session management)
     ↓
    tmux send-keys / capture-pane
     ↓
    Freebuff TUI (inside tmux)
     ↓
    Response
     ↓
    FreebuffTmuxParser (ANSI/TUI cleanup)
     ↓
    FOL Core

Message flow:
    send_message() → bracketed paste → tmux → Freebuff
    capture_pane() → parser → clean response → FOL

Concurrent request handling:
    An asyncio.Queue serializes requests. Only one message is processed
    at a time. If the bridge is busy, the request is queued.

Configuration (env vars):
    FOL_BRAIN=freebuff_tmux       — select this brain
    FREEBUFF_BINARY=freebuff      — binary name/path (default: "freebuff")
    FREEBUFF_CWD=<project>        — working directory
    FREEBUFF_TMUX_SESSION=fol-freebuff — tmux session name
    FREEBUFF_AUTO_START=true      — auto-start on FOL boot
    FREEBUFF_START_TIMEOUT=15     — seconds to wait for CLI ready
    FREEBUFF_RESPONSE_TIMEOUT=300 — seconds to wait for a response
    FREEBUFF_SETTLE_MS=1500       — ms of silence = response complete
    FREEBUFF_RESTART_ATTEMPTS=2   — max restart attempts on crash

Safety:
    - Freebuff does NOT get direct access to system tools
    - All tool calls go through FOL's ToolRegistry → RiskScorer → ConfirmationGate
    - API keys and secrets are never logged
    - The bridge only manages tmux I/O — no fake HTTP APIs
"""

from __future__ import annotations

import asyncio
import concurrent.futures
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
from modules.brain.freebuff_tmux_session import (
    CompletionState,
    FreebuffTmuxSession,
    TmuxConfig,
    TmuxSessionState,
    create_tmux_session,
    tmux_available,
    tmux_config_from_env,
)
from modules.brain.session_keepalive import SessionKeepalive

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FreebuffTmuxBridge — BrainInterface via tmux
# ---------------------------------------------------------------------------

class FreebuffTmuxBridge(BrainInterface):
    """Brain backend backed by Freebuff CLI running in a persistent tmux session.

    This is the PRIMARY brain for FOL. It:
      1. Creates/detects a tmux session with Freebuff running
      2. Sends user messages via tmux send-keys (bracketed paste)
      3. Reads responses via tmux capture-pane
      4. Cleans ANSI/TUI artifacts from captured output
      5. Returns clean text through the BrainInterface contract

    The session is persistent — one Freebuff process serves all requests
    for the lifetime of FOL. This preserves Freebuff's conversation context.

    Fallback: if the tmux session fails, the BrainRouter falls back to
    CurrentLLMAdapter (API providers).

    Concurrent request handling:
        An asyncio.Queue serializes requests. Only one message is processed
        at a time. If the bridge is busy, the second request waits in queue.

    Configuration:
        FOL_BRAIN=freebuff_tmux     — select this brain
        FREEBUFF_BINARY=freebuff    — binary name
        FREEBUFF_CWD=<project>      — working directory
        FREEBUFF_TMUX_SESSION=name  — tmux session name
    """

    name = "freebuff_tmux"

    def __init__(self) -> None:
        self._config: TmuxConfig = tmux_config_from_env()
        self._session: Optional[FreebuffTmuxSession] = None
        self._initialized = False
        self._init_error: Optional[str] = None
        self._restart_count = 0
        self._max_restarts = self._config.max_restarts
        self._request_count = 0
        self._total_latency: float = 0.0
        self._keepalive: Optional[SessionKeepalive] = None
        # Request serialization
        self._request_lock = asyncio.Lock()
        self._busy = False

    @property
    def available(self) -> bool:
        """True when tmux is installed and Freebuff binary exists.

        The tmux session is created lazily on first use (ensure_session).
        This allows get_brain() to succeed at startup — the session is
        established on the first chat_stream() call.
        """
        avail = tmux_available() and bool(shutil.which(self._config.binary))
        logger.info("[FreebuffBridge] available=%s", avail)
        return avail

    @property
    def is_busy(self) -> bool:
        """True if the bridge is processing a request."""
        return self._busy

    def _check_binary(self) -> bool:
        """Check if the Freebuff binary is available."""
        return bool(shutil.which(self._config.binary))

    def status(self) -> dict[str, Any]:
        """Return current status (never contains secrets)."""
        session_status = self._session.status() if self._session else {}
        keepalive_status = (
            self._keepalive.health_summary if self._keepalive else {}
        )
        return {
            "backend": self.name,
            "available": self.available,
            "busy": self._busy,
            "tmux_available": tmux_available(),
            "binary_available": self._check_binary(),
            "session": session_status,
            "keepalive": keepalive_status,
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
        return [f"freebuff_tmux/{self._config.binary}"]

    def available_providers(self) -> list[str]:
        if not self.available:
            return []
        return ["freebuff_tmux"]

    def test_connection(self) -> str:
        """Test if the tmux session and Freebuff are reachable."""
        if not tmux_available():
            return "❌ tmux not installed. Install: brew install tmux"
        if not self._check_binary():
            return f"❌ Freebuff binary not found ({self._config.binary})"
        if self._session and self._session.is_alive:
            state = self._session.completion_state.value
            return f"✅ Freebuff tmux session active ({self._config.session_name}, state={state})"
        return "⚠️ tmux and Freebuff available but session not active"

    # -- Session management --------------------------------------------------

    async def ensure_session(self) -> FreebuffTmuxSession:
        """Ensure a tmux session with Freebuff is running.

        Returns the active session.
        Raises BrainUnavailableError if session cannot be created.
        """
        logger.info("[FreebuffBridge] ensure_session...")
        if self._session and self._session.is_alive:
            return self._session

        if self._session and self._session.state == TmuxSessionState.ERROR:
            # Attempt restart
            if self._restart_count < self._max_restarts:
                self._restart_count += 1
                logger.info(
                    "Restarting Freebuff tmux session (attempt %d/%d)",
                    self._restart_count, self._max_restarts,
                )
                if await self._session.restart():
                    return self._session
            raise BrainUnavailableError(
                f"Freebuff tmux session crashed {self._restart_count} times. "
                f"Max restart attempts ({self._max_restarts}) exceeded."
            )

        # Create new session
        self._session = create_tmux_session(self._config)

        if not await self._session.check_or_create():
            self._init_error = self._session._info.error_message or "Session creation failed"
            raise BrainUnavailableError(
                f"Failed to start Freebuff tmux session: {self._init_error}"
            )

        if not await self._session.wait_ready():
            self._init_error = self._session._info.error_message or "Ready timeout"
            raise BrainUnavailableError(
                f"Freebuff not ready in tmux: {self._init_error}"
            )

        self._initialized = True
        self._init_error = None
        logger.info("Freebuff tmux session ready (%s)", self._config.session_name)

        # Start keepalive watchdog after session is ready
        await self._start_keepalive()

        return self._session

    async def _close_session(self) -> None:
        """Close the current session."""
        await self._stop_keepalive()
        if self._session:
            await self._session.close()
            self._session = None

    # -- Prompt construction -------------------------------------------------

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
        """Send a message to Freebuff via tmux and receive the response.

        This is the core communication method. It:
        1. Ensures a tmux session is active
        2. Acquires the request lock (serializes concurrent calls)
        3. Sends the message via tmux send-keys (bracketed paste)
        4. Captures the response via tmux capture-pane
        5. Returns the clean response text

        If the session is busy (another request in flight), this method
        will wait for the lock rather than rejecting.
        """
        async with self._request_lock:
            start = time.time()
            self._busy = True
            try:
                session = await self.ensure_session()

                # Wait for session to be idle before sending
                if session.is_busy:
                    logger.debug("Session busy, waiting for IDLE state...")
                    for _ in range(600):  # 300s max wait
                        if session.is_idle:
                            break
                        await asyncio.sleep(0.5)
                    else:
                        raise BrainError("Session stuck in BUSY state for 300s")

                # Send message
                logger.info("[FreebuffBridge] send_message started")
                if not await session.send_message(text):
                    raise BrainError("Failed to send message to Freebuff via tmux")
                logger.info("[FreebuffBridge] send_message completed")

                # Read response
                logger.info("[FreebuffBridge] read_response started")
                response = await session.read_response(
                    timeout=timeout,
                    input_text=text,
                )

                elapsed = time.time() - start
                self._request_count += 1
                self._total_latency += elapsed
                logger.info("[FreebuffBridge] read_response result length=%d", len(response))

                if not response:
                    raise BrainError("Freebuff returned empty response via tmux")

                return response

            except BrainUnavailableError:
                raise
            except BrainError:
                raise
            except Exception as exc:
                raise BrainError(f"Freebuff tmux bridge error: {exc}") from exc
            finally:
                self._busy = False

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
        """Complete a conversation via Freebuff tmux session."""
        prompt = self._build_prompt(messages, system)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in async context — run in thread
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(
                    asyncio.run,
                    self._send_and_receive(prompt),
                )
                return future.result(
                    timeout=float(self._config.response_timeout)
                )
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
        """Stream completion via Freebuff tmux session.

        Note: Freebuff CLI is a TUI — true streaming is not available.
        We poll tmux capture-pane and yield new text as it appears.
        """
        prompt = self._build_prompt(messages, system)
        try:
            session = await self.ensure_session()
        except BrainUnavailableError as exc:
            logger.warning("[FreebuffBridge] ensure_session unavailable: %s", exc)
            yield {"type": "error", "message": str(exc)}
            return

        async with self._request_lock:
            self._busy = True
            try:
                from modules.brain.freebuff_tmux_session import capture_pane
                from modules.brain.freebuff_tmux_parser import (
                    extract_streaming_chunks,
                    detect_response_complete,
                    detect_error_screen,
                    strip_bracketed_paste,
                    extract_response,
                )

                # Check if Freebuff is currently on an error screen
                raw_initial = capture_pane(self._config.session_name)
                err = detect_error_screen(raw_initial)
                if err:
                    logger.warning("[FreebuffBridge] error screen detected before sending: %s", err)
                    yield {"type": "error", "message": f"Freebuff error: {err}"}
                    return

                logger.info("[FreebuffBridge] send_message started")
                if not await session.send_message(prompt):
                    logger.warning("[FreebuffBridge] send_message failed")
                    yield {"type": "error", "message": "Failed to send message to Freebuff via tmux"}
                    return
                logger.info("[FreebuffBridge] send_message completed")

                logger.info("[FreebuffBridge] read_response started")
                timeout = self._config.response_timeout
                start = time.time()
                previous = capture_pane(self._config.session_name)
                accumulated: set[str] = set()
                emitted_tokens = 0

                while (time.time() - start) < timeout:
                    await asyncio.sleep(0.5)

                    raw = capture_pane(self._config.session_name)
                    if not raw:
                        continue

                    # Check for error screen
                    err = detect_error_screen(raw)
                    if err and emitted_tokens == 0:
                        logger.warning("[FreebuffBridge] error screen detected: %s", err)
                        yield {"type": "error", "message": f"Freebuff error: {err}"}
                        return

                    current = strip_bracketed_paste(raw)
                    if current and current != previous:
                        chunks = extract_streaming_chunks(current, previous)
                        for chunk in chunks:
                            if chunk not in accumulated:
                                accumulated.add(chunk)
                                emitted_tokens += 1
                                logger.info("[FreebuffBridge] emitting token")
                                yield {"type": "token", "text": chunk + "\n"}
                        previous = current

                    if detect_response_complete(current, previous):
                        break

                if emitted_tokens == 0:
                    # Fallback to full extract_response if chunk diff missed it
                    raw = capture_pane(self._config.session_name)
                    resp = extract_response(
                        raw,
                        input_text=prompt,
                        message_sent_at=session._info.last_message_sent_at,
                    )
                    if resp:
                        emitted_tokens += 1
                        logger.info("[FreebuffBridge] read_response result length=%d", len(resp))
                        logger.info("[FreebuffBridge] emitting token")
                        yield {"type": "token", "text": resp}

                logger.info("[FreebuffBridge] read_response result length=%d", emitted_tokens)
                if emitted_tokens == 0:
                    logger.warning("[FreebuffBridge] empty response from Freebuff")
                    yield {"type": "error", "message": "Freebuff returned empty response via tmux"}
                    return

                logger.info("[FreebuffBridge] emitting done")
                yield {"type": "done", "stop_reason": "end_turn"}

            except Exception as exc:
                logger.warning("[FreebuffBridge] error during streaming: %s", exc)
                yield {"type": "error", "message": f"Freebuff tmux bridge error: {exc}"}
            finally:
                self._busy = False

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Async completion via Freebuff tmux session."""
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
        except BrainError:
            return {
                "content": "",
                "tool_calls": [],
                "stop_reason": "error",
            }

    # -- Reasoning capabilities (prompt wrappers) ---------------------------

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

    # -- Keepalive management -----------------------------------------------

    async def _start_keepalive(self) -> None:
        """Start the keepalive watchdog for this session.

        Only one keepalive task runs per bridge instance.
        The restart callback delegates to the bridge's own restart logic.
        """
        if self._keepalive and self._keepalive.is_running:
            logger.debug("Keepalive already running, skipping")
            return

        async def _on_restart() -> None:
            """Restart callback: delegates to bridge's restart logic."""
            if self._session:
                logger.info("Keepalive triggered bridge restart")
                ok = await self._session.restart()
                if ok:
                    self._restart_count += 1
                    logger.info(
                        "Keepalive restart succeeded (total: %d)",
                        self._restart_count,
                    )
                else:
                    logger.error("Keepalive restart failed")

        self._keepalive = SessionKeepalive(
            session_name=self._config.session_name,
            check_interval=10.0,
            max_missed=3,
            restart_callback=_on_restart,
        )
        await self._keepalive.start()

    async def _stop_keepalive(self) -> None:
        """Stop the keepalive watchdog."""
        if self._keepalive:
            await self._keepalive.stop()
            self._keepalive = None

    # -- Cleanup ------------------------------------------------------------

    async def cleanup(self) -> None:
        """Gracefully shut down the tmux session and keepalive."""
        await self._stop_keepalive()
        await self._close_session()
        self._initialized = False
        self._busy = False


__all__ = [
    "FreebuffTmuxBridge",
]
