"""Brain modules — Freebuff integration and management.

Three integration paths:

1. **Freebuff via OpenRouter** (model provider):
   ``FreebuffBrainAdapter`` routes reasoning through OpenRouter to Freebuff's
   models (DeepSeek V4 Flash, MiMo 2.5). Legitimate API access.

2. **Freebuff CLI via tmux** (recommended local brain):
   ``FreebuffTmuxBridge`` runs Freebuff inside a persistent tmux session.
   Uses ``tmux capture-pane`` for reliable TUI output parsing.

3. **Freebuff CLI via PTY** (deprecated):
   ``FreebuffBridgeCLI`` launches the real Freebuff CLI in a persistent
   pseudo-terminal session. DEPRECATED — broken for React-based TUIs.

Fallback chain:
  Freebuff tmux → Current (LiteLLM) → API providers
"""

from modules.brain.freebuff_adapter import FreebuffBrainAdapter
from modules.brain.freebuff_process import FreebuffProcessManager, BrainProcessState, BrainProcessStatus
from modules.brain.startup import BrainStartupManager
from modules.brain.freebuff_bridge import FreebuffBridgeCLI
from modules.brain.freebuff_session import FreebuffSession, SessionState, SessionConfig
from modules.brain.freebuff_parser import (
    strip_ansi, clean_terminal_output, detect_ready,
    detect_response_complete, extract_response,
)
from modules.brain.freebuff_tmux_bridge import FreebuffTmuxBridge
from modules.brain.freebuff_tmux_session import FreebuffTmuxSession, TmuxSessionState, TmuxConfig, CompletionState
from modules.brain.freebuff_tmux_parser import (
    strip_ansi as strip_ansi_tmux,
    clean_capture,
    detect_ready as detect_ready_tmux,
    detect_response_complete as detect_response_complete_tmux,
    extract_response as extract_response_tmux,
)
from modules.brain.session_keepalive import (
    SessionKeepalive,
    get_keepalive,
    start_keepalive,
    stop_keepalive,
)

__all__ = [
    "FreebuffBrainAdapter",
    "FreebuffProcessManager",
    "BrainProcessState",
    "BrainProcessStatus",
    "BrainStartupManager",
    "FreebuffBridgeCLI",
    "FreebuffSession",
    "SessionState",
    "SessionConfig",
    "FreebuffTmuxBridge",
    "FreebuffTmuxSession",
    "TmuxSessionState",
    "TmuxConfig",
    "CompletionState",
    "SessionKeepalive",
    "get_keepalive",
    "start_keepalive",
    "stop_keepalive",
]
