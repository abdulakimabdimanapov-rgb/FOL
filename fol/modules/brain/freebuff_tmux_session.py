"""Freebuff Tmux Session — manages a persistent tmux session for Freebuff CLI.

Architecture:
    FOL
     ↓
    FreebuffTmuxSession (this module)
     ↓
    tmux new-session -d -s fol-freebuff
     ↓
    tmux send-keys -t fol-freebuff "freebuff" Enter
     ↓
    tmux capture-pane -t fol-freebuff -p
     ↓
    Freebuff TUI runs inside tmux
     ↓
    FOL sends messages via tmux send-keys
     ↓
    FOL reads responses via tmux capture-pane

Key advantages over PTY approach:
    - tmux handles the terminal emulation (alternate screen, cursor positioning)
    - capture-pane returns the RENDERED screen content, not raw escape codes
    - Session survives FOL restarts (tmux keeps running)
    - No need for our own terminal emulator

Completion state machine:
    IDLE → SUBMITTED → WORKING → RESPONDING → COMPLETE
                                                  ↓
                                              IDLE (next message)

Concurrent requests:
    Only one message at a time. A second send_message() while the first
    is still processing will be rejected with state BUSY.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from modules.brain.freebuff_tmux_parser import (
    clean_capture,
    detect_error_screen,
    detect_ready,
    detect_response_complete,
    extract_response,
    strip_bracketed_paste,
)

logger = logging.getLogger(__name__)

# Default terminal size for the tmux pane
_DEFAULT_COLS = 120
_DEFAULT_ROWS = 40


# ---------------------------------------------------------------------------
# Completion state machine
# ---------------------------------------------------------------------------

class CompletionState(Enum):
    """State machine for tracking Freebuff response lifecycle.

    IDLE      → session ready, no request in flight
    SUBMITTED → message sent, waiting for Freebuff to start processing
    WORKING   → Freebuff has acknowledged input, actively processing
    RESPONDING→ output is streaming back
    COMPLETE  → response fully received, ready to extract
    BUSY      → another request is in flight, new sends rejected
    ERROR     → unrecoverable error
    """
    IDLE = "idle"
    SUBMITTED = "submitted"
    WORKING = "working"
    RESPONDING = "responding"
    COMPLETE = "complete"
    BUSY = "busy"
    ERROR = "error"


class TmuxSessionState(Enum):
    """Tmux session lifecycle states."""
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    THINKING = "thinking"
    RESPONDING = "responding"
    BUSY = "busy"
    ERROR = "error"
    CLOSED = "closed"


@dataclass
class TmuxInfo:
    """Persistent tmux session metadata."""
    session_name: str = "fol-freebuff"
    pid: int = 0
    state: TmuxSessionState = TmuxSessionState.CREATED
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    owned_process: bool = True  # Did FOL create this session?
    message_count: int = 0
    last_message_sent_at: float = 0.0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TmuxConfig:
    """Configuration for tmux session."""
    session_name: str = "fol-freebuff"
    binary: str = "freebuff"
    cwd: str = ""
    cols: int = _DEFAULT_COLS
    rows: int = _DEFAULT_ROWS
    start_timeout: float = 15.0
    response_timeout: float = 300.0
    settle_ms: int = 1500
    max_restarts: int = 2
    restart_delay: float = 2.0


def tmux_config_from_env() -> TmuxConfig:
    """Read tmux configuration from environment variables."""
    return TmuxConfig(
        session_name=os.environ.get("FREEBUFF_TMUX_SESSION", "fol-freebuff").strip(),
        binary=(os.environ.get("FREEBUFF_BINARY") or "freebuff").strip(),
        cwd=(os.environ.get("FREEBUFF_CWD") or "").strip(),
        cols=int(os.environ.get("FREEBUFF_TMUX_COLS", str(_DEFAULT_COLS))),
        rows=int(os.environ.get("FREEBUFF_TMUX_ROWS", str(_DEFAULT_ROWS))),
        start_timeout=float(os.environ.get("FREEBUFF_START_TIMEOUT", "15")),
        response_timeout=float(os.environ.get("FREEBUFF_RESPONSE_TIMEOUT", "300")),
        settle_ms=int(os.environ.get("FREEBUFF_SETTLE_MS", "1500")),
        max_restarts=int(os.environ.get("FREEBUFF_RESTART_ATTEMPTS", "2")),
        restart_delay=float(os.environ.get("FREEBUFF_RESTART_DELAY", "2")),
    )


# ---------------------------------------------------------------------------
# Tmux helper functions
# ---------------------------------------------------------------------------

def _run_tmux(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a tmux command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["tmux"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        return -1, "", "tmux not found"
    except subprocess.TimeoutExpired:
        return -2, "", "tmux command timed out"
    except Exception as e:
        return -3, "", str(e)


def tmux_available() -> bool:
    """Check if tmux is installed and available."""
    rc, _, _ = _run_tmux(["-V"])
    return rc == 0


def session_exists(name: str) -> bool:
    """Check if a tmux session with the given name exists."""
    rc, _, _ = _run_tmux(["has-session", "-t", name])
    return rc == 0


def capture_pane(name: str, start_line: int = -500) -> str:
    """Capture the visible content of a tmux pane.

    Args:
        name: tmux session name
        start_line: negative offset from bottom (default: last 500 lines)

    Returns:
        The rendered screen content as a string
    """
    rc, stdout, stderr = _run_tmux(
        ["capture-pane", "-t", name, "-p", "-S", str(start_line)],
        timeout=5.0,
    )
    if rc != 0:
        logger.warning("tmux capture-pane failed: %s", stderr)
        return ""
    return stdout


def send_keys(name: str, text: str, literal: bool = False) -> bool:
    """Send text to a tmux session.

    Always uses bracketed paste for safety — this prevents Freebuff from
    interpreting special characters in user input as TUI shortcuts.

    For multi-line text or text containing special characters,
    uses bracketed paste (send-keys -l + Enter).

    Args:
        name: tmux session name
        text: text to send
        literal: if True, send literally (no key interpretation)

    Returns:
        True if sent successfully
    """
    if not text:
        return False

    # Always use bracketed paste — it's the safest approach for TUI input
    # Bracketed paste: ESC[200~ ... ESC[201~
    # This tells the TUI "this is pasted text, don't interpret special keys"
    needs_paste = (
        literal
        or "\n" in text
        or len(text) > 80
        or any(c in text for c in "\t\r\x1b")
    )

    if needs_paste:
        # Send start bracket
        rc1, _, _ = _run_tmux(
            ["send-keys", "-t", name, "-l", "\x1b[200~"],
            timeout=5.0,
        )
        # Send the actual text
        rc2, _, _ = _run_tmux(
            ["send-keys", "-t", name, "-l", text],
            timeout=5.0,
        )
        # Send end bracket
        rc3, _, _ = _run_tmux(
            ["send-keys", "-t", name, "-l", "\x1b[201~"],
            timeout=5.0,
        )
        # Send Enter
        rc4, _, _ = _run_tmux(
            ["send-keys", "-t", name, "Enter"],
            timeout=5.0,
        )
        return rc1 == 0 and rc4 == 0
    else:
        # Simple short text: send as literal keys + Enter
        rc, _, _ = _run_tmux(
            ["send-keys", "-t", name, "-l", text],
            timeout=5.0,
        )
        rc2, _, _ = _run_tmux(
            ["send-keys", "-t", name, "Enter"],
            timeout=5.0,
        )
        return rc == 0


def kill_session(name: str) -> bool:
    """Kill a tmux session."""
    rc, _, _ = _run_tmux(["kill-session", "-t", name])
    return rc == 0


def resize_pane(name: str, cols: int, rows: int) -> bool:
    """Resize the tmux pane."""
    rc, _, _ = _run_tmux(
        ["resize-window", "-t", name, "-x", str(cols), "-y", str(rows)]
    )
    return rc == 0


# ---------------------------------------------------------------------------
# FreebuffTmuxSession
# ---------------------------------------------------------------------------

class FreebuffTmuxSession:
    """Manages a persistent tmux session running Freebuff CLI.

    Lifecycle:
    1. check_or_create() — detect existing or create new session
    2. wait_ready() — wait for Freebuff TUI to be ready
    3. send_message() — send user message
    4. read_response() — capture and parse response
    5. close() — kill session (only if we own it)

    Completion state machine:
        IDLE → SUBMITTED → WORKING → RESPONDING → COMPLETE → IDLE

    Concurrent request handling:
        Only one message at a time. If a message is already in flight,
        send_message() returns False (caller should wait or queue).
    """

    def __init__(self, config: TmuxConfig) -> None:
        self._config = config
        self._info = TmuxInfo(session_name=config.session_name)
        self._lock = asyncio.Lock()
        self._previous_capture = ""
        self._completion_state = CompletionState.IDLE
        self._completion_state_changed_at: float = time.time()

    @property
    def is_alive(self) -> bool:
        """True if the tmux session exists and Freebuff is running."""
        return session_exists(self._config.session_name)

    @property
    def state(self) -> TmuxSessionState:
        return self._info.state

    @property
    def completion_state(self) -> CompletionState:
        return self._completion_state

    @property
    def is_idle(self) -> bool:
        """True if session is ready for a new message."""
        return self._completion_state in (
            CompletionState.IDLE,
            CompletionState.COMPLETE,
        )

    @property
    def is_busy(self) -> bool:
        """True if a request is in flight."""
        return self._completion_state in (
            CompletionState.SUBMITTED,
            CompletionState.WORKING,
            CompletionState.RESPONDING,
        )

    # -- State machine -------------------------------------------------------

    def _set_completion_state(self, new_state: CompletionState) -> None:
        """Transition to a new completion state with timestamp."""
        old = self._completion_state
        self._completion_state = new_state
        self._completion_state_changed_at = time.time()
        if old != new_state:
            logger.debug(
                "Completion state: %s → %s",
                old.value, new_state.value,
            )

    # -- Lifecycle -----------------------------------------------------------

    async def check_or_create(self) -> bool:
        """Check for existing session or create a new one.

        Returns True if a session is available (existing or newly created).
        """
        name = self._config.session_name

        # Check if session already exists
        if session_exists(name):
            logger.info("Found existing tmux session: %s", name)
            self._info.owned_process = False  # We didn't create it
            self._info.state = TmuxSessionState.READY
            self._info.pid = self._get_session_pid()
            self._set_completion_state(CompletionState.IDLE)
            return True

        # Create new session
        logger.info("Creating tmux session: %s", name)
        self._info.state = TmuxSessionState.STARTING
        self._info.owned_process = True

        # Create tmux session with specific size
        rc, _, stderr = _run_tmux([
            "new-session", "-d",
            "-s", name,
            "-x", str(self._config.cols),
            "-y", str(self._config.rows),
        ])
        if rc != 0:
            self._info.state = TmuxSessionState.ERROR
            self._info.error_message = f"Failed to create tmux session: {stderr}"
            self._set_completion_state(CompletionState.ERROR)
            logger.error("tmux new-session failed: %s", stderr)
            return False

        # Launch Freebuff inside the session
        cmd = self._config.binary
        if self._config.cwd:
            cmd = f"cd {self._config.cwd} && {cmd}"

        rc, _, stderr = _run_tmux([
            "send-keys", "-t", name, cmd, "Enter",
        ])
        if rc != 0:
            self._info.state = TmuxSessionState.ERROR
            self._info.error_message = f"Failed to launch Freebuff: {stderr}"
            self._set_completion_state(CompletionState.ERROR)
            logger.error("tmux send-keys failed: %s", stderr)
            return False

        self._info.created_at = time.time()
        self._info.last_activity = time.time()
        logger.info("tmux session created, Freebuff launched")
        return True

    async def wait_ready(self, timeout: Optional[float] = None) -> bool:
        """Wait for Freebuff TUI to be ready for input.

        Checks tmux capture-pane output for ready indicators.
        """
        timeout = timeout or self._config.start_timeout
        name = self._config.session_name
        start = time.time()

        logger.info("Waiting for Freebuff ready (timeout=%.1fs)...", timeout)

        while (time.time() - start) < timeout:
            await asyncio.sleep(1.0)

            if not session_exists(name):
                self._info.state = TmuxSessionState.ERROR
                self._info.error_message = "tmux session disappeared"
                self._set_completion_state(CompletionState.ERROR)
                return False

            raw = capture_pane(name)
            if raw:
                err = detect_error_screen(raw)
                if err:
                    self._info.state = TmuxSessionState.ERROR
                    self._info.error_message = f"Freebuff error screen: {err}"
                    self._set_completion_state(CompletionState.ERROR)
                    logger.warning("Freebuff startup detected error screen: %s", err)
                    return False

            if raw and detect_ready(raw):
                self._info.state = TmuxSessionState.READY
                self._previous_capture = raw
                self._set_completion_state(CompletionState.IDLE)
                logger.info("Freebuff ready (after %.1fs)", time.time() - start)
                return True

        # Timeout — check if there is an error screen
        raw = capture_pane(name)
        if raw:
            err = detect_error_screen(raw)
            if err:
                self._info.state = TmuxSessionState.ERROR
                self._info.error_message = f"Freebuff error screen: {err}"
                self._set_completion_state(CompletionState.ERROR)
                logger.warning("Freebuff ready timeout with error screen: %s", err)
                return False
            if detect_ready(raw):
                self._info.state = TmuxSessionState.READY
                self._previous_capture = raw
                self._set_completion_state(CompletionState.IDLE)
                return True

        self._info.state = TmuxSessionState.ERROR
        self._info.error_message = "Freebuff not ready after timeout"
        self._set_completion_state(CompletionState.ERROR)
        return False

    # -- Communication -------------------------------------------------------

    async def send_message(self, text: str) -> bool:
        """Send a user message to Freebuff via tmux.

        Uses bracketed paste for multi-line text.
        Rejects if session is already busy (concurrent request protection).
        """
        if not text or not text.strip():
            return False

        if not self.is_alive:
            logger.error("Cannot send: tmux session not alive")
            self._set_completion_state(CompletionState.ERROR)
            return False

        async with self._lock:
            # Reject concurrent requests
            if self.is_busy:
                logger.warning(
                    "Rejecting send: session busy (state=%s)",
                    self._completion_state.value,
                )
                return False

            self._info.state = TmuxSessionState.THINKING
            self._info.last_message_sent_at = time.time()
            self._info.message_count += 1

            # Take a snapshot before sending (for diffing later)
            self._previous_capture = capture_pane(self._config.session_name)

            # Mark as submitted
            self._set_completion_state(CompletionState.SUBMITTED)

            # Send the message
            sent = send_keys(
                self._config.session_name,
                text.strip(),
                literal=True,
            )

            if sent:
                self._info.last_activity = time.time()
                logger.info("Message sent to Freebuff (len=%d)", len(text))
            else:
                self._info.state = TmuxSessionState.ERROR
                self._info.error_message = "Failed to send message"
                self._set_completion_state(CompletionState.ERROR)

            return sent

    async def read_response(
        self,
        timeout: Optional[float] = None,
        input_text: str = "",
    ) -> str:
        """Read and return the assistant's response.

        Uses the completion state machine to track response lifecycle:
            SUBMITTED → WORKING → RESPONDING → COMPLETE

        Polls tmux capture-pane until:
        1. Output settles (no changes for settle_ms)
        2. Response complete indicator detected
        3. Timeout reached

        Returns:
            Clean response text, or empty string on failure.
        """
        timeout = timeout or self._config.response_timeout
        name = self._config.session_name
        start = time.time()
        settle_ms = self._config.settle_ms
        last_change_time = time.time()
        last_capture = self._previous_capture
        seen_content = False

        while (time.time() - start) < timeout:
            await asyncio.sleep(0.5)

            if not session_exists(name):
                self._set_completion_state(CompletionState.ERROR)
                break

            raw = capture_pane(name)
            if not raw:
                continue

            # Strip bracketed paste markers from raw output
            raw = strip_bracketed_paste(raw)

            # Detect state transitions
            if self._completion_state == CompletionState.SUBMITTED:
                # Freebuff started processing?
                if raw != last_capture:
                    self._set_completion_state(CompletionState.WORKING)
                    self._info.state = TmuxSessionState.RESPONDING

            if self._completion_state == CompletionState.WORKING:
                # Output is streaming — move to RESPONDING
                if raw != last_capture:
                    self._set_completion_state(CompletionState.RESPONDING)
                    seen_content = True

            if self._completion_state == CompletionState.RESPONDING:
                # Still streaming — track changes
                if raw != last_capture:
                    last_change_time = time.time()
                    last_capture = raw

            # Check if output has settled (no changes for settle_ms)
            silence_ms = (time.time() - last_change_time) * 1000
            if silence_ms >= settle_ms and raw:
                if detect_response_complete(raw, self._previous_capture):
                    self._set_completion_state(CompletionState.COMPLETE)
                    self._info.state = TmuxSessionState.READY
                    self._previous_capture = raw
                    response = extract_response(
                        raw,
                        input_text=input_text,
                        message_sent_at=self._info.last_message_sent_at,
                    )
                    logger.info(
                        "Response received (len=%d, time=%.1fs, state=COMPLETE)",
                        len(response), time.time() - start,
                    )
                    return response

        # Timeout — try to extract whatever we have
        raw = capture_pane(name) if session_exists(name) else ""
        if raw:
            raw = strip_bracketed_paste(raw)
        self._previous_capture = raw
        if raw:
            response = extract_response(
                raw,
                input_text=input_text,
                message_sent_at=self._info.last_message_sent_at,
            )
            if response:
                logger.warning(
                    "Response timeout but got partial (len=%d)", len(response),
                )
                self._info.state = TmuxSessionState.READY
                self._set_completion_state(CompletionState.COMPLETE)
                return response

        self._info.state = TmuxSessionState.ERROR
        self._info.error_message = "Response timeout"
        self._set_completion_state(CompletionState.ERROR)
        return ""

    # -- Status & introspection ----------------------------------------------

    def status(self) -> dict:
        """Return session status."""
        return {
            "session_name": self._config.session_name,
            "state": self._info.state.value,
            "completion_state": self._completion_state.value,
            "is_alive": self.is_alive,
            "is_idle": self.is_idle,
            "is_busy": self.is_busy,
            "pid": self._info.pid,
            "message_count": self._info.message_count,
            "owned": self._info.owned_process,
            "error": self._info.error_message,
        }

    def _get_session_pid(self) -> int:
        """Get the PID of the process running in the tmux session."""
        rc, stdout, _ = _run_tmux([
            "display-message", "-p", "-t", self._config.session_name,
            "#{pane_pid}",
        ])
        if rc == 0 and stdout.strip():
            try:
                return int(stdout.strip())
            except ValueError:
                pass
        return 0

    # -- Cleanup -------------------------------------------------------------

    async def close(self) -> None:
        """Close the tmux session.

        Only kills the session if FOL created it (owned_process=True).
        If the user started it manually, leaves it running.
        """
        async with self._lock:
            if self._info.state == TmuxSessionState.CLOSED:
                return

            self._info.state = TmuxSessionState.CLOSED
            self._set_completion_state(CompletionState.ERROR)

            if self._info.owned_process and session_exists(self._config.session_name):
                logger.info("Killing owned tmux session: %s", self._config.session_name)
                kill_session(self._config.session_name)
            elif session_exists(self._config.session_name):
                logger.info("Leaving user-owned tmux session: %s", self._config.session_name)
            else:
                logger.debug("tmux session already gone: %s", self._config.session_name)

    async def restart(self) -> bool:
        """Restart the tmux session (crash recovery)."""
        logger.info("Restarting tmux session: %s", self._config.session_name)

        # Kill existing session if any
        if session_exists(self._config.session_name):
            kill_session(self._config.session_name)
            await asyncio.sleep(self._config.restart_delay)

        # Recreate
        self._info = TmuxInfo(session_name=self._config.session_name)
        self._set_completion_state(CompletionState.IDLE)
        ok = await self.check_or_create()
        if not ok:
            return False

        return await self.wait_ready()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_tmux_session(config: Optional[TmuxConfig] = None) -> FreebuffTmuxSession:
    """Create a new FreebuffTmuxSession with the given configuration."""
    if config is None:
        config = tmux_config_from_env()
    return FreebuffTmuxSession(config)


__all__ = [
    "CompletionState",
    "TmuxSessionState",
    "TmuxInfo",
    "TmuxConfig",
    "FreebuffTmuxSession",
    "tmux_config_from_env",
    "create_tmux_session",
    "tmux_available",
    "session_exists",
    "capture_pane",
    "send_keys",
]
