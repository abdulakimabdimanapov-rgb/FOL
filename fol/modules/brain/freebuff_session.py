"""Freebuff PTY Session — manages a persistent pseudo-terminal session.

The session wraps a Freebuff CLI process running in a real PTY (pseudo-terminal).
Freebuff is a TUI application that requires a real TTY — plain pipes won't work
because the CLI checks isTTY and enters alternate screen / raw mode only when it
detects a terminal.

Architecture:
  pty.openpty() → (master_fd, slave_fd)
      slave_fd → stdin/stdout/stderr of the child process
      master_fd → read/write from FOL (via background thread + asyncio bridge)

The session does NOT parse output — that's the parser's job.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import select
import signal
import struct
import termios
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from modules.brain.freebuff_parser import (
    clean_terminal_output,
    detect_ready,
    detect_response_complete,
    extract_response,
)

logger = logging.getLogger(__name__)

# Default terminal size for the PTY
_DEFAULT_COLS = 120
_DEFAULT_ROWS = 40


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

class SessionState(Enum):
    """PTY session lifecycle states."""
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    THINKING = "thinking"
    RESPONDING = "responding"
    BUSY = "busy"
    ERROR = "error"
    CLOSED = "closed"


@dataclass
class PTYInfo:
    """Persistent PTY session metadata."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    pid: int = 0
    master_fd: int = -1
    cwd: str = ""
    state: SessionState = SessionState.CREATED
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    error_message: Optional[str] = None
    owned_process: bool = True  # Did FOL start this process?


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class SessionConfig:
    """Configuration for a PTY session."""
    binary: str = "freebuff"
    cwd: str = ""
    start_timeout: float = 15.0       # seconds to wait for CLI ready
    response_timeout: float = 300.0   # seconds to wait for a response
    settle_ms: int = 1500             # ms of silence → response complete
    cols: int = _DEFAULT_COLS
    rows: int = _DEFAULT_ROWS
    env: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# PTY Session (real pseudo-terminal)
# ---------------------------------------------------------------------------

class FreebuffSession:
    """Manages a persistent PTY session with the Freebuff CLI.

    Uses a real pseudo-terminal (pty.openpty) so the Freebuff TUI works
    correctly with alternate screen, raw mode, and mouse tracking.

    Lifecycle:
      1. create() — fork + exec freebuff in a PTY
      2. wait_ready() — wait for TUI to be ready
      3. send_message(text) — send user input
      4. read_response() — read until response complete
      5. close() — graceful shutdown
    """

    def __init__(self, config: SessionConfig) -> None:
        self._config = config
        self._info = PTYInfo(cwd=config.cwd)
        self._master_fd: int = -1
        self._pid: int = 0
        self._read_buffer: bytearray = bytearray()
        self._lock = asyncio.Lock()
        self._reader_thread: Optional[Any] = None
        self._reader_running = False
        self._state_callbacks: list[Callable[[SessionState], Any]] = []
        self._process_exited = False

    @property
    def state(self) -> SessionState:
        return self._info.state

    @property
    def session_id(self) -> str:
        return self._info.session_id

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def is_alive(self) -> bool:
        return self._info.state in (
            SessionState.READY,
            SessionState.THINKING,
            SessionState.RESPONDING,
            SessionState.BUSY,
        )

    def on_state_change(self, callback: Callable[[SessionState], Any]) -> None:
        """Register a state change callback."""
        self._state_callbacks.append(callback)

    def _set_state(self, state: SessionState, error: Optional[str] = None) -> None:
        """Update state and notify callbacks."""
        old = self._info.state
        self._info.state = state
        self._info.last_activity = time.time()
        if error:
            self._info.error_message = error
        if old != state:
            logger.info("Session %s: %s -> %s", self._info.session_id, old.value, state.value)
            for cb in self._state_callbacks:
                try:
                    cb(state)
                except Exception as exc:
                    logger.debug("State callback error: %s", exc)

    # -- Lifecycle ----------------------------------------------------------

    async def create(self) -> bool:
        """Create the PTY and spawn the Freebuff CLI process.

        Uses pty.openpty() to create a real pseudo-terminal so the TUI
        works correctly with alternate screen, mouse modes, etc.

        Returns True if the process started successfully.
        """
        async with self._lock:
            if self._info.state not in (SessionState.CREATED, SessionState.CLOSED, SessionState.ERROR):
                logger.warning("Session already in state %s", self._info.state.value)
                return False

            self._set_state(SessionState.STARTING)

            try:
                # Create real PTY
                master_fd, slave_fd = pty.openpty()
                self._master_fd = master_fd

                # Set terminal size
                winsize = struct.pack("HHHH", self._config.rows, self._config.cols, 0, 0)
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

                # Set master to non-blocking
                flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
                fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                # Build command
                cmd = self._build_command()
                cwd = self._config.cwd or str(Path.cwd())
                self._info.cwd = cwd

                # Build environment
                env = os.environ.copy()
                env.update(self._config.env)
                env["TERM"] = env.get("TERM", "xterm-256color")
                env["COLUMNS"] = str(self._config.cols)
                env["LINES"] = str(self._config.rows)

                # Fork and exec in child process with PTY
                pid = os.fork()
                if pid == 0:
                    # Child process
                    try:
                        os.close(master_fd)
                        os.setsid()

                        # Make slave the controlling terminal
                        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

                        # Redirect stdin/stdout/stderr to slave
                        os.dup2(slave_fd, 0)
                        os.dup2(slave_fd, 1)
                        os.dup2(slave_fd, 2)
                        if slave_fd > 2:
                            os.close(slave_fd)

                        # Set working directory
                        os.chdir(cwd)

                        # Set environment
                        for key, val in env.items():
                            os.environ[key] = val

                        # Exec freebuff
                        os.execvp(cmd[0], cmd)
                    except Exception as exc:
                        os.write(2, f"Child exec failed: {exc}\n".encode())
                        os._exit(1)
                else:
                    # Parent process
                    os.close(slave_fd)
                    self._pid = pid
                    self._info.pid = pid
                    self._info.owned_process = True

                    logger.info(
                        "Freebuff PTY started: pid=%d, master_fd=%d, cwd=%s, cmd=%s",
                        pid, master_fd, cwd, cmd,
                    )

                    # Start background reader thread
                    self._reader_running = True
                    self._reader_thread = asyncio.get_event_loop().run_in_executor(
                        None, self._read_thread
                    )

                    return True

            except OSError as exc:
                self._set_state(SessionState.ERROR, f"PTY creation failed: {exc}")
                logger.error("Failed to create PTY: %s", exc)
                return False
            except Exception as exc:
                self._set_state(SessionState.ERROR, str(exc))
                logger.error("Failed to start session: %s", exc)
                return False

    async def wait_ready(self, timeout: Optional[float] = None) -> bool:
        """Wait for the Freebuff TUI to be ready for input.

        Strategy: wait for initial output to settle (no new data for settle_ms),
        then check if the output suggests the TUI is ready.

        Returns True if ready within timeout.
        """
        timeout = timeout or self._config.start_timeout
        start = time.time()
        settle_ms = self._config.settle_ms

        logger.info("Waiting for Freebuff ready (timeout=%.1fs)...", timeout)

        while (time.time() - start) < timeout:
            await asyncio.sleep(0.5)

            if self._info.state == SessionState.ERROR:
                return False

            if self._info.state == SessionState.READY:
                return True

            # Check if process exited
            if self._process_exited:
                self._set_state(SessionState.ERROR, "Process exited during startup")
                return False

            # Check if we have output that suggests readiness
            raw = self._get_raw_output()
            if raw:
                # Wait for output to settle
                await asyncio.sleep(settle_ms / 1000.0)
                raw_after = self._get_raw_output()
                if raw_after and len(raw_after) == len(raw):
                    # Output settled
                    if detect_ready(raw_after):
                        self._set_state(SessionState.READY)
                        logger.info("Freebuff ready (after %.1fs)", time.time() - start)
                        return True

        # Timeout — mark as ready anyway (the TUI might be up but our
        # detection is imperfect). The real test is sending a message.
        logger.warning("Freebuff ready timeout (%.1fs) — proceeding anyway", timeout)
        self._set_state(SessionState.READY)
        return True

    async def send_message(self, text: str) -> bool:
        """Send a user message to the Freebuff CLI.

        Writes the message to the PTY master fd followed by Enter.
        Returns True if sent successfully.
        """
        if not self.is_alive:
            logger.error("Cannot send message: session not alive (state=%s)", self._info.state.value)
            return False

        if not text or not text.strip():
            return False

        async with self._lock:
            try:
                self._set_state(SessionState.THINKING)
                self._read_buffer.clear()

                # Write message + Enter to PTY master
                data = (text.strip() + "\n").encode("utf-8")
                os.write(self._master_fd, data)

                self._info.last_activity = time.time()
                logger.info("Message sent to Freebuff (len=%d)", len(text))
                return True

            except OSError as exc:
                self._set_state(SessionState.ERROR, f"Send failed: {exc}")
                logger.error("Failed to send message: %s", exc)
                return False

    async def read_response(
        self,
        timeout: Optional[float] = None,
        input_text: str = "",
    ) -> str:
        """Read and return the assistant's response.

        Waits until the output has settled (no new data for settle_ms)
        and the response appears complete.

        Returns the clean response text.
        """
        timeout = timeout or self._config.response_timeout
        start = time.time()
        settle_ms = self._config.settle_ms
        last_data_time = time.time()
        last_len = 0

        while (time.time() - start) < timeout:
            await asyncio.sleep(0.3)

            if self._info.state == SessionState.ERROR:
                break

            if self._process_exited:
                break

            raw = self._get_raw_output()
            current_len = len(raw)

            if current_len > last_len:
                last_data_time = time.time()
                last_len = current_len
                if self._info.state == SessionState.THINKING:
                    self._set_state(SessionState.RESPONDING)

            # Check if output has settled
            silence_ms = (time.time() - last_data_time) * 1000
            if silence_ms >= settle_ms and current_len > 0:
                if detect_response_complete(raw):
                    self._set_state(SessionState.READY)
                    response = extract_response(raw, input_text=input_text)
                    logger.info(
                        "Response received (len=%d, time=%.1fs)",
                        len(response), time.time() - start,
                    )
                    return response

        # Timeout
        raw = self._get_raw_output()
        response = extract_response(raw, input_text=input_text)
        if response:
            logger.warning("Response timeout but got partial response (len=%d)", len(response))
            self._set_state(SessionState.READY)
            return response

        self._set_state(SessionState.ERROR, "Response timeout")
        return ""

    async def read_response_streaming(
        self,
        timeout: Optional[float] = None,
        input_text: str = "",
    ):
        """Streaming version of read_response — yields chunks as they arrive.

        Yields dicts: {"type": "chunk", "text": str} or
                      {"type": "done", "text": str} or
                      {"type": "error", "message": str}
        """
        timeout = timeout or self._config.response_timeout
        start = time.time()
        settle_ms = self._config.settle_ms
        last_data_time = time.time()
        last_len = 0
        all_text = ""
        raw = ""

        while (time.time() - start) < timeout:
            await asyncio.sleep(0.3)

            if self._info.state == SessionState.ERROR:
                yield {"type": "error", "message": self._info.error_message or "Session error"}
                return

            if self._process_exited:
                yield {"type": "error", "message": "Process exited"}
                return

            raw = self._get_raw_output()
            current_len = len(raw)

            if current_len > last_len:
                last_data_time = time.time()
                new_text = extract_response(raw, input_text=input_text)
                if new_text and new_text != all_text:
                    delta = new_text[len(all_text):] if new_text.startswith(all_text) else new_text
                    if delta.strip():
                        yield {"type": "chunk", "text": delta}
                    all_text = new_text
                last_len = current_len
                if self._info.state == SessionState.THINKING:
                    self._set_state(SessionState.RESPONDING)

            silence_ms = (time.time() - last_data_time) * 1000
            if silence_ms >= settle_ms and current_len > 0:
                if detect_response_complete(raw):
                    self._set_state(SessionState.READY)
                    final = extract_response(raw, input_text=input_text)
                    yield {"type": "done", "text": final}
                    return

        final = extract_response(raw, input_text=input_text)
        yield {"type": "done", "text": final}

    async def close(self) -> None:
        """Gracefully close the session.

        If FOL owns the process, sends SIGTERM then SIGKILL after timeout.
        Closes the master fd and waits for the child to exit.
        """
        async with self._lock:
            if self._info.state == SessionState.CLOSED:
                return

            self._set_state(SessionState.CLOSED)
            self._reader_running = False

            if self._pid > 0 and self._info.owned_process:
                try:
                    os.kill(self._pid, signal.SIGTERM)
                    # Wait briefly for graceful exit
                    for _ in range(50):
                        try:
                            pid, status = os.waitpid(self._pid, os.WNOHANG)
                            if pid:
                                break
                        except ChildProcessError:
                            break
                        await asyncio.sleep(0.1)
                    else:
                        # Force kill
                        try:
                            os.kill(self._pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                except ProcessLookupError:
                    pass
                except Exception as exc:
                    logger.debug("Error closing process: %s", exc)

            # Close master fd
            if self._master_fd >= 0:
                try:
                    os.close(self._master_fd)
                except OSError:
                    pass
                self._master_fd = -1

            logger.info("Session %s closed", self._info.session_id)

    # -- Internal -----------------------------------------------------------

    def _build_command(self) -> list[str]:
        """Build the command to launch Freebuff CLI."""
        cmd = [self._config.binary]
        if self._config.cwd:
            cmd.extend(["--cwd", self._config.cwd])
        return cmd

    def _get_raw_output(self) -> str:
        """Get accumulated raw output as string."""
        try:
            return self._read_buffer.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def _read_thread(self) -> None:
        """Background thread that reads from the PTY master fd.

        Runs in a separate thread because PTY reads are blocking.
        Uses select() with timeout to allow periodic checks for shutdown.
        """
        while self._reader_running:
            try:
                # Use select with timeout to allow shutdown checks
                rlist, _, _ = select.select([self._master_fd], [], [], 0.5)
                if not rlist:
                    continue

                try:
                    data = os.read(self._master_fd, 4096)
                except OSError:
                    # Master fd closed or error
                    break

                if not data:
                    # EOF
                    break

                self._read_buffer.extend(data)
                self._info.last_activity = time.time()

            except Exception as exc:
                if self._reader_running:
                    logger.error("Read thread error: %s", exc)
                break

        # Check if process exited
        if self._pid > 0:
            try:
                pid, status = os.waitpid(self._pid, os.WNOHANG)
                if pid:
                    self._process_exited = True
                    exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                    logger.info("Process %d exited (code=%d)", pid, exit_code)
                    if self._info.state != SessionState.CLOSED:
                        self._set_state(SessionState.ERROR, f"Process exited: {exit_code}")
            except ChildProcessError:
                pass

        logger.debug("Read thread finished")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_session(
    binary: str = "freebuff",
    cwd: str = "",
    start_timeout: float = 15.0,
    response_timeout: float = 300.0,
    settle_ms: int = 1500,
) -> FreebuffSession:
    """Create a new FreebuffSession with the given configuration."""
    config = SessionConfig(
        binary=binary,
        cwd=cwd,
        start_timeout=start_timeout,
        response_timeout=response_timeout,
        settle_ms=settle_ms,
    )
    return FreebuffSession(config)


__all__ = [
    "FreebuffSession",
    "SessionState",
    "SessionConfig",
    "PTYInfo",
    "create_session",
]
