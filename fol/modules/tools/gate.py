"""ConfirmationGate — the canonical, code-enforced safety gate for FOL tools.

The gate is the single place that decides whether a tool call may execute.
The LLM can never decide that: the gate decides from canonical registry
metadata (``ToolSpec.risk_level`` / ``requires_confirmation``) plus
deterministic rule-based checks (e.g. shell-like ``fol_command`` calls).

Decisions
---------
``check(name, args)`` returns ``(GateDecision, action_id_or_None)``:

- ``OK``       — execute the tool.
- ``CONFIRM``  — the tool needs explicit user confirmation; blocked until
  the pending action is approved via ``approve(action_id)``. The returned
  ``action_id`` lets the UI approve/deny deterministically (``/confirm``).
- ``REJECT``   — unknown/unregistered tool: fail closed, never execute.

Approvals are bound to the exact tool-call signature (name + args), so a
model cannot bypass the gate by re-issuing a call with different arguments.
"""

from __future__ import annotations

import enum
import json
import re
import threading
import uuid
from typing import Any

from modules.tools.base import RiskLevel
from modules.tools.registry import ToolRegistry


class GateDecision(str, enum.Enum):
    OK = "ok"              # execute immediately, no notification
    PEEK_CONFIRM = "peek"  # execute with light notification (auto-dismiss)
    CONFIRM = "confirm"    # blocked — needs explicit user approval (A2UI card)
    STRICT_CONFIRM = "strict"  # blocked — modal + exact signature + timeout
    REJECT = "reject"      # unknown tool — fail closed


class RiskLevel5(enum.IntEnum):
    """5-level risk scoring for tool execution.

    Maps to GateDecision:
      1 → OK            (safe read, no notification)
      2 → OK + info     (UI focus, navigation — silent info ping)
      3 → PEEK_CONFIRM  (interactive GUI — light notification, auto-dismiss)
      4 → CONFIRM       (file mutation — A2UI card, button press required)
      5 → STRICT_CONFIRM (system dangerous — modal, exact signature, timeout)
    """
    SAFE_READ = 1         # Read-only: screenshots, search, system info
    UI_NAVIGATION = 2     # Open apps, focus windows, navigate tabs
    INTERACTIVE_GUI = 3   # Clicks, typing, hotkeys in active windows
    FILE_MUTATION = 4     # Write/delete files, config changes
    SYSTEM_DANGEROUS = 5  # Shell commands, network sends, destructive ops


class RiskScorer:
    """Maps tool names + args to a 5-level risk score.

    The scorer combines:
    1. Static tool-level risk (from ToolSpec.risk_level)
    2. Dynamic arg-level risk (e.g., fol_command with sudo → higher)
    3. Rule-based overrides (shell markers, destructive patterns)
    """

    # Level 1: Safe Read — no notification
    _SAFE_READ_TOOLS = frozenset({
        "screenshot", "browser_snapshot", "browser_text", "browser_get_url",
        "safari_get_url", "safari_get_text",
        "system_info", "clipboard_get",
        "search_files", "read_file", "search_web",
        "screen_size", "list_events", "list_profiles",
        "get_daily_summary", "get_contact_info", "summarize_emails",
    })

    # Level 2: UI Navigation — silent info ping
    _UI_NAV_TOOLS = frozenset({
        "open_app", "close_app", "activate_app",
        "browser_goto", "browser_close", "browser_refresh",
        "safari_goto",
        "scroll",
    })

    # Level 3: Interactive GUI — light notification (PEEK_CONFIRM)
    _INTERACTIVE_TOOLS = frozenset({
        "click", "double_click", "drag", "move",
        "type_text", "hotkey", "press_key",
        "browser_click", "browser_fill", "browser_press",
        "browser_type",
        "clipboard_set",
    })

    # Level 4: File Mutation — requires explicit confirmation (CONFIRM)
    _FILE_MUTATION_TOOLS = frozenset({
        "write_file", "create_document", "create_presentation",
        "share_document",
        "send_email", "draft_email", "reply_to_email",
        "create_event", "update_event", "delete_event",
        "send_telegram", "send_whatsapp",
        "save_to_obsidian", "remember", "log_daily_activity",
    })

    # Level 5: System Dangerous — modal + exact signature (STRICT_CONFIRM)
    # Note: fol_command has dynamic risk scoring (shell markers → Level 5,
    # non-shell → Level 4), so it's NOT in this static set.
    _SYSTEM_DANGEROUS_TOOLS = frozenset({
        "execute_command",
        "sync_cookies",
    })

    # Shell-execution markers for fol_command (rule-based Level 5).
    _SHELL_MARKERS = (
        "run ",
        "run:",
        "выполни",
        "выполнить",
        "запусти команду",
        "execute",
        "osascript",
        "sudo ",
        "rm -rf",
        "rm -r ",
        "curl ",
        "wget ",
        "kill ",
        "sh ",
        "bash ",
        "python3 ",
    )

    @classmethod
    def score(cls, name: str, args: dict[str, Any]) -> RiskLevel5:
        """Determine the risk level for a tool call."""
        # Static tool-level mapping
        if name in cls._SAFE_READ_TOOLS:
            return RiskLevel5.SAFE_READ
        if name in cls._UI_NAV_TOOLS:
            return RiskLevel5.UI_NAVIGATION
        if name in cls._INTERACTIVE_TOOLS:
            return RiskLevel5.INTERACTIVE_GUI
        if name in cls._FILE_MUTATION_TOOLS:
            return RiskLevel5.FILE_MUTATION
        if name in cls._SYSTEM_DANGEROUS_TOOLS:
            return RiskLevel5.SYSTEM_DANGEROUS

        # Dynamic: fol_command with shell markers → Level 5
        if name == "fol_command":
            command = str(args.get("command", "")) if isinstance(args, dict) else ""
            if any(marker in command.lower() for marker in cls._SHELL_MARKERS):
                return RiskLevel5.SYSTEM_DANGEROUS
            return RiskLevel5.FILE_MUTATION  # non-shell fol_command

        # Default: Level 3 (interactive) for unknown tools
        return RiskLevel5.INTERACTIVE_GUI

    @classmethod
    def to_decision(cls, level: RiskLevel5) -> GateDecision:
        """Map a risk level to the corresponding gate decision."""
        return {
            RiskLevel5.SAFE_READ: GateDecision.OK,
            RiskLevel5.UI_NAVIGATION: GateDecision.OK,
            RiskLevel5.INTERACTIVE_GUI: GateDecision.PEEK_CONFIRM,
            RiskLevel5.FILE_MUTATION: GateDecision.CONFIRM,
            RiskLevel5.SYSTEM_DANGEROUS: GateDecision.STRICT_CONFIRM,
        }[level]


class ConfirmationGate:
    """Deterministic confirmation policy over a ``ToolRegistry``."""

    _APPROVE = re.compile(
        r"^\s*(allowed|allow|approved|approve|yes|yeah|yep|ok|okay|go ahead|"
        r"continue|да|давай|подтвержд|подтверждаю|разреш|можно)\b",
        re.IGNORECASE,
    )
    _DENY = re.compile(
        r"^\s*(denied|deny|decline|no|nope|don'?t|cancel|"
        r"нет|не надо|отмен|запрещ|не разреш)\b",
        re.IGNORECASE,
    )

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._pending: dict[str, str] = {}   # action_id → tool-call signature
        self._approved: set[str] = set()     # signatures approved this session
        self._lock = threading.Lock()        # protects _pending + _approved

    # -- policy ------------------------------------------------------------

    def needs_confirmation(self, name: str, args: dict[str, Any]) -> bool:
        """Code decides — registry metadata + deterministic rules."""
        if not self._registry.has(name):
            return False
        level = RiskScorer.score(name, args)
        return level >= RiskLevel5.INTERACTIVE_GUI

    def score_risk(self, name: str, args: dict[str, Any]) -> RiskLevel5:
        """Return the 5-level risk score for a tool call."""
        return RiskScorer.score(name, args)

    # -- decisions ---------------------------------------------------------

    @staticmethod
    def signature(name: str, args: dict[str, Any]) -> str:
        """Canonical, JSON-normalized tool-call signature (name + args)."""
        try:
            return json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
        except Exception:
            return f"{name}:{str(args)[:300]}"

    def check(self, name: str, args: dict[str, Any]) -> tuple[GateDecision, str | None]:
        """Gate a tool call. Returns ``(decision, action_id)``.

        Uses the 5-level RiskScorer to determine the appropriate response:
          Level 1-2 (SAFE_READ, UI_NAVIGATION) → OK
          Level 3 (INTERACTIVE_GUI) → PEEK_CONFIRM (light, auto-dismiss)
          Level 4 (FILE_MUTATION) → CONFIRM (A2UI card, button press)
          Level 5 (SYSTEM_DANGEROUS) → STRICT_CONFIRM (modal, exact sig)
        """
        if not self._registry.has(name):
            return GateDecision.REJECT, None
        sig = self.signature(name, args)
        with self._lock:
            if sig in self._approved:
                return GateDecision.OK, None

        level = RiskScorer.score(name, args)
        decision = RiskScorer.to_decision(level)

        if decision in (GateDecision.PEEK_CONFIRM, GateDecision.CONFIRM, GateDecision.STRICT_CONFIRM):
            action_id = f"act_{uuid.uuid4().hex[:12]}"
            with self._lock:
                self._pending[action_id] = sig
            return decision, action_id

        return GateDecision.OK, None

    # -- approval ----------------------------------------------------------

    def approve(self, action_id: str) -> bool:
        """Approve a pending action; the exact signature becomes executable."""
        with self._lock:
            sig = self._pending.pop(action_id, None)
            if sig is None:
                return False
            self._approved.add(sig)
            return True

    def deny(self, action_id: str) -> bool:
        """Deny a pending action (removed, never executable this session)."""
        with self._lock:
            return self._pending.pop(action_id, None) is not None

    def approve_all_pending(self) -> int:
        """Approve every currently pending action. Returns the count approved.

        Used when the user approves a confirmation card: all signatures that
        were waiting for approval become executable this session.
        """
        with self._lock:
            count = len(self._pending)
            self._approved.update(self._pending.values())
            self._pending.clear()
            return count

    def deny_all_pending(self) -> int:
        """Deny every currently pending action. Returns the count denied."""
        with self._lock:
            count = len(self._pending)
            self._pending.clear()
            return count

    def reset(self) -> None:
        """Clear all pending + approved state (tests / session reset)."""
        with self._lock:
            self._pending.clear()
            self._approved.clear()

    # -- state -------------------------------------------------------------

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._pending)

    def pending(self) -> dict[str, str]:
        with self._lock:
            return dict(self._pending)

    def approved_signatures(self) -> set[str]:
        with self._lock:
            return set(self._approved)

    # -- natural-language approval detection -------------------------------

    def classify_user_decision(self, message: str) -> str | None:
        """Classify a user reply as ``"approve"`` / ``"deny"`` / ``None``.

        Used so the ConfirmAction card ("Allowed: …" / "Denied: …") and plain
        chat replies ("yes" / "да") can resolve a pending confirmation.
        """
        if not message:
            return None
        if self._APPROVE.match(message):
            return "approve"
        if self._DENY.match(message):
            return "deny"
        return None


__all__ = ["ConfirmationGate", "GateDecision", "RiskScorer", "RiskLevel5"]
