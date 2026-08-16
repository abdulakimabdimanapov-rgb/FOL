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
import uuid
from typing import Any

from modules.tools.base import RiskLevel
from modules.tools.registry import ToolRegistry


class GateDecision(str, enum.Enum):
    OK = "ok"              # execute
    CONFIRM = "confirm"    # blocked — needs explicit user approval
    REJECT = "reject"      # unknown tool — fail closed


class ConfirmationGate:
    """Deterministic confirmation policy over a ``ToolRegistry``."""

    # Shell-execution markers for fol_command (rule-based HIGH risk).
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

    # -- policy ------------------------------------------------------------

    def needs_confirmation(self, name: str, args: dict[str, Any]) -> bool:
        """Code decides — registry metadata + deterministic rules."""
        spec = self._registry.get_spec(name)
        if spec is None:
            return False  # unknown tools are rejected in check(), not confirmed
        if spec.requires_confirmation or spec.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return True
        return self._rule_confirmation(name, args)

    def _rule_confirmation(self, name: str, args: dict[str, Any]) -> bool:
        """Rule-based override: shell-like fol_command always needs approval."""
        if name != "fol_command":
            return False
        command = str(args.get("command", "")) if isinstance(args, dict) else ""
        lowered = command.lower()
        return any(marker in lowered for marker in self._SHELL_MARKERS)

    # -- decisions ---------------------------------------------------------

    @staticmethod
    def signature(name: str, args: dict[str, Any]) -> str:
        """Canonical, JSON-normalized tool-call signature (name + args)."""
        try:
            return json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
        except Exception:
            return f"{name}:{str(args)[:300]}"

    def check(self, name: str, args: dict[str, Any]) -> tuple[GateDecision, str | None]:
        """Gate a tool call. Returns ``(decision, action_id)``."""
        if not self._registry.has(name):
            return GateDecision.REJECT, None
        sig = self.signature(name, args)
        if sig in self._approved:
            return GateDecision.OK, None
        if self.needs_confirmation(name, args):
            action_id = f"act_{uuid.uuid4().hex[:12]}"
            self._pending[action_id] = sig
            return GateDecision.CONFIRM, action_id
        return GateDecision.OK, None

    # -- approval ----------------------------------------------------------

    def approve(self, action_id: str) -> bool:
        """Approve a pending action; the exact signature becomes executable."""
        sig = self._pending.pop(action_id, None)
        if sig is None:
            return False
        self._approved.add(sig)
        return True

    def deny(self, action_id: str) -> bool:
        """Deny a pending action (removed, never executable this session)."""
        return self._pending.pop(action_id, None) is not None

    def approve_all_pending(self) -> int:
        """Approve every currently pending action. Returns the count approved.

        Used when the user approves a confirmation card: all signatures that
        were waiting for approval become executable this session.
        """
        count = len(self._pending)
        self._approved.update(self._pending.values())
        self._pending.clear()
        return count

    def deny_all_pending(self) -> int:
        """Deny every currently pending action. Returns the count denied."""
        count = len(self._pending)
        self._pending.clear()
        return count

    def reset(self) -> None:
        """Clear all pending + approved state (tests / session reset)."""
        self._pending.clear()
        self._approved.clear()

    # -- state -------------------------------------------------------------

    def has_pending(self) -> bool:
        return bool(self._pending)

    def pending(self) -> dict[str, str]:
        return dict(self._pending)

    def approved_signatures(self) -> set[str]:
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


__all__ = ["ConfirmationGate", "GateDecision"]
