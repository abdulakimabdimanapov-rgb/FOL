"""Execute shell commands safely using argument arrays and strict executable validation."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
from typing import Any, Final

from modules.tools.base import AbstractTool, Permission, RiskLevel, ToolResult

# High-risk executables that should never be executed via this tool
DENIED_EXECUTABLES: Final[set[str]] = {
    "sudo", "su", "doas", "chmod", "chown", "mkfs", "dd",
    "shutdown", "reboot", "halt", "passwd", "useradd", "usermod",
}

# High-risk patterns in raw command strings (chaining, substitution, subshells)
SUSPICIOUS_SHELL_PATTERNS: Final[list[str]] = [
    r";", r"&&", r"\|\|", r"`", r"\$\(", r">\s*/dev/", r"\|\s*(ba)?sh"
]


class ExecuteCommand(AbstractTool):
    """Execute a terminal command safely."""

    name = "execute_command"
    description = "Execute a shell command safely using validated argument tokens."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
        },
        "required": ["command"],
    }
    required_permissions = [Permission.HIGH]
    # Canonical metadata (Phase 2): executing arbitrary shell commands is
    # high-risk and must be confirmed by the user.
    risk_level = RiskLevel.HIGH
    requires_confirmation = True
    timeout = 30.0

    def _validate_and_parse(self, command: str) -> tuple[bool, str, list[str]]:
        """Validate command and parse into argument tokens.
        
        Returns: (is_valid, error_reason, tokens)
        """
        cmd_str = command.strip()
        if not cmd_str:
            return False, "No command provided.", []

        # Check for shell metacharacter chaining / substitution
        for pattern in SUSPICIOUS_SHELL_PATTERNS:
            if re.search(pattern, cmd_str):
                return False, f"Command blocked: suspicious shell pattern detected ({pattern}).", []

        # Parse command into tokens safely
        try:
            tokens = shlex.split(cmd_str)
        except ValueError as exc:
            return False, f"Malformed command syntax: {exc}", []

        if not tokens:
            return False, "No valid command tokens found.", []

        executable = os.path.basename(tokens[0]).lower()
        if executable in DENIED_EXECUTABLES:
            return False, f"Command blocked: executable '{executable}' is restricted.", []

        # Destructive rm check
        if executable == "rm":
            for tok in tokens[1:]:
                if tok.startswith("/") or tok == "~" or ".." in tok:
                    return False, "Command blocked: destructive path in 'rm' command.", []

        return True, "", tokens

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        command = params.get("command", "").strip()
        is_valid, err_reason, tokens = self._validate_and_parse(command)
        if not is_valid:
            return ToolResult(success=False, error=err_reason)

        try:
            # Use create_subprocess_exec (shell=False) to avoid shell injection
            proc = await asyncio.create_subprocess_exec(
                tokens[0],
                *tokens[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            output = stdout.decode(errors="ignore").strip()
            err = stderr.decode(errors="ignore").strip()

            if proc.returncode == 0:
                return ToolResult(success=True, output=output or "Command executed successfully.")
            return ToolResult(success=False, error=err or output or f"Command failed with exit code {proc.returncode}.")
        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"Command timed out after {self.timeout}s.")
        except Exception as exc:
            return ToolResult(success=False, error=f"Execution error: {exc}")

