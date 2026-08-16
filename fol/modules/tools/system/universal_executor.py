"""Universal Command Executor — converts natural language to executable commands.

When FOL doesn't have a built-in command for something, this module uses the LLM
to generate shell commands, AppleScript, or Python code to accomplish the task.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# System prompt for the command generator
COMMAND_GENERATOR_PROMPT = """You are a command executor. Convert the user's natural language request into executable commands on macOS.

The user's request: {user_input}

You MUST respond with ONLY a JSON object in this exact format:
{{
  "thought": "brief explanation of what you're doing",
  "method": "shell" or "applescript" or "python",
  "command": "the actual command to execute",
  "explanation": "brief explanation of what the command does (in user's language)"
}}

Rules:
- For shell commands, use the actual shell syntax (ls, cp, open, etc.)
- For AppleScript, use proper AppleScript syntax for macOS automation
- For Python, write a Python one-liner or small script
- NEVER include sudo, rm -rf /, or destructive commands
- NEVER access files outside the user's home directory
- Prefer shell commands for simple tasks
- Use AppleScript for controlling macOS apps (Safari, Music, System Events, etc.)
- Respond ONLY with the JSON object, nothing else
- If the task cannot be accomplished with a command, respond with: {{"thought": "cannot execute", "method": "none", "command": "", "explanation": "Cannot execute this command"}}

Examples:
- "create a folder called test" → {{"thought": "create directory", "method": "shell", "command": "mkdir -p ~/test", "explanation": "Создаю папку test в домашней директории"}}
- "open calculator" → {{"thought": "open calculator app", "method": "shell", "command": "open -a Calculator", "explanation": "Открываю калькулятор"}}
- "what's the weather" → {{"thought": "check weather via terminal", "method": "shell", "command": "curl -s 'wttr.in/?format=3'", "explanation": "Проверяю погоду"}}
- "take a screenshot" → {{"thought": "screenshot command", "method": "shell", "command": "screencapture -x ~/Desktop/screenshot.png", "explanation": "Делаю скриншот"}}
- "send a message on telegram" → {{"thought": "cannot automate telegram send without credentials", "method": "none", "command": "", "explanation": "Для отправки сообщений в Telegram настройте интеграцию с Telegram ботом"}}
"""

# Dangerous patterns to block
BLOCKED_PATTERNS = [
    r"rm\s+(-rf|/\s)",
    r"sudo",
    r"dd\s+if=",
    r"mkfs",
    r"chmod\s+777",
    r"passwd",
    r"kill\s+-9",
    r">\s+/dev/(sda|sdb)",
    r"(wget|curl)\s+.*\|.*sh",
    r"eval\s*\(",
    r"os\.system\s*\(",
    r"subprocess\.(run|Popen|call)\s*\(\s*\[.*sudo",
]


def _is_safe_command(command: str, method: str) -> bool:
    """Check if a command is safe to execute."""
    if not command:
        return False
    
    cmd_lower = command.strip().lower()
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower):
            logger.warning("Blocked dangerous command: %s", command)
            return False
    
    return True


class UniversalExecutor:
    """Executes any user request by converting natural language to commands."""
    
    def __init__(self, llm_engine: Any = None, tool_registry: Any = None):
        self._llm = llm_engine
        self._tools = tool_registry
    
    async def execute(self, user_input: str) -> str | None:
        """Try to execute any user request.
        
        Returns the result string if successful, or None if the request
        should fall through to the normal LLM response.
        """
        if not self._llm:
            return None
        
        try:
            # Use LLM to generate a command
            prompt = COMMAND_GENERATOR_PROMPT.format(user_input=user_input)
            response = await self._llm.generate(
                prompt,
                system_prompt="You are a command executor. Convert natural language to macOS commands.",
            )
            
            if not response:
                return None
            
            # Parse the JSON response
            parsed = self._parse_response(response)
            if not parsed:
                return None
            
            method = parsed.get("method", "none")
            command = parsed.get("command", "")
            explanation = parsed.get("explanation", "")
            
            if method == "none" or not command:
                return None
            
            # Safety check
            if not _is_safe_command(command, method):
                return f"Команда заблокирована по соображениям безопасности: {command}"
            
            # Execute the command
            result = await self._run_command(command, method)
            
            if explanation:
                return f"{explanation}\n\nРезультат:\n{result}"
            return result
            
        except Exception as exc:
            logger.error("Universal executor failed: %s", exc)
            return None
    
    def _parse_response(self, response: str) -> dict[str, Any] | None:
        """Parse the JSON response from the LLM."""
        import json
        
        try:
            # Try to find JSON in the response
            if "```json" in response:
                start = response.index("```json") + 7
                end = response.index("```", start)
                return json.loads(response[start:end].strip())
            
            if "{" in response and "}" in response:
                start = response.index("{")
                end = response.rindex("}") + 1
                return json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            pass
        
        return None
    
    async def _run_command(self, command: str, method: str) -> str:
        """Execute a command using the specified method."""
        try:
            if method == "shell":
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                output = stdout.decode(errors="ignore").strip()
                err = stderr.decode(errors="ignore").strip()
                
                if proc.returncode == 0:
                    return output or "Команда выполнена успешно."
                return f"Ошибка: {err or output or 'Команда завершилась с ошибкой.'}"
            
            elif method == "applescript":
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                output = stdout.decode(errors="ignore").strip()
                err = stderr.decode(errors="ignore").strip()
                
                if proc.returncode == 0:
                    return output or "AppleScript выполнен успешно."
                return f"Ошибка AppleScript: {err or output}"
            
            elif method == "python":
                proc = await asyncio.create_subprocess_exec(
                    "python3", "-c", command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                output = stdout.decode(errors="ignore").strip()
                err = stderr.decode(errors="ignore").strip()
                
                if proc.returncode == 0:
                    return output or "Python-скрипт выполнен успешно."
                return f"Ошибка Python: {err or output}"
            
            else:
                return f"Неизвестный метод: {method}"
                
        except asyncio.TimeoutError:
            return "Команда выполнялась слишком долго и была прервана."
        except Exception as exc:
            return f"Ошибка выполнения: {exc}"
