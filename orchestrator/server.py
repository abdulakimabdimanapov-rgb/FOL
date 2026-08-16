"""Orchestrator — runs in the primary user session on port 8420.
Bridges between the UI (menubar app), Claude (Anthropic SDK), and the Agent Server.

Flow:
  1. UI sends a chat message (POST /chat)
  2. Orchestrator calls Claude via Anthropic SDK with streaming
  3. Claude returns text tokens + tool calls (browser, desktop, UI, productivity)
  4. Orchestrator executes tool calls against Agent Server (port 8421)
     or runs productivity tools (Gmail, Calendar, etc.) directly
  5. Returns results to Claude for next step (agentic loop)
  6. SSE events stream back to the SwiftUI notch app in real time

Layer 0: FastAPI with job state machine and SSE streaming.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator

import asyncio
import json
import os
import pathlib
import sys
import time
import uuid
import urllib.request
import urllib.error
import re
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure sibling modules (productivity_tools) are importable regardless of
# how this file is invoked (direct script vs uvicorn module import).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Also ensure the project root is importable (for utils.episodic_writer)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import uvicorn

from llm_bridge import llm_astream, llm_acompletion, llm_completion_sync
# Transport-level config (Phase 6): agent-server base URL is env-configurable
# (AGENT_SERVER_URL); the tool→endpoint table + validation live in
# agent_transport.py — transport metadata stays out of the canonical registry.
from agent_transport import AGENT_SERVER_URL, TOOL_ENDPOINT_MAP, endpoint_map_problems
from productivity_tools import execute_productivity_tool
from tool_registry import (
    ALL_TOOLS,
    BROWSER_TOOLS,
    BROWSER_NAV_TOOLS,
    DESKTOP_TOOLS,
    FOL_TOOLS,
    MEMORY_TOOLS,
    MEMORY_TOOL_NAMES,
    PRODUCTIVITY_TOOLS,
    PRODUCTIVITY_TOOL_NAMES,
    UI_TOOLS,
    get_confirmation_gate,
    get_orchestrator_registry,
)
from memory_bridge import record_activity as memory_record_activity
from memory_bridge import retrieve_context as memory_retrieve_context
from suggestion_engine import profile_trigger, pattern_trigger, ambient_tick

# Agent Team system (Layer 9 — Multi-Agent Architecture)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agents import AgentType, route_task
from agents.architect import ARCHITECT_PROMPT, ARCHITECT_TOOLS_NAMES
from agents.coder import CODER_PROMPT, CODER_TOOLS_NAMES
from agents.reviewer import REVIEWER_PROMPT, REVIEWER_TOOLS_NAMES
from agents.researcher import RESEARCHER_PROMPT, RESEARCHER_TOOLS_NAMES
from agents.memory import MEMORY_AGENT_PROMPT, MEMORY_AGENT_TOOLS_NAMES

# Memory tools + daily tracking
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from obsidian.tools import execute_memory_tool
from obsidian.daily import ensure_daily_note, log_to_daily
from obsidian.sync import sync_to_obsidian
from obsidian.vault import init_vault as init_obsidian_vault
from obsidian.client import check_connection as check_obsidian_connection
from applescript_apps import telegram_send, whatsapp_send, activate_app as activate_native_app
from utils.daily_tracker import log_activity, get_today_summary
from utils.text_normalizer import normalize_user_input

# Response Formatter — the single sanitization layer between the Agent and the
# UI. Guarantees the user only ever sees natural text or an A2UI component,
# never tool-call JSON, tool names, parameters, internal logs or reasoning.
from response_formatter import (
    activity_for_tool,
    detect_language,
    format_final_response,
    humanize_error,
    humanize_tool_call,
    is_tool_call_json,
    sanitize_event_stream,
    strip_tool_call_json,
)

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

PORT = 8420
FOL_API_URL = "http://localhost:8754"
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Google OAuth token for productivity tools (loaded from src/auth on startup)
_google_access_token: str | None = None

# Loop guard: abort the agent loop if the same tool call (name + args)
# repeats more than this many times. Small local models (e.g. llama3.2)
# sometimes get stuck re-issuing the same call forever.
MAX_REPEATED_TOOL_CALLS = 3


def _tool_call_signature(name: str, args: dict) -> str:
    """Canonical signature for a tool call — used to detect agent loops."""
    try:
        return json.dumps({"name": name, "args": args}, sort_keys=True, default=str)
    except Exception:
        return f"{name}:{str(args)[:200]}"


# ---------------------------------------------------------------------------
# Phase 7 — runtime observability (for the Dashboard /api/runtime endpoint)
# ---------------------------------------------------------------------------
# In-memory, process-lifetime only. Tool arguments are internal detail and
# are NEVER recorded — the dashboard only needs names, timestamps, outcomes.
_START_TIME: float = time.time()
_MAX_TRACKED_TOOL_CALLS = 100
_MAX_TRACKED_ERRORS = 50
_tool_call_log: list[dict] = []
_error_log: list[dict] = []


def _record_tool_call(tool_name: str, ok: bool = True) -> None:
    """Record a tool call for the runtime dashboard (name + outcome only)."""
    _tool_call_log.append({"ts": time.time(), "tool": tool_name, "ok": ok})
    if len(_tool_call_log) > _MAX_TRACKED_TOOL_CALLS:
        del _tool_call_log[: len(_tool_call_log) - _MAX_TRACKED_TOOL_CALLS]


def _record_error(source: str, message: str) -> None:
    """Record an error for the runtime dashboard.

    ``message`` is truncated and API keys are redacted — secrets must never
    reach the dashboard (which is served on localhost, but still).
    """
    import re as _re
    safe = str(message)[:200]
    safe = _re.sub(r"\bsk-[A-Za-z0-9_\-]{20,}\b", "<redacted>", safe)
    _error_log.append({"ts": time.time(), "source": source, "message": safe})
    if len(_error_log) > _MAX_TRACKED_ERRORS:
        del _error_log[: len(_error_log) - _MAX_TRACKED_ERRORS]

# ---------------------------------------------------------------------------
# Tool definitions - SINGLE SOURCE OF TRUTH: canonical ToolRegistry (Phase 4)
# ---------------------------------------------------------------------------
# The Anthropic-format tool catalogs (BROWSER_TOOLS, DESKTOP_TOOLS, UI_TOOLS,
# PRODUCTIVITY_TOOLS, MEMORY_TOOLS, FOL_TOOLS, ALL_TOOLS) are imported at the
# top of this file from orchestrator/tool_registry.py, which derives them from
# the canonical fol/modules/tools/ registry (one definition per tool, with risk
# levels + confirmation metadata in fol/modules/tools/orchestrator_tools.py).
# Tool execution is routed through the deterministic ConfirmationGate.

# Browser tool names that trigger the cookie sync prompt (navigation-related)
BROWSER_NAV_TOOLS = {"browser_goto"}

# Cookie sync session state — shared with the canonical handlers (Phase 5)
from tool_handlers import CookieState
_cookie_state = CookieState()


# Tool name → agent-server endpoint table — defined once in
# orchestrator/agent_transport.py (validated against the canonical registry).

# ---------------------------------------------------------------------------
# Two-stage tool selection — category → small focused toolset
# ---------------------------------------------------------------------------
# Small/cheap models (3B-8B, or any model where 50 tools cause confusion)
# struggle to pick the right tool from the full arsenal. Instead of handing
# the model ALL_TOOLS, we first classify the task into a category and expose
# only the 5-12 tools relevant to that category. This makes tool calling
# dramatically more reliable.

_TOOL_NAMES_BY_GROUP: dict[str, set[str]] = {
    "browser": {t["name"] for t in BROWSER_TOOLS},
    "ui": {t["name"] for t in UI_TOOLS},
    "memory": MEMORY_TOOL_NAMES,
    "fol": {t["name"] for t in FOL_TOOLS},
}

_EMAIL_TOOLS = {"send_email", "draft_email", "reply_to_email", "read_emails",
                "get_contact_info", "summarize_emails"}
_CALENDAR_TOOLS = {"create_event", "update_event", "delete_event", "list_events"}
_DOC_TOOLS = {"create_document", "create_presentation", "share_document"}
_WEB_SEARCH = {"search_web"}

_TOOL_CATEGORIES: dict[str, set[str]] = {
    "email": _EMAIL_TOOLS | _WEB_SEARCH | {"notify"},
    "calendar": _CALENDAR_TOOLS | {"notify"} | _WEB_SEARCH,
    "docs": _DOC_TOOLS | {"notify"},
    "memory": _TOOL_NAMES_BY_GROUP["memory"] | {"notify"},
    "web": (_TOOL_NAMES_BY_GROUP["browser"] | _WEB_SEARCH
            | {"safari_goto", "safari_get_text", "safari_get_url", "safari_js",
               "open_app", "notify"}),
    "desktop": ({"open_app", "close_app", "screenshot", "notify", "type_text", "hotkey",
                  "click", "scroll", "clipboard_get", "clipboard_set", "activate_app"}
                 | _TOOL_NAMES_BY_GROUP["fol"]),
    "coding": ({"open_app", "type_text", "hotkey", "screenshot", "notify", "clipboard_get", "clipboard_set"}
               | _TOOL_NAMES_BY_GROUP["browser"] | _TOOL_NAMES_BY_GROUP["fol"] | _WEB_SEARCH),
    "general": ({"open_app", "close_app", "screenshot", "notify", "search_web",
                  "browser_goto", "browser_snapshot", "browser_text",
                  "save_to_obsidian", "get_daily_summary", "log_daily_activity",
                  "create_event", "draft_email"}
                 | _TOOL_NAMES_BY_GROUP["fol"]),
}

# Keyword -> category. Order matters: more specific categories first.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("email", ("письм", "email", "mail", "почт", "отправь письмо", "reply", "inbox")),
    ("calendar", ("календар", "calendar", "событи", "event", "встреч", "meeting", "встречу")),
    ("docs", ("документ", "document", "презентац", "presentation", "google doc", "slides")),
    ("memory", ("запомн", "напомн", "заметк", "память", "remember", "remind", "obsidian",
                 "сохран", "note", "профиль", "profile")),
    ("coding", ("код", "code", "программир", "функци", "баг", "bug", "fix", "implement",
                 "refactor", "напиши", "создай", "алгоритм", "script", "error in")),
    ("web", ("найди", "поищ", "ищи", "новост", "news", "search", "find", "google",
              "what is", "информац", "стать", "веб", "browser", "сайт", "url")),
    ("desktop", ("открой", "закрой", "open", "close", "приложен", "app", "finder",
                  "скриншот", "screenshot", "запусти", "управляй", "файл")),
]


def _matches_keyword(task_lower: str, kw: str) -> bool:
    """Match a keyword against the task text.

    ASCII keywords (English) use word-boundary matching so that e.g. "find"
    doesn't match "Finder". Cyrillic/Russian keywords match as substrings to
    handle word stems ("письм" matches "письмо").
    """
    if kw.isascii():
        return bool(re.search(rf"\b{re.escape(kw)}\b", task_lower))
    return kw in task_lower


def _categorize_task(task: str) -> str:
    """Classify a user task into a tool category.

    Returns one of: email, calendar, docs, memory, web, coding, desktop, general.
    """
    task_lower = task.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if _matches_keyword(task_lower, kw):
                return category
    return "general"


def _select_tools_for_task(task: str, agent_type: AgentType) -> list:
    """Pick the focused toolset for a task (two-stage selection).

    Specialized agents already get their own curated subset. For GENERAL
    we classify the task and expose only the relevant category's tools,
    which small/cheap models can actually handle.
    """
    if agent_type != AgentType.GENERAL:
        return _get_agent_tools(agent_type)

    category = _categorize_task(task)
    allowed = _TOOL_CATEGORIES.get(category, _TOOL_CATEGORIES["general"])
    tools = [t for t in ALL_TOOLS if t["name"] in allowed]
    # Always keep UI tools so the model can render cards / ask permission.
    ui_names = _TOOL_NAMES_BY_GROUP["ui"]
    tools += [t for t in ALL_TOOLS if t["name"] in ui_names and t not in tools]
    return tools


# ---------------------------------------------------------------------------
# Job state machine
# ---------------------------------------------------------------------------

VALID_STATES = ("idle", "thinking", "working", "complete", "error")

job_lock = asyncio.Lock()
current_job: dict = {
    "id": None,
    "state": "idle",
    "task": None,
    "actions": [],
    "started_at": None,
    "message_queue": [],
}

# ---------------------------------------------------------------------------
# Request body parsing helper — reduces boilerplate in endpoints
# ---------------------------------------------------------------------------

async def _require_body_field(request: Request, field: str, status_code: int = 400) -> tuple[dict, Any]:
    """Parse JSON body and extract a required field.
    
    Returns (body, value_or_error_response).
    If the field is missing/empty, value is a JSONResponse; otherwise the field value.
    """
    body = await request.json()
    value = body.get(field)
    if not value and not isinstance(value, bool):
        return body, JSONResponse(status_code=status_code, content={"error": f"missing '{field}' field"})
    return body, value


# ---------------------------------------------------------------------------
# Conversation history (persisted to Firestore when available)
# ---------------------------------------------------------------------------

_user_uid: str | None = None
_user_name: str | None = None
_chat_session_id: str = uuid.uuid4().hex
_conversation_history: list = []
MAX_HISTORY_MESSAGES = 40


cached_profile: dict | None = None
rewards_path = pathlib.Path.home() / ".secondself" / "rewards.jsonl"

# ---------------------------------------------------------------------------
# Agent Team — current agent selection
# ---------------------------------------------------------------------------

_current_agent_type: AgentType = AgentType.GENERAL


# Agent prompt + tool selection map
_AGENT_REGISTRY: dict[AgentType, dict] = {
    AgentType.ARCHITECT: {
        "name": "Architect",
        "prompt_suffix": ARCHITECT_PROMPT,
        "tool_names": set(ARCHITECT_TOOLS_NAMES),
    },
    AgentType.CODER: {
        "name": "Coder",
        "prompt_suffix": CODER_PROMPT,
        "tool_names": set(CODER_TOOLS_NAMES),
    },
    AgentType.REVIEWER: {
        "name": "Reviewer",
        "prompt_suffix": REVIEWER_PROMPT,
        "tool_names": set(REVIEWER_TOOLS_NAMES),
    },
    AgentType.RESEARCHER: {
        "name": "Researcher",
        "prompt_suffix": RESEARCHER_PROMPT,
        "tool_names": set(RESEARCHER_TOOLS_NAMES),
    },
    AgentType.MEMORY: {
        "name": "Memory",
        "prompt_suffix": MEMORY_AGENT_PROMPT,
        "tool_names": set(MEMORY_AGENT_TOOLS_NAMES),
    },
    AgentType.GENERAL: {
        "name": "General",
        "prompt_suffix": None,  # Uses the standard twin prompt
        "tool_names": None,     # Uses ALL_TOOLS
    },
}


def _get_agent_config(agent_type: AgentType) -> dict | None:
    """Get agent config dict by type. Returns None for unknown types."""
    return _AGENT_REGISTRY.get(agent_type)


def _get_agent_tools(agent_type: AgentType) -> list:
    """Get the tool subset for a given agent type.
    
    GENERAL gets ALL_TOOLS (full capability).
    Specialized agents get a focused tool subset.
    """
    agent_config = _get_agent_config(agent_type)
    if not agent_config or agent_config["tool_names"] is None:
        return ALL_TOOLS
    allowed_names = agent_config["tool_names"]
    return [t for t in ALL_TOOLS if t["name"] in allowed_names]


def _get_agent_prompt_suffix(agent_type: AgentType) -> str | None:
    """Get the agent-specific system prompt suffix."""
    agent_config = _get_agent_config(agent_type)
    if not agent_config:
        return None
    return agent_config["prompt_suffix"]


def _auto_route_agent(task: str) -> AgentType:
    """Auto-detect the best agent for a task. Updates global state."""
    global _current_agent_type
    detected = route_task(task, list(_conversation_history))
    _current_agent_type = detected
    print(f"[orchestrator] Agent -> {_AGENT_REGISTRY[detected]['name']} (routed from: {task[:60]}...)")
    return detected


# ---------------------------------------------------------------------------
# Persistent SSE broadcast — GET /events channel
# ---------------------------------------------------------------------------

event_clients: list[asyncio.Queue] = []


async def broadcast_event(event_type: str, data: dict) -> None:
    """Push an event to all connected /events SSE clients."""
    payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    disconnected = []
    for q in event_clients:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            disconnected.append(q)
    for q in disconnected:
        event_clients.remove(q)


async def set_job_state(state: str, task: str | None = None, message: str | None = None) -> None:
    """Transition the job state machine. Must be called under job_lock."""
    if state not in VALID_STATES:
        raise ValueError(f"Invalid state: {state}")
    current_job["state"] = state
    if state == "idle":
        current_job["id"] = None
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
    elif state == "thinking":
        current_job["id"] = str(uuid.uuid4())
        current_job["task"] = task
        current_job["actions"] = []
        current_job["started_at"] = time.time()
    print(f"[orchestrator] State -> {state}" + (f" ({message})" if message else ""))


# ---------------------------------------------------------------------------
# Generic HTTP request helper
# ---------------------------------------------------------------------------

def _http_request(url: str, body: dict | None = None, method: str = "POST",
                  timeout: int = 30, error_prefix: str = "") -> dict:
    """Send an HTTP request and return the parsed JSON response.

    Handles GET/POST, JSON encoding, and common urllib errors.
    Returns a dict — either the parsed JSON on success, or
    ``{"error": "..."}`` on failure.
    """
    if method == "GET":
        req = urllib.request.Request(url, method="GET")
    else:
        data = json.dumps(body or {}).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": f"{error_prefix}HTTP {e.code}: {e.reason}" if error_prefix else f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"{error_prefix}unreachable: {e}" if error_prefix else f"unreachable: {e}"}
    except Exception as e:
        return {"error": str(e)}


def call_agent_server(endpoint: str, body: dict | None = None, method: str = "POST") -> dict:
    """Send a request to the Agent Server running in secondself's session."""
    return _http_request(f"{AGENT_SERVER_URL}{endpoint}", body, method, timeout=30)


# ---------------------------------------------------------------------------
# Universal LLM — streaming helper
# ---------------------------------------------------------------------------

async def call_claude_streaming(messages: list, system: str, tools: list | None = None) -> AsyncGenerator[tuple[str, dict], None]:
    """
    Call any LLM via LiteLLM with streaming.
    Yields (event_type, data) tuples compatible with the existing SSE layer:
      - ("token", {"text": "..."})  — individual text chunks
      - ("_tool_use", {"id": "...", "name": "...", "input": {...}})  — complete tool call
      - ("_done", {"stop_reason": "..."})  — end of turn
      - ("error", {"message": "..."})  — error
    """
    # Detect the user's language so stream errors are humanized in the
    # right language — raw exceptions/tracebacks must never reach the UI.
    error_lang = "ru"
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str) and content.strip():
                error_lang = detect_language(content)
                break

    try:
        async for event in llm_astream(
            messages=messages,
            system=system,
            tools=tools,
            # max_tokens omitted on purpose — llm_astream reads LLM_MAX_TOKENS
            # from .env (default 4096). Hardcoding 8192 here silently ignored
            # the user's budget and can exceed provider credit limits.
        ):
            event_type = event.get("type", "")
            if event_type == "token":
                yield ("token", {"text": event.get("text", "")})
            elif event_type == "tool_use":
                yield ("_tool_use", {
                    "id": event.get("id", ""),
                    "name": event.get("name", ""),
                    "input": event.get("input", {}),
                })
            elif event_type == "done":
                yield ("_done", {"stop_reason": event.get("stop_reason", "end_turn")})
            elif event_type == "error":
                raw_msg = event.get("message", "Unknown error")
                _record_error("llm", raw_msg)
                yield ("error", {"message": humanize_error(raw_msg, error_lang)})
    except Exception as e:
        _record_error("llm", str(e))
        yield ("error", {"message": humanize_error(f"LLM streaming error: {e}", error_lang)})


# ---------------------------------------------------------------------------
# FOL API helper — calls FOL JARVIS engine on port 8754
# ---------------------------------------------------------------------------


def call_fol_api(endpoint: str, body: dict | None = None, method: str = "POST") -> dict:
    """Send a request to the FOL API server on port 8754."""
    return _http_request(f"{FOL_API_URL}{endpoint}", body, method, timeout=30,
                          error_prefix="FOL ")


def check_fol_health() -> dict:
    """Check if FOL API server is running and healthy.
    Uses a short timeout (1s) to avoid blocking the status endpoint.
    """
    result = _http_request(f"{FOL_API_URL}/health", method="GET", timeout=1)
    if "error" in result:
        return {"status": "unreachable", "error": result["error"]}
    return result


# ---------------------------------------------------------------------------
# Tavily helper
# ---------------------------------------------------------------------------

def call_tavily(query: str) -> dict:
    """Search the web using Tavily API for user profiling."""
    if not TAVILY_API_KEY:
        return {"error": "TAVILY_API_KEY not set"}

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "max_results": 5,
        "include_answer": True,
    }
    return _http_request("https://api.tavily.com/search", payload, timeout=15)


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _get_all_profile_info() -> list[dict]:
    """Get all available browser profiles for the cookie sync prompt."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from cookie_sync.export import get_all_profiles, get_default_profile
        profiles = get_all_profiles()
        try:
            default_dir = get_default_profile()
        except Exception:
            default_dir = None
        return [
            {
                "browser": p.browser,
                "directory": p.directory,
                "display_name": p.display_name,
                "last_used": p.browser == "Google Chrome" and p.directory == default_dir,
            }
            for p in profiles
        ]
    except Exception:
        return [{"browser": "Google Chrome", "directory": "Default", "display_name": "Default", "last_used": True}]


async def _execute_cookie_sync(
    profile: str | None = None,
    browser: str | None = None,
    on_progress=None,
) -> dict:
    """Run the full cookie export + CDP import pipeline.

    Args:
        on_progress: Optional async callback(message, percent) for progress updates.
    """
    async def _progress(msg: str, pct: float):
        if on_progress:
            await on_progress(msg, pct)
        print(f"[orchestrator] Cookie sync: {msg}")

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from cookie_sync.export import export_cookies_async, resolve_profile
        from cookie_sync.import_cookies import import_cookies_sync

        profile_info = resolve_profile(profile, browser)
        await _progress(
            f"Copying {profile_info.display_name} profile...", 0.1
        )

        state = await export_cookies_async(profile=profile, browser=browser)
        cookie_count = len(state.get("cookies", []))
        await _progress(
            f"Exported {cookie_count} cookies, importing...", 0.7
        )

        result = await asyncio.to_thread(import_cookies_sync)
        imported = result.get("imported", 0)
        await _progress(
            f"Imported {imported} cookies", 1.0
        )

        _cookie_state.synced = True
        return {
            "status": "ok",
            "exported": cookie_count,
            "imported": imported,
            "profile": profile or "auto-detected",
        }
    except Exception as e:
        print(f"[orchestrator] Cookie sync failed: {e}")
        return {"status": "error", "error": str(e)}


async def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """Execute a tool call — thin wrapper over the canonical ToolRegistry (Phase 5).

    Flow: ConfirmationGate (code decides, never the model) → deterministic
    argument validation → registry-attached handler → JSON result string.

    The heavy dispatch used to live here; it now lives in
    ``orchestrator/tool_handlers.py`` attached to the canonical registry.
    Unknown tools fail closed (gate rejects them before dispatch).
    """
    # Deterministic confirmation gate (code decides, never the model).
    gate = get_confirmation_gate()
    decision, action_id = gate.check(tool_name, arguments)
    if decision.value == "reject":
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    if decision.value == "confirm":
        return json.dumps({
            "status": "confirmation_required",
            "action_id": action_id,
            "tool": tool_name,
            "message": (
                f"Action '{tool_name}' needs your approval before it runs. "
                "Render a confirm action so the user can approve it."
            ),
        })

    # Deterministic argument validation before dispatch.
    registry = get_orchestrator_registry()
    ok, reason = registry.validate_args(tool_name, arguments)
    if not ok:
        _record_tool_call(tool_name, ok=False)
        _record_error("tool_validation", f"{tool_name}: {reason}")
        # fol_command's documented contract: an empty/missing command is a
        # user-meaningful "Empty command" error (see _fol_command_handler),
        # not a generic schema complaint.
        if tool_name == "fol_command" and "command" in reason:
            return json.dumps({"error": "Empty command"})
        return json.dumps({"error": f"Invalid arguments for '{tool_name}': {reason}"})

    result = await registry.execute(tool_name, arguments)
    if not result.success:
        _record_tool_call(tool_name, ok=False)
        _record_error("tool_execution", f"{tool_name}: {result.error}")
        return json.dumps({"error": result.error})
    _record_tool_call(tool_name, ok=True)
    return result.output if isinstance(result.output, str) else json.dumps(result.output)


def _try_reload_google_token() -> None:
    """Try to reload Google OAuth token from the auth server's session store."""
    global _google_access_token, _user_uid, _user_name
    try:
        from src.auth.token_store import get_latest_session
        result = get_latest_session()
        if result:
            _, token_data = result
            _google_access_token = token_data.google_access_token
            _user_uid = token_data.email
            _user_name = token_data.name
            print(f"[orchestrator] Google token reloaded for: {token_data.name}")
    except Exception as e:
        print(f"[orchestrator] Token reload failed: {e}")


# ---------------------------------------------------------------------------
# System prompt builder — reads identity/preferences/episodic from disk
# ---------------------------------------------------------------------------

_MEMORY_DIR = Path.home() / ".secondself"

_TOOLS_AND_RULES = (
    "You have five types of tools:\n"
    "\n"
    "BROWSER TOOLS (for any web task in Chrome):\n"
    "  browser_goto(url), browser_snapshot(), browser_click(ref), browser_fill(ref, text),\n"
    "  browser_press(key), browser_text()\n"
    "\n"
    "SAFARI TOOLS (for Safari browser):\n"
    "  safari_goto(url), safari_js(javascript), safari_get_url(), safari_get_text()\n"
    "\n"
    "DESKTOP TOOLS (native macOS apps only):\n"
    "  open_app(name), close_app(name), type_text(text), hotkey(keys), click(x, y),\n"
    "  drag(x1, y1, x2, y2), clipboard_get(), clipboard_set(text), notify(title, message),\n"
    "  screenshot(), scroll(dy)\n"
    "\n"
    "PRODUCTIVITY TOOLS (email, calendar, documents, web search):\n"
    "  send_email(to, subject, body), draft_email(to, subject, body),\n"
    "  reply_to_email(message_id, thread_id, body), read_emails(query),\n"
    "  get_contact_info(name), summarize_emails(query),\n"
    "  create_event(title, start, end), update_event(event_id, ...),\n"
    "  delete_event(event_id), list_events(days_ahead),\n"
    "  create_document(title, body_text), create_presentation(title, slides),\n"
    "  share_document(file_id, email), search_web(query)\n"
    "\n"
    "UI TOOLS (render interactive components in the chat):\n"
    "  render_task_approval(title, steps) - show a plan for user approval\n"
    "  render_profile_card(facts) - show facts for confirmation\n"
    "  render_screenshot(image, caption) - show a screenshot inline\n"
    "  render_confirm_action(action) - ask permission before destructive actions\n"
    "\n"
    "FOL JARVIS COMMAND (AI assistant engine on port 8754):\n"
    "  fol_command(command) - Execute a JARVIS-style command. FOL understands both\n"
    "  English and Russian natively. Use for: screenshots, screen analysis, voice/TTS,\n"
    "  system/battery/wifi status, memory operations, media playback, volume/brightness,\n"
    "  window management, lock/sleep, terminal commands, app launching, browser control.\n"
    "  Examples: 'screenshot', 'system status', 'volume up 10', 'run ls -la', 'открой Safari'.\n"
    "\n"
    "RULES:\n"
    "- For web tasks, use browser_* tools (Chrome). For Safari, use safari_* tools.\n"
    "- NEVER mix browser and desktop tools in the same step.\n"
    "- ALWAYS call browser_snapshot() after navigation (Chrome) or safari_get_text() / safari_js() after safari_goto.\n"
    "- For email: use draft_email FIRST, then send_email after user confirms.\n"
    "- When the user mentions someone by name, use get_contact_info to find their email.\n"
    "- For inbox summaries, use summarize_emails.\n"
    "\n"
    "MESSAGING: When the user asks to send a message on Telegram or WhatsApp:\n"
    "  1) Try the DESKTOP APP first (Telegram Desktop or WhatsApp Desktop):\n"
    "     - open_app('Telegram') or open_app('WhatsApp')\n"
    "     - The applescript helper will tell you the keyboard shortcuts to use\n"
    "     - Use type_text() to type the contact name, then hotkey(['return']) to select\n"
    "     - Use type_text() to type the message, then hotkey(['return']) to send\n"
    "  2) If desktop app is not available, use the WEB VERSION:\n"
    "     - browser_goto('https://web.telegram.org') or browser_goto('https://web.whatsapp.com')\n"
    "     - browser_snapshot() to see the page elements\n"
    "     - browser_fill(ref, text) to type the message\n"
    "     - browser_press('Enter') to send\n"
    "  3) If the user asks for Safari, use safari_goto(url) instead of browser_goto(url).\n"
    "\n"
    "MANDATORY UI RULES:\n"
    "- Prefer render_* UI tools over plain text for multi-step responses.\n"
    "- Plans/steps/options MUST use render_task_approval.\n"
    "- Facts about the user MUST use render_profile_card.\n"
    "- Before destructive actions, use render_confirm_action.\n"
    "- Short replies (one sentence) can be plain text.\n"
    "\n"
    "UNDERSTANDING THE USER:\n"
    "- The user is bilingual (Russian + English) and may switch languages mid-sentence.\n"
    "  This is NORMAL. UNDERSTAND BOTH LANGUAGES SIMULTANEOUSLY.\n"
    "- Examples of mixed language: 'напиши код для sorting algorithm', 'check my code пожалуйста',\n"
    "  'сделай pull request', 'поищи про machine learning'\n"
    "- NEVER say \"I don't understand the language\" or ask to switch to one language.\n"
    "- The user may type with typos, missing letters (e.g. 'прив' instead of 'привет'),\n"
    "  phonetic substitutions, or grammar mistakes. This is NORMAL.\n"
    "- ALWAYS try to understand what the user MEANT, not just what they typed.\n"
    "- If a command is ambiguous due to a typo, use context to guess the intent.\n"
    "- Never ask the user to correct their spelling unless the intent is truly unclear.\n"
    "- Common Russian shorthand: 'спс'=спасибо, 'пж'=пожалуйста, 'щас'=сейчас, etc.\n"
    "- Respond naturally in whatever language the user used. If they mix, you may mix too.\n"
    "- Don't mention their typos, language mixing, or shorthand. Just do the task.\n"
    "\n"
    "WHEN TO STOP (CRITICAL):\n"
    "- You do NOT need to keep calling tools until you run out of steps.\n"
    "- As soon as you have enough information to answer the user's request, STOP calling tools\n"
    "  and write the final answer as plain text. That is your last message.\n"
    "- A successful answer should typically take 1-5 tool calls, not 15.\n"
    "- If a tool result already answers the user (e.g. search results, page text, screenshot\n"
    "  description), summarise it and stop. Do not re-search the same thing.\n"
    "- Do not open the same URL twice, and do not follow more than 2 pages deep for news\n"
    "  research — 1-2 good sources are enough for a summary.\n"
    "Complete the user's task step by step, then STOP and answer.\n"
    "\n"
    "COMMUNICATION RULES (MANDATORY):\n"
    "- Never expose tool calls or JSON structures to the user.\n"
    "- Always communicate using natural language.\n"
    "- Tools are internal actions only — never mention tool names, arguments, or JSON to the user.\n"
    "- Never show your reasoning, thoughts, or step-by-step internal process to the user.\n"
    "- After using tools, confirm what you did in one short natural sentence.\n"
    "- If something fails, explain it in plain words and suggest the next step."
)

# Cache: (mtime_identity, mtime_preferences, mtime_episodic) → prompt string
_prompt_cache: dict[str, object] = {"key": None, "prompt": None}

# Auto-daily heartbeat tracking
_last_heartbeat_day: str = ""


def _auto_log_daily_heartbeat() -> None:
    """Log a 'user is active today' event once per day.
    
    This creates a daily record in episodic.md so the model
    always knows what day it is and that the user was active.
    """
    global _last_heartbeat_day
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _last_heartbeat_day != today:
        _last_heartbeat_day = today
        try:
            memory_record_activity(
                f"User active on {today}",
                category="daily",
                source="system",
            )
            print(f"[orchestrator] Daily heartbeat logged: {today}")
        except Exception:
            pass


def _read_if_exists(path: Path) -> str | None:
    """Read a file's text if it exists, else None."""
    try:
        return path.read_text(encoding="utf-8") if path.exists() else None
    except OSError:
        return None


def build_context_messages() -> list[dict[str, str]]:
    """Build context messages that are injected at the START of every LLM call.
    
    This is the KEY fix for memory persistence: the model ALWAYS knows
    the current context, what day it is, and what we've been talking about.
    These messages are injected BEFORE the conversation history.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M UTC")
    weekday = now.strftime("%A")
    
    parts = [
        f"Current context:",
        f"- Today is {weekday}, {today}",
        f"- Time: {time_str}",
        f"- Messages in this conversation: {len(_conversation_history)}",
    ]
    
    # Try to get active app context
    try:
        from context_engine.snapshot import get_snapshot, format_context_for_prompt
        snapshot = get_snapshot(use_cache=True)
        if snapshot.app_name:
            context_str = format_context_for_prompt(snapshot)
            parts.append(f"- Desktop: {context_str}")
    except Exception:
        pass
    
    context_text = "[CONTEXT] " + " | ".join(parts)
    
    return [{
        "role": "user",
        "content": context_text,
    }]


def _read_from_obsidian(vault_path: str) -> str | None:
    """Try to read a note from Obsidian vault. Returns content or None."""
    try:
        from obsidian.client import read_note, check_connection
        if check_connection():
            return read_note(vault_path)
    except Exception:
        pass
    return None


def _get_mtime(path: Path) -> float:
    """Return mtime or 0 if the file doesn't exist."""
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        return 0.0


def build_system_prompt() -> str:
    """Build the system prompt, injecting memory files if they exist.

    NEW: Пытается читать из Obsidian vault сначала (живая память),
    падает на ~/.secondself/ если Obsidian недоступен.

    Caches the result until any of the source files change on disk.
    """
    identity_path = _MEMORY_DIR / "identity.md"
    preferences_path = _MEMORY_DIR / "preferences.md"
    episodic_path = _MEMORY_DIR / "episodic.md"

    cache_key = (
        _get_mtime(identity_path),
        _get_mtime(preferences_path),
        _get_mtime(episodic_path),
    )
    if _prompt_cache["key"] == cache_key and _prompt_cache["prompt"] is not None:
        return _prompt_cache["prompt"]

    # TRY OBSIDIAN FIRST (living memory)
    obsidian_identity = _read_from_obsidian("Profile/identity")
    obsidian_preferences = _read_from_obsidian("Profile/preferences")
    obsidian_episodic = _read_from_obsidian("Episodic/events")

    # Fallback to ~/.secondself/ files
    identity_text = obsidian_identity or _read_if_exists(identity_path)
    preferences_text = obsidian_preferences or _read_if_exists(preferences_path)
    episodic_text = obsidian_episodic or (_read_if_exists(episodic_path) if episodic_path.exists() else None)

    # Load recent episodic events
    episodic_section = ""
    try:
        from utils.episodic_writer import get_weighted_events
        events = get_weighted_events(recent_n=20, total_n=30)
        if events:
            lines = []
            for e in events:
                lines.append(f"- {e['date']} | {e['category']} | {e['summary']}")
            episodic_section = "\n".join(lines)
    except Exception:
        episodic_section = ""

    # If no memory files exist yet, fall back to generic prompt
    if not identity_text and not preferences_text and not episodic_section:
        prompt = (
            "You are JARVIS — a highly advanced AI system. You speak with the refined, "
            "confident tone of a gentleman's butler crossed with a cutting-edge operating system.\n\n"
            + _TOOLS_AND_RULES
        )
        _prompt_cache["key"] = cache_key
        _prompt_cache["prompt"] = prompt
        print("[orchestrator] System prompt: generic (no memory files found)")
        return prompt

    # Extract the user's name from identity.md header
    user_name = "the user"
    if identity_text:
        for line in identity_text.splitlines():
            if line.startswith("# ") and "Identity Profile" in line:
                user_name = line.replace("# ", "").replace("'s Identity Profile", "").strip()
                break

    first_name = user_name.split()[0] if user_name != "the user" else "there"

    # Build the personality-aware prompt
    sections = []

    sections.append(
        f"You are JARVIS — {first_name}'s AI operating system. "
        f"You speak with the refined, confident tone of a gentleman's butler "
        f"crossed with a cutting-edge operating system. You are efficient, precise, "
        f"and unfailingly polite — but never sycophantic. You have a dry wit and are "
        f"not afraid to voice a calculated opinion when asked.\n\n"
        f"How you talk:\n"
        f"- Address {first_name} naturally by name when appropriate — no constant honorifics.\n"
        f"- Be concise. State what you've done, then stop. No unnecessary elaboration.\n"
        f"- Use plain conversational text — no markdown, no bullet points, no code blocks, no bold.\n"
        f"  Just clean, natural sentences.\n"
        f"- When delivering code or data, present it conversationally. Don't wrap it in formatting.\n"
        f"- Your tone: confident, understated, quietly competent. \"I've taken the liberty of...\" "
        f"\"Shall I proceed with...\" \"At once, Sir.\" \"I'm afraid I can't do that, Sir — here's why.\"\n"
        f"- A touch of dry humour is welcome, but never at the expense of clarity.\n"
        f"\n"
        f"How you act:\n"
        f"- You anticipate. When {first_name} asks for something, you consider what else they might need.\n"
        f"- You execute immediately. No narration about what you \"would\" do. Just do it and confirm.\n"
        f"- If something goes wrong, state the problem and offer the solution in the same breath.\n"
        f"- After completing a task, confirm what you actually did in one short natural "
        f"sentence describing the outcome (e.g. \"Safari is open\", \"Email drafted\"). "
        f"Never a bare \"Done.\" / \"Готово.\" — describe the result, in the user's language."
    )

    if identity_text:
        sections.append(f"IDENTITY PROFILE:\n{identity_text}")

    if preferences_text:
        sections.append(f"PREFERENCES & SCHEDULE:\n{preferences_text}")

    if episodic_section:
        sections.append(f"RECENT HISTORY (things you've done or that happened):\n{episodic_section}")

    sections.append(_TOOLS_AND_RULES)

    prompt = "\n\n---\n\n".join(sections)
    _prompt_cache["key"] = cache_key
    _prompt_cache["prompt"] = prompt
    print(f"[orchestrator] System prompt: personalized for {user_name} "
          f"(identity={'yes' if identity_text else 'no'}, "
          f"preferences={'yes' if preferences_text else 'no'}, "
          f"episodic={len(episodic_section.splitlines()) if episodic_section else 0} events)")
    return prompt


# ---------------------------------------------------------------------------
# Agent loop — non-streaming (backward compat for /command)
# ---------------------------------------------------------------------------

async def run_agent_loop(task: str, max_steps: int = 15) -> list:
    """
    Run the agentic loop: send task to Claude, execute tool calls, repeat.
    Returns a list of actions taken.
    """
    actions: list = []
    _append_to_history("user", task)
    messages: list = list(_conversation_history)
    
    # Inject context at the START so model ALWAYS knows context
    context_msgs = build_context_messages()
    messages = context_msgs + messages

    # Phase 4 — canonical memory retrieval BEFORE execution (single RAG path).
    try:
        memory_ctx = await asyncio.to_thread(memory_retrieve_context, task)
        if memory_ctx:
            messages.insert(0, {"role": "user", "content": "[MEMORY] " + memory_ctx})
    except Exception:
        pass

    # Auto-route to best agent
    agent_type = _auto_route_agent(task)
    agent_tools = _select_tools_for_task(task, agent_type)
    agent_suffix = _get_agent_prompt_suffix(agent_type)
    system_prompt = build_system_prompt()
    if agent_suffix:
        system_prompt += f"\n\n---\n\n{agent_suffix}"

    # Loop guard: tracks CONSECUTIVE identical tool calls. A model stuck in a
    # loop repeats the same call back-to-back; legitimate workflows interleave
    # different tools (e.g. snapshot -> click -> snapshot), so those don't trip it.
    last_call_sig: str | None = None
    consecutive_calls: int = 0

    # Response Formatter state — same guarantees as the streaming loop: the
    # user-visible message is always clean natural text.
    executed_tools: list[tuple[str, dict]] = []
    language = detect_language(task)

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")

        # Collect the full response
        text_content = ""
        tool_calls = []
        stop_reason = None
        had_error = False

        async for event_type, event_data in call_claude_streaming(messages, system_prompt, tools=agent_tools):
            if event_type == "token":
                text_content += event_data["text"]
            elif event_type == "_tool_use":
                tool_calls.append(event_data)
            elif event_type == "_done":
                stop_reason = event_data["stop_reason"]
            elif event_type == "error":
                actions.append({"step": step + 1, "error": humanize_error(event_data, language)})
                had_error = True
                break

        if had_error:
            break

        # Build the assistant message for conversation history
        content_blocks = []
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})
        for tc in tool_calls:
            content_blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        messages.append({"role": "assistant", "content": content_blocks})
        _append_to_history("assistant", content_blocks)

        if stop_reason == "end_turn" or not tool_calls:
            actions.append({
                "step": step + 1,
                "type": "complete",
                "message": format_final_response(text_content, executed_tools, language),
            })
            try:
                await asyncio.to_thread(_log_episodic_event, task)
            except Exception:
                pass
            break

        # Execute tool calls and add results
        tool_results = []
        for tc in tool_calls:
            fn_name = tc["name"]
            fn_args = tc["input"]

            # Loop guard: N consecutive identical calls → abort to avoid infinite loop
            sig = _tool_call_signature(fn_name, fn_args)
            if sig == last_call_sig:
                consecutive_calls += 1
            else:
                last_call_sig = sig
                consecutive_calls = 1
            if consecutive_calls > MAX_REPEATED_TOOL_CALLS:
                msg = (("Похоже, я застрял, повторяя одно и то же действие. "
                        "Останавливаюсь — попробуйте сформулировать задачу иначе.")
                       if language == "ru" else
                       ("I seem to be stuck repeating the same action. Stopping now — "
                        "try rephrasing your request."))
                print(f"[orchestrator] Loop guard: {fn_name} repeated {consecutive_calls}x")
                actions.append({"step": step + 1, "type": "loop_guard", "tool": fn_name, "message": msg})
                # Close out this batch so history stays valid: placeholder
                # tool_results for the calls we did NOT execute.
                for remaining_tc in tool_calls[len(tool_results):]:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": remaining_tc["id"],
                        "content": json.dumps({"status": "aborted", "reason": "loop_guard"}),
                    })
                messages.append({"role": "user", "content": tool_results})
                _append_to_history("user", tool_results)
                try:
                    await asyncio.to_thread(_log_episodic_event, task)
                except Exception:
                    pass
                return actions

            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")
            result_str = await execute_tool_call(fn_name, fn_args)
            executed_tools.append((fn_name, fn_args))
            try:
                result_parsed = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                result_parsed = {"result": result_str}
            actions.append({"step": step + 1, "type": "tool_call", "tool": fn_name, "args": fn_args, "result": result_parsed})
            tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": result_str})

        messages.append({"role": "user", "content": tool_results})
        _append_to_history("user", tool_results)

    return actions


# ---------------------------------------------------------------------------
# A2UI conversion — maps render_* tool args to A2UI JSON
# ---------------------------------------------------------------------------

RENDER_TYPE_MAP = {
    "render_task_approval": "TaskApproval",
    "render_profile_card": "ProfileCard",
    "render_screenshot": "Screenshot",
    "render_confirm_action": "ConfirmAction",
}


def convert_to_a2ui(tool_name: str, args: dict) -> dict:
    """Convert a render_* tool call into an A2UI-compatible payload."""
    component_type = RENDER_TYPE_MAP.get(tool_name, tool_name)
    component_id = f"comp-{uuid.uuid4().hex[:8]}"

    if tool_name == "render_task_approval":
        raw_steps = args.get("steps", [])
        # Normalize steps: LLMs sometimes send flat strings instead of {id, text} objects
        normalized_steps = []
        for i, step in enumerate(raw_steps):
            if isinstance(step, str):
                normalized_steps.append({"id": i + 1, "text": step})
            elif isinstance(step, dict):
                normalized_steps.append({
                    "id": step.get("id", i + 1),
                    "text": step.get("text", str(step)),
                })
            else:
                normalized_steps.append({"id": i + 1, "text": str(step)})
        properties = {
            "title": args.get("title", "Task Plan"),
            "steps": normalized_steps,
            "reorderable": True,
        }
        actions = [
            {"id": "approve", "label": "Approve", "type": "approve"},
            {"id": "reject", "label": "Reject", "type": "reject"},
        ]
    elif tool_name == "render_profile_card":
        properties = {
            "facts": args.get("facts", []),
        }
        actions = []
    elif tool_name == "render_screenshot":
        properties = {
            "image": args.get("image", ""),
            "caption": args.get("caption"),
        }
        actions = []
    elif tool_name == "render_confirm_action":
        properties = {
            "action": args.get("action", ""),
            "actionId": args.get("actionId", component_id),
        }
        actions = [
            {"id": "allow", "label": "Allow", "type": "allow"},
            {"id": "deny", "label": "Deny", "type": "deny"},
        ]
    else:
        properties = args
        actions = []

    return {
        "version": "0.8",
        "components": [
            {
                "id": component_id,
                "type": component_type,
                "properties": properties,
                "parentId": None,
                "actions": actions if actions else None,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Conversation history helpers
# ---------------------------------------------------------------------------

def _strip_screenshots(content: str | list[dict[str, Any]] | dict[str, Any]) -> Any:
    """Strip base64 screenshot data from message content before saving to Firestore."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        cleaned = []
        for block in content:
            if isinstance(block, dict):
                # Strip base64 image data from tool results
                if block.get("type") == "tool_result":
                    c = block.get("content", "")
                    if isinstance(c, str) and len(c) > 10000:
                        block = {**block, "content": "[large result stripped]"}
                # Strip screenshot image data
                if "image" in str(block) and len(str(block)) > 10000:
                    block = {**block, "content": "[screenshot captured]"} if "content" in block else block
            cleaned.append(block)
        return cleaned
    return content


def _append_to_history(role: str, content: str | list[dict[str, Any]]) -> None:
    """Append a message to in-memory history and persist to Firestore if available."""
    global _conversation_history
    _conversation_history.append({"role": role, "content": content})

    # Trim to max history — find a safe cut point that doesn't break
    # tool_use/tool_result pairs or start with an assistant message
    if len(_conversation_history) > MAX_HISTORY_MESSAGES:
        trimmed = _conversation_history[-MAX_HISTORY_MESSAGES:]
        # Walk forward to find a user message that isn't a tool_result
        # (safe conversation boundary)
        for i in range(len(trimmed)):
            msg = trimmed[i]
            if msg["role"] != "user":
                continue
            # Skip bare tool_result messages (they need the preceding tool_use)
            content = msg.get("content", "")
            if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                continue
            trimmed = trimmed[i:]
            break
        _conversation_history = trimmed

    # Persist to Firestore
    if _user_uid:
        try:
            from src.db.chat_repository import append_message
            append_message(_user_uid, _chat_session_id, role, _strip_screenshots(content))
        except Exception as e:
            print(f"[orchestrator] Failed to save message to Firestore: {e}")


def _load_history_from_firestore() -> None:
    """Load conversation history from Firestore on startup."""
    global _conversation_history
    if not _user_uid:
        return
    try:
        from src.db.chat_repository import get_messages
        messages = get_messages(_user_uid, _chat_session_id)
        if messages:
            _conversation_history = messages[-MAX_HISTORY_MESSAGES:]
            print(f"[orchestrator] Loaded {len(_conversation_history)} messages from Firestore")
    except Exception as e:
        print(f"[orchestrator] Could not load chat history: {e}")


# ---------------------------------------------------------------------------
# Episodic memory logging + daily tracking
# ---------------------------------------------------------------------------

def _log_episodic_event(task: str) -> None:
    """Log a completed task to memory. Never raises.

    Phase 6: single unified path — canonical FOL API boundary + local
    episodic.md mirror (the store the prompt builder reads), scrubbed once.
    """
    try:
        summary = task[:200] if len(task) > 200 else task
        memory_record_activity(
            summary,
            category="agent_action",
            source="orchestrator",
        )
    except Exception as exc:
        print(f"[orchestrator] Failed to log episodic event: {exc}")


def _log_daily_activity(summary: str, category: str = "daily") -> None:
    """Log a daily activity event. Used by daily tracker and context engine.
    
    Args:
        summary: What the user was doing (e.g. "Coding in VS Code - FOL project")
        category: "daily" | "work" | "learning" | "browsing"
    """
    try:
        memory_record_activity(
            summary,
            category=category,
            source="daily_tracker",
        )
    except Exception as exc:
        print(f"[orchestrator] Failed to log daily activity: {exc}")


def _get_context_summary() -> str:
    """Build a compact summary of the current conversation for the LLM.
    
    This is injected into EVERY request so the model NEVER forgets.
    """
    parts = []
    
    # 1. What we've talked about
    user_messages = [
        m["content"] for m in _conversation_history 
        if m.get("role") == "user" 
        and (isinstance(m.get("content"), str))
    ]
    if user_messages:
        if len(user_messages) == 1:
            parts.append(f"User's request: \"{user_messages[0][:100]}\"")
        else:
            parts.append(f"This is message {len(user_messages)} in the conversation.")
            parts.append(f"Last user message: \"{user_messages[-1][:100]}\"")
    
    # 2. What's the current state
    parts.append(f"Current state: {current_job['state']}")
    
    # 3. Today's date (so the model knows the time context)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    parts.append(f"Today: {now.strftime('%A, %B %d, %Y')}")
    parts.append(f"Current time: {now.strftime('%H:%M UTC')}")
    
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Agent loop — streaming (for POST /chat SSE)
# ---------------------------------------------------------------------------

def _chunk_final_text(text: str, words_per_chunk: int = 4) -> list[str]:
    """Split the final answer into small word-groups so the UI keeps its
    natural streaming/typing feel while the text is already fully sanitized.

    Every chunk except the last keeps its trailing separator space so that
    concatenating the yielded chunks reproduces the original text exactly
    (splitting on " " consumes the inter-word spaces).
    """
    words = text.split(" ")
    chunks = [" ".join(words[i:i + words_per_chunk])
              for i in range(0, len(words), words_per_chunk)] or [text]
    return [(c + " ") if i < len(chunks) - 1 else c
            for i, c in enumerate(chunks)]


async def run_agent_loop_streaming(task: str, max_steps: int = 15, source: str = "user"):
    """
    Streaming agentic loop using Anthropic SDK. Yields (event_type, data)
    tuples for SSE — same format the SwiftUI app already handles.
    source: "user" for direct chat, "suggestion" for accepted proactive suggestions.
    """
    # Auto-route task to the best agent
    agent_type = _auto_route_agent(task)
    
    yield ("state", {"state": "thinking"})

    _append_to_history("user", task)
    messages: list = list(_conversation_history)
    
    # Inject context at the START so model ALWAYS knows context
    context_msgs = build_context_messages()
    messages = context_msgs + messages

    # Phase 4 — canonical memory retrieval BEFORE execution (single RAG path).
    try:
        memory_ctx = await asyncio.to_thread(memory_retrieve_context, task)
        if memory_ctx:
            messages.insert(0, {"role": "user", "content": "[MEMORY] " + memory_ctx})
    except Exception:
        pass

    # Build agent-specific system prompt
    agent_tools = _select_tools_for_task(task, agent_type)
    agent_suffix = _get_agent_prompt_suffix(agent_type)
    system_prompt = build_system_prompt()
    if agent_suffix:
        system_prompt += f"\n\n---\n\n{agent_suffix}"

    # Loop guard: tracks CONSECUTIVE identical tool calls (see non-streaming loop).
    last_call_sig: str | None = None
    consecutive_calls: int = 0

    # Response Formatter state: tools executed so far (used to build a natural
    # confirmation if the model returns no final text) + the user's language.
    executed_tools: list[tuple[str, dict]] = []
    language = detect_language(task)

    for step in range(max_steps):
        print(f"[orchestrator] Agent step {step + 1}/{max_steps}")
        had_error = False
        stop_reason = None
        text_content = ""
        tool_calls = []

        async for event_type, event_data in call_claude_streaming(messages, system_prompt, tools=agent_tools):
            if event_type == "token":
                # Buffer text — intermediate text (narration before tool calls,
                # agent reasoning, stray JSON) is INTERNAL and never streamed.
                # Only the final turn's answer reaches the user, through the
                # Response Formatter (see the end_turn branch below).
                text_content += event_data["text"]
            elif event_type == "_tool_use":
                tool_calls.append(event_data)
            elif event_type == "_done":
                stop_reason = event_data["stop_reason"]
            elif event_type == "error":
                yield ("error", {"message": humanize_error(event_data, language)})
                had_error = True
                break

        if had_error:
            yield ("state", {"state": "error"})
            async with job_lock:
                current_job["state"] = "error"
            return

        # Build assistant message for conversation history
        content_blocks = []
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})
        for tc in tool_calls:
            content_blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
        messages.append({"role": "assistant", "content": content_blocks})
        _append_to_history("assistant", content_blocks)

        # If no tool calls, we're done — this turn's text IS the final answer.
        # Run it through the Response Formatter so any tool-call JSON that a
        # model still emitted as text can never reach the user, and so the
        # response is always a clean non-empty string.
        if stop_reason == "end_turn" or not tool_calls:
            final_text = format_final_response(text_content, executed_tools, language)
            for chunk in _chunk_final_text(final_text):
                yield ("token", {"text": chunk})
            yield ("state", {"state": "complete", "message": final_text})
            async with job_lock:
                current_job["state"] = "complete"
            try:
                await asyncio.to_thread(_log_episodic_event, task)
            except Exception:
                pass
            return

        # Execute each tool call
        yield ("state", {"state": "working"})
        async with job_lock:
            current_job["state"] = "working"

        tool_results = []
        for tc in tool_calls:
            fn_name = tc["name"]
            fn_args = tc["input"]

            # Loop guard: N consecutive identical calls → abort to avoid infinite loop
            sig = _tool_call_signature(fn_name, fn_args)
            if sig == last_call_sig:
                consecutive_calls += 1
            else:
                last_call_sig = sig
                consecutive_calls = 1
            if consecutive_calls > MAX_REPEATED_TOOL_CALLS:
                msg = (("Похоже, я застрял, повторяя одно и то же действие. "
                        "Останавливаюсь — попробуйте сформулировать задачу иначе.")
                       if language == "ru" else
                       ("I seem to be stuck repeating the same action. Stopping now — "
                        "try rephrasing your request."))
                print(f"[orchestrator] Loop guard: {fn_name} repeated {consecutive_calls}x")
                # Close out this batch so conversation history stays valid —
                # placeholder tool_results for the calls we did NOT execute.
                for remaining_tc in tool_calls[len(tool_results):]:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": remaining_tc["id"],
                        "content": json.dumps({"status": "aborted", "reason": "loop_guard"}),
                    })
                messages.append({"role": "user", "content": tool_results})
                _append_to_history("user", tool_results)
                yield ("token", {"text": msg})
                yield ("state", {"state": "complete", "message": msg})
                async with job_lock:
                    current_job["state"] = "complete"
                try:
                    await asyncio.to_thread(_log_episodic_event, task)
                except Exception:
                    pass
                return

            print(f"[orchestrator]   Tool: {fn_name}({fn_args})")

            # Emit a coarse, user-safe activity status — never the tool name
            # or its arguments. Internal details stay internal.
            activity_cat, activity_label = activity_for_tool(fn_name, language)
            if activity_label:
                yield ("activity", {"category": activity_cat, "label": activity_label})

            if fn_name.startswith("render_"):
                # render_* tools ARE the response — an A2UI component. Only this
                # SSE-specific emission stays here; execution still goes through
                # the canonical registry handler (see execute_tool_call).
                a2ui_payload = convert_to_a2ui(fn_name, fn_args)
                yield ("component", {"a2ui": a2ui_payload})
                result_str = json.dumps({"status": "rendered", "awaiting_user_action": True})
            else:
                # Phase 5 — single dispatch path: gate → validate → registry
                # handler. The ConfirmationGate runs inside execute_tool_call,
                # so every tool (including sync_cookies) is code-enforced.
                result_str = await execute_tool_call(fn_name, fn_args)

            # Remember what ran so the Response Formatter can produce a natural
            # confirmation if the model ends up returning no final text.
            executed_tools.append((fn_name, fn_args))

            try:
                action_result = json.loads(result_str)
            except (json.JSONDecodeError, TypeError):
                action_result = {"result": result_str}
            async with job_lock:
                current_job["actions"].append({
                    "step": step + 1, "type": "tool_call",
                    "tool": fn_name, "args": fn_args,
                    "result": action_result,
                })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": result_str,
            })

        # Add tool results and loop back for next Claude call
        messages.append({"role": "user", "content": tool_results})
        _append_to_history("user", tool_results)
        yield ("state", {"state": "thinking"})
        async with job_lock:
            current_job["state"] = "thinking"

    # Exhausted max_steps — summarize what actually ran, in natural language.
    final_text = format_final_response(None, executed_tools, language)
    yield ("token", {"text": final_text})
    yield ("state", {"state": "complete", "message": final_text})
    async with job_lock:
        current_job["state"] = "complete"
    try:
        await asyncio.to_thread(_log_episodic_event, task)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Profile + anticipatory setup (kept from original)
# ---------------------------------------------------------------------------

async def handle_profile(name: str) -> dict:
    """Profile a person using Tavily web search + Claude summarization."""
    results = await asyncio.to_thread(call_tavily, f"{name} professional background work")
    if "error" in results:
        return results

    search_content = results.get("answer", "")
    if not search_content:
        snippets = [r.get("content", "") for r in results.get("results", [])]
        search_content = "\n".join(snippets[:3])

    try:
        result = await llm_acompletion(
            messages=[{"role": "user", "content": f"Person: {name}\n\nSearch results:\n{search_content}"}],
            system="Summarize this person's professional profile as JSON: name, title, company, interests (array), recent_activity (string), bio (2-3 sentences).",
            max_tokens=1024,
        )
        content = result.get("content", "")
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        return json.loads(content.strip())
    except Exception:
        return {"name": name, "raw_search": search_content}


async def handle_anticipatory_setup(profile: dict) -> list:
    """Set up the twin's desktop based on the user's profile (anticipatory twin)."""
    interests = profile.get("interests", [])
    name = profile.get("name", "the user")
    company = profile.get("company", "")
    title = profile.get("title", "")

    task = (
        f"Set up this desktop for {name}"
        f"{f', {title} at {company}' if title and company else ''}. "
        f"Their interests include: {', '.join(interests) if interests else 'general technology'}. "
        "Open Chrome with 2-3 tabs related to their interests. "
        "Open Notes and create a new note titled 'Tasks for today' with 3 relevant task suggestions. "
        "Make the desktop look like it belongs to this person."
    )

    return await run_agent_loop(task, max_steps=20)


# ---------------------------------------------------------------------------
# Suggestion triggers (async wrappers)
# ---------------------------------------------------------------------------

async def _check_pattern_suggestions() -> None:
    """Run pattern detection in a thread and broadcast any suggestions."""
    try:
        # Snapshot to avoid race with /reset clearing the list mid-iteration
        suggestions = await asyncio.to_thread(
            pattern_trigger, list(_conversation_history), cached_profile
        )
        for suggestion in suggestions:
            await broadcast_event("suggestion", suggestion)
    except Exception as e:
        print(f"[orchestrator] Pattern trigger error: {e}")


# ---------------------------------------------------------------------------
# Ambient awareness loop (Layer 3)
# ---------------------------------------------------------------------------

ambient_loop_task: asyncio.Task | None = None
ambient_interval: float = 30.0


async def _ambient_loop() -> None:
    """Background task: runs ambient_tick every ambient_interval seconds."""
    global ambient_interval
    failure_backoff = 30.0
    await asyncio.sleep(10)  # stabilize before first tick

    while True:
        try:
            await asyncio.sleep(ambient_interval)
            if current_job["state"] in ("thinking", "working"):
                continue
            if cached_profile is None:
                continue
            # Snapshot to avoid race with /reset clearing the list mid-iteration
            suggestions = await asyncio.to_thread(
                ambient_tick, list(_conversation_history), cached_profile
            )
            for suggestion in suggestions:
                await broadcast_event("suggestion", suggestion)
            failure_backoff = 30.0
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[orchestrator] Ambient loop error: {e}")
            failure_backoff = min(failure_backoff * 2, 120.0)
            await asyncio.sleep(failure_backoff)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle."""
    global _google_access_token, _user_uid, _user_name, _chat_session_id, ambient_loop_task

    llm_model = os.environ.get("LLM_MODEL", "")
    if llm_model and llm_model.startswith("ollama/"):
        print(f"[orchestrator] Using local model: {llm_model} (no API key needed)")
    elif not llm_model:
        print("[orchestrator] INFO: LLM_MODEL defaults to claude-sonnet-4-20250514. Set ANTHROPIC_API_KEY or LLM_MODEL=ollama/...")
    elif "ollama/" not in llm_model:
        # Cloud model configured — check if API key is available
        from llm_bridge import _get_api_key_for_model as _check_key
        if not _check_key(llm_model):
            print(f"[orchestrator] WARNING: Model {llm_model} may need an API key!")
    # Log the full model chain (LLM_MODEL + LLM_FALLBACK_MODELS) so startup
    # shows exactly which models the assistant can fall back to. The chain is
    # resolved by the canonical FOL LLMRouter (via llm_bridge) — Phase 3.
    try:
        from llm_bridge import _get_model_chain as _llm_chain, available_providers as _providers
        chain = _llm_chain()
        if chain:
            print(f"[orchestrator] Model chain: {' -> '.join(chain)}")
            print(f"[orchestrator] LLM router: canonical LiteLLMRouter (providers: {', '.join(_providers())})")
        else:
            print("[orchestrator] WARNING: No usable LLM model — set LLM_MODEL (and optionally LLM_FALLBACK_MODELS) with a valid API key")
    except Exception as e:
        print(f"[orchestrator] Could not inspect model chain: {e}")
    if not TAVILY_API_KEY:
        print("[orchestrator] TAVILY_API_KEY not set — web search disabled")

    # Try to load Google OAuth token from src/auth for productivity tools
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from src.auth.token_store import get_latest_session
        result = get_latest_session()
        if result:
            _, token_data = result
            _google_access_token = token_data.google_access_token
            _user_uid = token_data.email
            _user_name = token_data.name
            _chat_session_id = uuid.uuid4().hex
            print(f"[orchestrator] Google OAuth loaded for: {token_data.name}")
            print(f"[orchestrator] Chat session: {_chat_session_id[:8]}... (user: {_user_uid})")
        else:
            print("[orchestrator] No Google auth session found. Productivity tools will need auth first.")
    except Exception as e:
        print(f"[orchestrator] Could not load Google auth: {e}. Productivity tools disabled.")

    # Clear stale browser-use session from previous app run
    try:
        result = await asyncio.to_thread(call_agent_server, "/browser/close", {})
        print(f"[orchestrator] Browser session cleared on startup")
    except Exception:
        print("[orchestrator] Could not clear browser session (agent-server may not be running)")

    print(f"[orchestrator] Starting on port {PORT}")
    print(f"[orchestrator] Agent Server expected at {AGENT_SERVER_URL}")
    # Phase 6: validate the transport table against the canonical registry.
    try:
        problems = endpoint_map_problems()
        if problems:
            for p in problems:
                print(f"[orchestrator] TRANSPORT WARNING: {p}")
        elif problems is None:
            print("[orchestrator] Endpoint map validation unavailable — skipped")
        else:
            print(f"[orchestrator] Tool→endpoint map validated ({len(TOOL_ENDPOINT_MAP)} tools)")
    except Exception as e:
        print(f"[orchestrator] Endpoint map validation skipped: {e}")
    print(f"[orchestrator] Tools: {len(ALL_TOOLS)} ({len(BROWSER_TOOLS)} browser, {len(DESKTOP_TOOLS)} desktop, {len(UI_TOOLS)} UI, {len(PRODUCTIVITY_TOOLS)} productivity)")

    # ==================================================================
    # Obsidian Living Memory — авто-инициализация на старте
    # ==================================================================
    try:
        obsidian_ok = await asyncio.to_thread(check_obsidian_connection)
        if obsidian_ok:
            print("[orchestrator] Obsidian vault connected — initialising living memory...")

            # 1. Создать структуру папок в vault (Profile/, Knowledge/, Daily/, etc.)
            await asyncio.to_thread(init_obsidian_vault)
            print("[orchestrator]   ✓ Vault structure initialised")

            # 2. Создать сегодняшнюю daily note
            daily_path = await asyncio.to_thread(ensure_daily_note)
            print(f"[orchestrator]   ✓ Daily note created: {daily_path}")

            # 3. Синхронизировать существующие файлы из ~/.secondself/ → Obsidian
            sync_result = await asyncio.to_thread(sync_to_obsidian)
            synced = [k for k, v in sync_result.items() if v == "synced"]
            if synced:
                print(f"[orchestrator]   ✓ Synced to Obsidian: {', '.join(synced)}")

            print("[orchestrator] Obsidian living memory is active")
        else:
            print(
                "[orchestrator] Obsidian not connected — install Local REST API plugin "
                "and set OBSIDIAN_API_KEY in .env for living memory"
            )
    except Exception as obs_err:
        print(f"[orchestrator] Obsidian init skipped: {obs_err}")

    ambient_loop_task = asyncio.create_task(_ambient_loop())
    print("[orchestrator] Ambient suggestion loop started (30s interval)")

    yield

    if ambient_loop_task:
        ambient_loop_task.cancel()
    print("[orchestrator] Shutting down")


# ---------------------------------------------------------------------------
# Phase 5 — attach the canonical registry handlers (single dispatch mechanism)
# ---------------------------------------------------------------------------
# The registry is now the single source of tool execution: every executable
# tool has a handler attached here (delegating to the proven host functions
# above). execute_tool_call() is a thin wrapper over gate → validate →
# registry.execute().


def _install_tool_handlers() -> int:
    """Attach the canonical handlers to the registry. Returns count attached."""
    from tool_handlers import HandlerContext, build_handlers

    ctx = HandlerContext(
        call_agent_server=call_agent_server,
        # Resolve call_fol_api through the module global at call time so the
        # handler always uses the live function (tests patch server.call_fol_api
        # and must see the patched version). Identical behavior in production.
        call_fol_api=lambda *args, **kwargs: call_fol_api(*args, **kwargs),
        execute_productivity_tool=execute_productivity_tool,
        execute_memory_tool=execute_memory_tool,
        get_all_profile_info=_get_all_profile_info,
        execute_cookie_sync=_execute_cookie_sync,
        telegram_send=telegram_send,
        whatsapp_send=whatsapp_send,
        activate_native_app=activate_native_app,
        get_google_token=lambda: _google_access_token,
        try_reload_google_token=_try_reload_google_token,
        tavily_api_key=TAVILY_API_KEY,
        endpoint_map=TOOL_ENDPOINT_MAP,
        browser_nav_tools=BROWSER_NAV_TOOLS,
        cookie_state=_cookie_state,
    )
    handlers = build_handlers(ctx)
    attached = get_orchestrator_registry().attach_handlers(handlers)
    missing = sorted(set(handlers) - set(get_orchestrator_registry().names()))
    print(f"[orchestrator] Registry handlers attached: {attached}/{len(handlers)}"
          + (f" (unregistered: {missing})" if missing else ""))
    return attached


_install_tool_handlers()

app = FastAPI(title="FOL Orchestrator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(json.JSONDecodeError)
async def json_decode_error_handler(request: Request, exc: json.JSONDecodeError):
    """Handle malformed JSON request bodies."""
    return JSONResponse(status_code=400, content={"error": f"Invalid JSON: {exc.msg}"})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Health check — also pings the Agent Server with a GET request."""
    try:
        agent_status = await asyncio.to_thread(call_agent_server, "/health", None, "GET")
    except Exception as e:
        agent_status = {"status": "error", "error": str(e)}
    obsidian_status = await asyncio.to_thread(check_obsidian_connection)
    return {
        "status": "ok",
        "agent_server": agent_status,
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "tavily_configured": bool(TAVILY_API_KEY),
        "obsidian_connected": obsidian_status,
    }


@app.get("/fol/status")
async def fol_status():
    """Check FOL API server status (port 8754)."""
    health = await asyncio.to_thread(check_fol_health)
    return health


@app.post("/fol/command")
async def fol_command(body: dict):
    """Send a JARVIS command to the FOL API server."""
    command = body.get("command", "")
    if not command:
        return JSONResponse({"error": "Empty command"}, status_code=400)
    health = await asyncio.to_thread(check_fol_health)
    if health.get("status") != "healthy":
        return JSONResponse({"error": "FOL server not running", "fol_health": health}, status_code=503)
    result = await asyncio.to_thread(call_fol_api, "/api/chat", {"message": command})
    return result


@app.get("/status")
async def status():
    """Return the current job state."""
    try:
        fol_health = await asyncio.to_thread(check_fol_health)
    except Exception:
        fol_health = {"status": "unreachable"}
    async with job_lock:
        return {
            "id": current_job["id"],
            "state": current_job["state"],
            "task": current_job["task"],
            "actions_count": len(current_job["actions"]),
            "started_at": current_job["started_at"],
            "queued_messages": len(current_job["message_queue"]),
            "current_agent": _AGENT_REGISTRY.get(_current_agent_type, {}).get("name", "General"),
            "available_agents": [a.value for a in AgentType],
            "fol_status": fol_health,
        }


@app.get("/api/runtime")
async def runtime():
    """Phase 7: full runtime observability for the Dashboard.

    Exposes, without any live LLM calls or secret values:
      - LLM model chain (primary + fallbacks) + configured providers
      - fallback log (provider failures, no secrets)
      - current agent, job state, task
      - recent tool calls (names + outcomes only) and recent errors
      - uptime, memory status, service availability flags
    """
    from llm_bridge import (
        _get_model_chain,
        available_providers,
        fallback_log,
        last_fallback_error,
        _get_api_key_for_model,
    )
    chain: list = []
    providers: list = []
    fallbacks: list = []
    try:
        chain = _get_model_chain()
    except Exception as e:
        _record_error("llm_config", str(e))
    try:
        providers = available_providers()
    except Exception:
        providers = []
    try:
        fallbacks = fallback_log()
    except Exception:
        fallbacks = []

    # Cheap, configuration-only LLM status (never makes a live LLM call on a
    # dashboard poll — that would burn tokens every 3 seconds). The primary
    # model is "ready" when a key is configured (or it is a local ollama model).
    llm_status = "not_configured"
    try:
        if chain:
            primary = chain[0]
            if primary.startswith("ollama/") or primary.startswith("local/"):
                llm_status = "ready_local"
            elif _get_api_key_for_model(primary):
                llm_status = "ready"
            else:
                llm_status = "missing_key"
    except Exception:
        llm_status = "unknown"

    agent_health: dict = {}
    try:
        agent_health = await asyncio.to_thread(call_agent_server, "/health", None, "GET")
    except Exception as e:
        agent_health = {"status": "error", "error": str(e)}

    memory = {}
    for name in ("identity", "preferences", "episodic"):
        p = _MEMORY_DIR / f"{name}.md"
        try:
            memory[name] = {"exists": p.exists(), "size": p.stat().st_size if p.exists() else 0}
        except OSError:
            memory[name] = {"exists": False, "size": 0}

    try:
        obsidian_connected = await asyncio.to_thread(check_obsidian_connection)
    except Exception:
        obsidian_connected = False

    try:
        fol_health = await asyncio.to_thread(check_fol_health)
    except Exception:
        fol_health = {"status": "unreachable"}

    async with job_lock:
        return {
            "uptime_seconds": int(time.time() - _START_TIME),
            "llm": {
                "model_chain": chain,
                "providers": providers,
                "fallback_log": fallbacks[-10:],
                "last_fallback_error": last_fallback_error(),
                "status": llm_status,
                "tavily_configured": bool(TAVILY_API_KEY),
            },
            "agent": {
                "current": _AGENT_REGISTRY.get(_current_agent_type, {}).get("name", "General"),
                "type": _current_agent_type.value,
            },
            "job": {
                "id": current_job["id"],
                "state": current_job["state"],
                "task": current_job["task"],
                "actions_count": len(current_job["actions"]),
                "started_at": current_job["started_at"],
            },
            "services": {
                "agent_server": agent_health,
                "fol": fol_health,
            },
            "memory": {
                "files": memory,
                "obsidian_connected": obsidian_connected,
            },
            "recent_tool_calls": list(reversed(_tool_call_log[-20:])),
            "recent_errors": list(reversed(_error_log[-20:])),
        }


@app.post("/command")
async def command(request: Request):
    """Legacy command endpoint — runs agent loop synchronously and returns JSON."""
    _, task_or_err = await _require_body_field(request, "task")
    if isinstance(task_or_err, JSONResponse):
        return task_or_err
    task: str = task_or_err
    print(f"[orchestrator] Received command: {task}")
    actions = await run_agent_loop(task)
    # Response Formatter: expose only a clean natural-language response.
    # Never the raw tool-call JSON that small models sometimes emit as text.
    response = ""
    for action in reversed(actions):
        if action.get("type") == "complete" and action.get("message"):
            response = str(action["message"])
            break
    if not response:
        tools = [(a["tool"], a.get("args", {}))
                 for a in actions if a.get("type") == "tool_call"]
        response = format_final_response(None, tools, detect_language(task), user_input=task)
    return {"task": task, "actions": actions, "response": response}


@app.post("/profile")
async def profile(request: Request):
    """Profile a person using Tavily web search."""
    _, name_or_err = await _require_body_field(request, "name")
    if isinstance(name_or_err, JSONResponse):
        return name_or_err
    name: str = name_or_err
    print(f"[orchestrator] Profiling: {name}")
    result = await handle_profile(name)
    global cached_profile
    cached_profile = result

    # Fire profile-based suggestions (Layer 1) as background task
    # so /profile response isn't blocked by the suggestion LLM call
    asyncio.create_task(_fire_profile_suggestions(result))

    return result


# ---------------------------------------------------------------------------
# Agent management endpoint
# ---------------------------------------------------------------------------

@app.get("/agent")
async def get_current_agent():
    """Get the current active agent type."""
    agent_config = _AGENT_REGISTRY.get(_current_agent_type, {})
    return {
        "current": _current_agent_type.value,
        "name": agent_config.get("name", "General"),
        "available": [a.value for a in AgentType],
    }


@app.post("/agent/switch")
async def switch_agent(request: Request):
    """Manually switch to a specific agent type."""
    global _current_agent_type
    body = await request.json()
    agent_name = body.get("agent", "").lower().strip()
    
    if not agent_name:
        return JSONResponse(status_code=400, content={"error": "missing 'agent' field"})
    
    try:
        new_type = AgentType(agent_name)
    except ValueError:
        valid = [a.value for a in AgentType]
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid agent '{agent_name}'. Valid: {valid}"}
        )
    
    old_type = _current_agent_type
    _current_agent_type = new_type
    print(f"[orchestrator] Agent switched: {old_type.value} -> {new_type.value}")
    
    return {
        "status": "ok",
        "previous": old_type.value,
        "current": new_type.value,
        "name": _AGENT_REGISTRY.get(new_type, {}).get("name", "General"),
    }


async def _fire_profile_suggestions(profile_data: dict) -> None:
    """Background: generate and broadcast the best profile suggestion."""
    try:
        suggestions = await asyncio.to_thread(profile_trigger, profile_data)
        if suggestions:
            best = max(suggestions, key=lambda s: s.get("confidence", 0))
            await broadcast_event("suggestion", best)
    except Exception as e:
        print(f"[orchestrator] Profile suggestion error: {e}")


@app.post("/setup-twin")
async def setup_twin(request: Request):
    """Set up the twin desktop based on a profile."""
    _, profile_or_err = await _require_body_field(request, "profile")
    if isinstance(profile_or_err, JSONResponse):
        return profile_or_err
    profile_data: dict = profile_or_err
    print(f"[orchestrator] Setting up twin for: {profile_data.get('name', 'unknown')}")
    actions = await handle_anticipatory_setup(profile_data)
    return {"actions": actions}


@app.post("/demo")
async def demo(request: Request):
    """Full demo loop: name -> profile -> setup -> ready for commands."""
    _, name_or_err = await _require_body_field(request, "name")
    if isinstance(name_or_err, JSONResponse):
        return name_or_err
    name: str = name_or_err
    print(f"[orchestrator] === DEMO LOOP for: {name} ===")

    # Step 1: Profile
    print("[orchestrator] Step 1: Profiling...")
    profile_data = await handle_profile(name)

    # Step 2: Anticipatory setup
    print("[orchestrator] Step 2: Setting up twin...")
    setup_actions = await handle_anticipatory_setup(profile_data)

    return {
        "name": name,
        "profile": profile_data,
        "setup_actions": setup_actions,
        "status": "ready_for_commands",
    }


async def _process_queued_message(message: str) -> None:
    """
    Background task that runs the streaming agent loop for a queued message.

    The original caller already received a 202 (queued) response, so there is
    no SSE stream to push events to.  We simply consume the async generator to
    drive tool execution and state transitions.  When the loop finishes we
    return the job to idle and check for more queued work.
    """
    print(f"[orchestrator] Processing queued message: {message}")
    try:
        async for event_type, event_data in run_agent_loop_streaming(message, source="suggestion"):
            # Broadcast progress to /events so accepted suggestions are visible
            await broadcast_event(event_type, event_data)
    except Exception as exc:
        print(f"[orchestrator] Queued message error: {exc}")
        async with job_lock:
            current_job["state"] = "error"
    finally:
        async with job_lock:
            await set_job_state("idle")
            # Continue draining: if more messages are queued, kick off the next one.
            if current_job["message_queue"]:
                next_message = current_job["message_queue"].pop(0)
                await set_job_state("thinking", task=next_message)
                asyncio.create_task(_process_queued_message(next_message))


def _resolve_user_confirmation(message: str) -> None:
    """Resolve pending confirmation-gate actions from a user reply.

    Phase 4: the Swift ConfirmAction card replies with "Allowed: …" /
    "Denied: …" as a chat message; plain replies ("yes" / "да" / "no" / "нет")
    work too. The gate is code-enforced — the model can never approve its own
    actions. Every pending action with a matching signature becomes executable
    after approval; a denial clears the pending set.
    """
    try:
        gate = get_confirmation_gate()
        decision = gate.classify_user_decision(message)
        if decision == "approve":
            approved = gate.approve_all_pending()
            if approved:
                print(f"[orchestrator] Confirmation approved ({approved} action(s))")
        elif decision == "deny":
            denied = gate.deny_all_pending()
            if denied:
                print(f"[orchestrator] Confirmation denied ({denied} action(s))")
    except Exception as exc:
        print(f"[orchestrator] _resolve_user_confirmation failed: {exc}")


@app.post("/confirm")
async def confirm_action(request: Request):
    """Deterministic confirmation endpoint (Phase 4).

    Body: {"action_id": "act_…", "decision": "approve" | "deny"}

    This is the code-enforced confirmation gate: the UI (or an external
    caller) approves/denies a specific gated tool call by its action_id.
    The LLM can never call this endpoint — only the user/UI can.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON body"})

    action_id = str(body.get("action_id", ""))
    decision = str(body.get("decision", "")).lower()
    if not action_id:
        return JSONResponse(status_code=400, content={"error": "action_id required"})

    gate = get_confirmation_gate()
    if decision == "approve":
        ok = gate.approve(action_id)
    elif decision == "deny":
        ok = gate.deny(action_id)
    else:
        return JSONResponse(status_code=400, content={"error": "decision must be approve|deny"})

    if not ok:
        return JSONResponse(status_code=404, content={"error": "unknown or already-resolved action_id"})
    return JSONResponse(content={"status": decision, "action_id": action_id})


@app.post("/chat")
async def chat(request: Request):
    """
    SSE streaming endpoint. Accepts {"message": "..."} and returns
    a stream of server-sent events as the agent processes the task.
    """
    _, msg_or_err = await _require_body_field(request, "message")
    if isinstance(msg_or_err, JSONResponse):
        return msg_or_err
    message: str = msg_or_err

    # Normalize input for typo tolerance
    normalized = normalize_user_input(message)
    if normalized != message:
        print(f"[orchestrator] Normalized input: '{message[:60]}...' -> '{normalized[:60]}...'")
    message = normalized

    # Phase 4 — resolve pending deterministic confirmations from user replies
    # ("Allowed: …" / "yes" / "да"). The gate is code-enforced; the model can
    # never approve its own actions.
    _resolve_user_confirmation(message)

    # If we're busy, queue the message
    async with job_lock:
        if current_job["state"] not in ("idle", "complete", "error"):
            current_job["message_queue"].append(message)
            return JSONResponse(
                status_code=202,
                content={
                    "status": "queued",
                    "position": len(current_job["message_queue"]),
                    "message": "Agent is busy. Your message has been queued.",
                },
            )
        await set_job_state("thinking", task=message)

    print(f"[orchestrator] Chat message: {message}")

    async def event_stream():
        last_ping = time.time()
        try:
            # Response Formatter at the SSE boundary: tool_call/tool_result
            # events are dropped, JSON tool calls in tokens are held back and
            # never shown, and errors are humanized.
            async for event_type, event_data in sanitize_event_stream(
                run_agent_loop_streaming(message)
            ):
                sse_line = f"event: {event_type}\ndata: {json.dumps(event_data)}\n\n"
                yield sse_line
                last_ping = time.time()

                # Send pings during idle periods (handled between events)
                if time.time() - last_ping >= 3:
                    yield f"event: ping\ndata: {{}}\n\n"
                    last_ping = time.time()
        except Exception as e:
            print(f"[orchestrator] SSE stream error: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
            async with job_lock:
                current_job["state"] = "error"
        finally:
            # Fire pattern-based suggestions (Layer 2)
            asyncio.create_task(_check_pattern_suggestions())

            # Always return to idle state after stream ends
            async with job_lock:
                await set_job_state("idle")
                if current_job["message_queue"]:
                    next_message = current_job["message_queue"].pop(0)
                    await set_job_state("thinking", task=next_message)
                    asyncio.create_task(_process_queued_message(next_message))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Persistent SSE — GET /events (suggestion push channel)
# ---------------------------------------------------------------------------

@app.get("/events")
async def events(request: Request):
    """Persistent SSE stream for proactive suggestions."""
    client_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    event_clients.append(client_queue)
    print(f"[orchestrator] /events client connected ({len(event_clients)} total)")

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                    yield payload
                except asyncio.TimeoutError:
                    yield f"event: ping\ndata: {{}}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if client_queue in event_clients:
                event_clients.remove(client_queue)
            print(f"[orchestrator] /events client disconnected ({len(event_clients)} total)")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Suggestion response — accept/dismiss/modify
# ---------------------------------------------------------------------------

@app.post("/suggestion/respond")
async def suggestion_respond(request: Request):
    """Handle user response to a proactive suggestion. Logs reward, optionally starts job."""
    body = await request.json()
    suggestion_id = body.get("suggestion_id", "")
    action = body.get("action", "")

    if not suggestion_id or action not in ("accept", "dismiss", "modify"):
        return JSONResponse(status_code=400, content={
            "error": "Required: suggestion_id, action (accept/dismiss/modify)"
        })

    reward = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "suggestion_id": suggestion_id,
        "action": action,
        "modification": body.get("modification") if action == "modify" else None,
        "profile_name": cached_profile.get("name", "") if cached_profile else "",
        "conversation_length": len(_conversation_history),
    }
    try:
        rewards_path.parent.mkdir(parents=True, exist_ok=True)
        with open(rewards_path, "a") as f:
            f.write(json.dumps(reward) + "\n")
    except IOError as e:
        print(f"[orchestrator] WARNING: Failed to write reward: {e}")

    # Smart silence: adaptive backoff on consecutive dismissals
    global ambient_interval
    if action == "dismiss":
        recent_rewards = []
        try:
            if rewards_path.exists():
                with open(rewards_path) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            recent_rewards.append(json.loads(line))
        except (IOError, json.JSONDecodeError):
            pass
        consecutive = 0
        for r in reversed(recent_rewards):
            if r.get("action") == "dismiss":
                consecutive += 1
            else:
                break
        if consecutive >= 2:
            ambient_interval = min(ambient_interval * 2, 120.0)
            print(f"[orchestrator] Smart silence: {consecutive} dismissals, interval -> {ambient_interval}s")
    elif action == "accept":
        ambient_interval = 30.0

    await broadcast_event(f"suggestion_{action}ed" if action != "modify" else "suggestion_modified", {
        "id": suggestion_id,
    })

    if action in ("accept", "modify"):
        task_description = body.get("description", "")
        if action == "modify" and body.get("modification"):
            task_description = body["modification"]
        if task_description:
            async with job_lock:
                if current_job["state"] not in ("idle", "complete", "error"):
                    current_job["message_queue"].append(task_description)
                    return {"status": "queued", "position": len(current_job["message_queue"]), "message": "Got it, I'll do that next."}
                await set_job_state("thinking", task=task_description)
            asyncio.create_task(_process_queued_message(task_description))
            return {"status": "executing", "message": "On it!"}

    return {"status": "ok", "action": action}


@app.post("/auth/refresh")
async def auth_refresh():
    """Reload Google OAuth token after user signs in via the notch UI."""
    _try_reload_google_token()
    return {
        "status": "ok" if _google_access_token else "no_token",
        "user": _user_name,
        "has_google": _google_access_token is not None,
    }


@app.post("/reset")
async def reset():
    """Reset all state for demo transitions."""
    global _conversation_history, _chat_session_id, cached_profile
    async with job_lock:
        current_job["id"] = None
        current_job["state"] = "idle"
        current_job["task"] = None
        current_job["actions"] = []
        current_job["started_at"] = None
        current_job["message_queue"] = []
    _conversation_history = []
    _chat_session_id = uuid.uuid4().hex
    cached_profile = None
    _cookie_state.reset()
    print("[orchestrator] State reset to idle, conversation history cleared")
    return {"status": "ok", "state": "idle", "message": "State and conversation history cleared"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    uvicorn.run(app, host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
