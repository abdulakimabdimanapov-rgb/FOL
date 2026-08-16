"""Canonical tool catalog for the active orchestrator (Phase 4).

Every tool the streaming orchestrator exposes to the LLM is defined HERE as a
canonical ``ToolSpec`` — name, description, JSON schema, risk level,
confirmation requirement and category. ``build_orchestrator_registry()``
registers them all in the canonical ``ToolRegistry``, which becomes the single
source of truth for tool metadata. The legacy Anthropic tool dicts that used
to live in ``orchestrator/server.py``, ``orchestrator/productivity_tools.py``
and ``obsidian/tools.py`` are now derived from this catalog (see
``orchestrator/tool_registry.py``); the legacy dicts are preserved for other
consumers but are no longer the orchestrator's definition source.

Risk levels (canonical, code-enforced):
    low       — read-only / harmless
    medium    — affects local state in a reversible way
    high      — affects the system / user's data — confirmation required
    critical  — destructive or irreversible

High-risk tools are gated by the canonical ``ConfirmationGate`` — the model
cannot decide whether confirmation is needed.
"""

from __future__ import annotations

from typing import Any

from modules.tools.base import RiskLevel, ToolSpec
from modules.tools.registry import ToolRegistry


def _spec(
    name: str,
    description: str,
    schema: dict[str, Any],
    risk: str = "low",
    category: str = "general",
    confirm: bool = False,
) -> ToolSpec:
    """Build a canonical ToolSpec (risk as a string for readability)."""
    return ToolSpec(
        name=name,
        description=description,
        schema=schema,
        risk_level=RiskLevel(risk),
        requires_confirmation=confirm,
        category=category,
    )


# ---------------------------------------------------------------------------
# Browser tools (agent-browser / Chrome)
# ---------------------------------------------------------------------------

BROWSER_SPECS = [
    _spec(
        "browser_goto",
        "Navigate the browser to a URL. Use for any web task.",
        {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to"}}, "required": ["url"]},
        risk="medium", category="browser",
    ),
    _spec(
        "browser_click",
        "Click an element on the web page by its ref ID (from browser_snapshot).",
        {"type": "object", "properties": {"ref": {"type": "string", "description": "Element ref from snapshot, e.g. 'e3'"}}, "required": ["ref"]},
        risk="medium", category="browser",
    ),
    _spec(
        "browser_fill",
        "Fill a text input on the web page by its ref ID with the given text.",
        {"type": "object", "properties": {"ref": {"type": "string", "description": "Element ref, e.g. 'e5'"}, "text": {"type": "string", "description": "Text to type"}}, "required": ["ref", "text"]},
        risk="medium", category="browser",
    ),
    _spec(
        "browser_snapshot",
        "Get the current page structure with element refs. Call before clicking/filling.",
        {"type": "object", "properties": {}},
        risk="low", category="browser",
    ),
    _spec(
        "browser_text",
        "Get the text content of the current web page.",
        {"type": "object", "properties": {}},
        risk="low", category="browser",
    ),
    _spec(
        "browser_press",
        "Press a keyboard key in the browser (Enter, Tab, Escape, etc.).",
        {"type": "object", "properties": {"key": {"type": "string", "description": "Key to press"}}, "required": ["key"]},
        risk="medium", category="browser",
    ),
    _spec(
        "sync_cookies",
        "Sync cookies from the user's Chrome browser into the agent browser. Call this ONLY after the user approves cookie sync via render_confirm_action. This transfers authenticated sessions (Google, GitHub, etc.) so the agent can browse logged-in sites.",
        {"type": "object", "properties": {
            "profile": {"type": "string", "description": "Chrome profile to sync from — accepts display name (e.g. 'Work') or directory name (e.g. 'Profile 4'). Omit to auto-detect last-used."},
            "browser": {"type": "string", "description": "Browser name if ambiguous (e.g. 'Google Chrome', 'Arc'). Omit for Chrome."},
        }},
        risk="high", category="browser", confirm=True,
    ),
    _spec(
        "list_profiles",
        "List all available browser profiles the user can sync cookies from. Call this to show the user their options before syncing.",
        {"type": "object", "properties": {}},
        risk="low", category="browser",
    ),
]

# ---------------------------------------------------------------------------
# Desktop tools (native macOS apps + Safari + messaging)
# ---------------------------------------------------------------------------

DESKTOP_SPECS = [
    _spec(
        "open_app",
        "Open a macOS application by name. Native apps only (Notes, Finder, Calendar).",
        {"type": "object", "properties": {"name": {"type": "string", "description": "Application name"}}, "required": ["name"]},
        risk="medium", category="desktop",
    ),
    _spec(
        "close_app",
        "Quit a macOS application by name.",
        {"type": "object", "properties": {"name": {"type": "string", "description": "Application name"}}, "required": ["name"]},
        risk="medium", category="desktop",
    ),
    _spec(
        "drag",
        "Drag the mouse from one point to another (e.g. move a window or file).",
        {"type": "object", "properties": {
            "x1": {"type": "integer"}, "y1": {"type": "integer"},
            "x2": {"type": "integer"}, "y2": {"type": "integer"},
            "duration": {"type": "number", "description": "Drag duration in seconds (default 0.3)"}},
            "required": ["x1", "y1", "x2", "y2"]},
        risk="high", category="desktop", confirm=True,
    ),
    _spec(
        "clipboard_get",
        "Read the current clipboard text.",
        {"type": "object", "properties": {}},
        risk="low", category="desktop",
    ),
    _spec(
        "clipboard_set",
        "Set the clipboard text.",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        risk="medium", category="desktop",
    ),
    _spec(
        "notify",
        "Show a macOS notification banner.",
        {"type": "object", "properties": {"title": {"type": "string"}, "message": {"type": "string"}}, "required": ["title"]},
        risk="low", category="desktop",
    ),
    _spec(
        "type_text",
        "Type text using the keyboard. Native macOS apps only, not web pages.",
        {"type": "object", "properties": {"text": {"type": "string", "description": "Text to type"}}, "required": ["text"]},
        risk="high", category="desktop", confirm=True,
    ),
    _spec(
        "hotkey",
        "Press a keyboard shortcut in a native macOS app.",
        {"type": "object", "properties": {"keys": {"type": "array", "items": {"type": "string"}, "description": "Keys to press together"}}, "required": ["keys"]},
        risk="high", category="desktop", confirm=True,
    ),
    _spec(
        "click",
        "Click at x,y pixel coordinates. Native macOS apps only.",
        {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"]},
        risk="high", category="desktop", confirm=True,
    ),
    _spec(
        "screenshot",
        "Take a screenshot of the full desktop. Use sparingly.",
        {"type": "object", "properties": {}},
        risk="medium", category="desktop",
    ),
    _spec(
        "scroll",
        "Scroll the screen in a native macOS app.",
        {"type": "object", "properties": {"dy": {"type": "integer", "description": "Vertical scroll (positive=up, negative=down)"}}, "required": ["dy"]},
        risk="medium", category="desktop",
    ),
    _spec(
        "safari_goto",
        "Navigate Safari browser to a URL. Use for WhatsApp Web, Telegram Web, or any site where you need Safari instead of Chrome.",
        {"type": "object", "properties": {"url": {"type": "string", "description": "URL to navigate to"}}, "required": ["url"]},
        risk="medium", category="desktop",
    ),
    _spec(
        "safari_js",
        "Execute JavaScript in the current Safari tab. Use to interact with web pages (click buttons, read text, fill forms).",
        {"type": "object", "properties": {"javascript": {"type": "string", "description": "JavaScript code to execute"}}, "required": ["javascript"]},
        risk="high", category="desktop", confirm=True,
    ),
    _spec(
        "safari_get_url",
        "Get the current URL from the active Safari tab.",
        {"type": "object", "properties": {}},
        risk="low", category="desktop",
    ),
    _spec(
        "safari_get_text",
        "Get the visible text content of the current Safari page. Use to read page content.",
        {"type": "object", "properties": {}},
        risk="low", category="desktop",
    ),
    _spec(
        "send_telegram",
        "Activate Telegram Desktop and prepare to send a message. Opens Telegram and returns keyboard shortcuts for the AI to find the contact and send the message using type_text() and hotkey().",
        {"type": "object", "properties": {"contact": {"type": "string", "description": "Contact name or username to message"}, "message": {"type": "string", "description": "Message text to send"}}, "required": ["contact", "message"]},
        risk="medium", category="desktop",
    ),
    _spec(
        "send_whatsapp",
        "Activate WhatsApp Desktop and prepare to send a message. Opens WhatsApp and returns keyboard shortcuts for the AI to find the contact and send the message using type_text() and hotkey().",
        {"type": "object", "properties": {"contact": {"type": "string", "description": "Contact name as it appears in WhatsApp"}, "message": {"type": "string", "description": "Message text to send"}}, "required": ["contact", "message"]},
        risk="medium", category="desktop",
    ),
    _spec(
        "activate_app",
        "Bring a macOS application to the front. Use before starting to interact with any app via keyboard tools (type_text, hotkey).",
        {"type": "object", "properties": {"name": {"type": "string", "description": "Application name, e.g. 'Telegram', 'WhatsApp', 'Safari', 'Notes'"}}, "required": ["name"]},
        risk="low", category="desktop",
    ),
]

# ---------------------------------------------------------------------------
# UI tools (render A2UI components — low risk by design)
# ---------------------------------------------------------------------------

UI_SPECS = [
    _spec(
        "render_task_approval",
        "Render an interactive task approval card. Use BEFORE executing a multi-step plan. Include at least 2 steps.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Title for the plan card"},
            "steps": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}}, "required": ["id", "text"]}},
        }, "required": ["steps"]},
        risk="low", category="ui",
    ),
    _spec(
        "render_profile_card",
        "Render a profile card showing facts about the user for confirmation.",
        {"type": "object", "properties": {
            "facts": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
        }, "required": ["facts"]},
        risk="low", category="ui",
    ),
    _spec(
        "render_screenshot",
        "Render a screenshot preview card in the chat.",
        {"type": "object", "properties": {
            "image": {"type": "string", "description": "Base64-encoded JPEG"},
            "caption": {"type": "string"},
        }, "required": ["image"]},
        risk="low", category="ui",
    ),
    _spec(
        "render_confirm_action",
        "Render a confirmation dialog before an important action.",
        {"type": "object", "properties": {
            "action": {"type": "string", "description": "What you want to do"},
            "actionId": {"type": "string", "description": "Unique identifier"},
        }, "required": ["action"]},
        risk="low", category="ui",
    ),
]

# ---------------------------------------------------------------------------
# FOL JARVIS command (FOL API engine, port 8754)
# ---------------------------------------------------------------------------

FOL_SPECS = [
    _spec(
        "fol_command",
        "Execute a JARVIS-style command through the FOL engine (port 8754). "
        "FOL understands both English and Russian commands natively. "
        "Use for: taking screenshots, voice/TTS control, system info, "
        "battery/wifi/bluetooth status, memory operations, media control, "
        "volume/brightness adjustment, window management, lock/sleep, "
        "running terminal commands, browser interaction, and macOS control.\n\n"
        "EXAMPLES:\n"
        "  - 'screenshot' — take a screenshot\n"
        "  - 'what\\'s on screen' — analyze screen content\n"
        "  - 'system status' — show system info\n"
        "  - 'battery' — check battery level\n"
        "  - 'volume up 10' — increase volume\n"
        "  - 'play music' — play music\n"
        "  - 'lock' — lock the screen\n"
        "  - 'run ls -la' — execute terminal command\n"
        "  - 'open Safari' — launch application\n"
        "  - 'my profile' — show user profile\n"
        "  - 'заблокируй' — lock screen (Russian)\n"
        "  - 'прибавь громкость' — volume up (Russian)",
        {"type": "object", "properties": {
            "command": {"type": "string", "description": "Command text to send to FOL. Can be in English or Russian."},
        }, "required": ["command"]},
        risk="medium", category="fol", confirm=False,
    ),
]

# ---------------------------------------------------------------------------
# Productivity tools (Gmail / Calendar / Docs / web search)
# ---------------------------------------------------------------------------

PRODUCTIVITY_SPECS = [
    _spec(
        "send_email",
        "Send a new email on behalf of the user. Write the body in their voice. Only call after the user confirmed a draft, or if they said to send directly.",
        {"type": "object", "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body text, written in the user's voice"},
        }, "required": ["to", "subject", "body"]},
        risk="high", category="productivity", confirm=True,
    ),
    _spec(
        "draft_email",
        "Draft an email for the user to review before sending. Use this BEFORE send_email unless the user explicitly said to send directly.",
        {"type": "object", "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string", "description": "Email subject line"},
            "body": {"type": "string", "description": "Email body text, written in the user's voice"},
        }, "required": ["to", "subject", "body"]},
        risk="low", category="productivity",
    ),
    _spec(
        "reply_to_email",
        "Reply to an existing email thread. Use read_emails first to find the message_id and thread_id.",
        {"type": "object", "properties": {
            "message_id": {"type": "string", "description": "Gmail message ID (from read_emails)"},
            "thread_id": {"type": "string", "description": "Gmail thread ID (from read_emails)"},
            "body": {"type": "string", "description": "Reply body text"},
        }, "required": ["message_id", "thread_id", "body"]},
        risk="high", category="productivity", confirm=True,
    ),
    _spec(
        "read_emails",
        "Search and read the user's emails. Supports Gmail search syntax: 'from:john subject:meeting', 'is:unread', 'newer_than:1d'.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "limit": {"type": "integer", "description": "Max emails to return (default 5)"},
        }, "required": ["query"]},
        risk="low", category="productivity",
    ),
    _spec(
        "get_contact_info",
        "Look up a contact's email address by searching recent emails for their name.",
        {"type": "object", "properties": {
            "name": {"type": "string", "description": "The person's name to search for"},
        }, "required": ["name"]},
        risk="low", category="productivity",
    ),
    _spec(
        "summarize_emails",
        "Read and summarize a batch of emails. Use when the user asks for inbox overview or email summaries.",
        {"type": "object", "properties": {
            "query": {"type": "string", "description": "Gmail search query"},
            "limit": {"type": "integer", "description": "Max emails to summarize (default 10)"},
        }, "required": ["query"]},
        risk="low", category="productivity",
    ),
    _spec(
        "create_event",
        "Create a new Google Calendar event.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Event title"},
            "start": {"type": "string", "description": "Start time in ISO 8601"},
            "end": {"type": "string", "description": "End time in ISO 8601"},
            "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses"},
            "description": {"type": "string", "description": "Event description"},
            "location": {"type": "string", "description": "Event location"},
        }, "required": ["title", "start", "end"]},
        risk="medium", category="productivity",
    ),
    _spec(
        "update_event",
        "Update an existing Google Calendar event. Use list_events first to find the event_id.",
        {"type": "object", "properties": {
            "event_id": {"type": "string", "description": "Calendar event ID"},
            "title": {"type": "string"}, "start": {"type": "string"}, "end": {"type": "string"},
            "description": {"type": "string"}, "location": {"type": "string"},
        }, "required": ["event_id"]},
        risk="medium", category="productivity",
    ),
    _spec(
        "delete_event",
        "Delete a Google Calendar event.",
        {"type": "object", "properties": {"event_id": {"type": "string", "description": "Event ID to delete"}}, "required": ["event_id"]},
        risk="medium", category="productivity",
    ),
    _spec(
        "list_events",
        "List upcoming Google Calendar events.",
        {"type": "object", "properties": {
            "days_ahead": {"type": "integer", "description": "Days to look ahead (default 7)"},
            "query": {"type": "string", "description": "Text search to filter events"},
        }},
        risk="low", category="productivity",
    ),
    _spec(
        "create_document",
        "Create a new Google Doc. Returns the document URL.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Document title"},
            "body_text": {"type": "string", "description": "Initial body content"},
        }, "required": ["title"]},
        risk="medium", category="productivity",
    ),
    _spec(
        "create_presentation",
        "Create a new Google Slides presentation. Returns the URL.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "Presentation title"},
            "slides": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}}},
        }, "required": ["title"]},
        risk="medium", category="productivity",
    ),
    _spec(
        "share_document",
        "Share a Google Doc/Slides/Drive file with someone by email.",
        {"type": "object", "properties": {
            "file_id": {"type": "string", "description": "Google Drive file ID"},
            "email": {"type": "string", "description": "Recipient email address"},
            "role": {"type": "string", "enum": ["reader", "commenter", "writer"]},
        }, "required": ["file_id", "email"]},
        risk="high", category="productivity", confirm=True,
    ),
    _spec(
        "search_web",
        "Search the web for information using Tavily.",
        {"type": "object", "properties": {"query": {"type": "string", "description": "Search query"}}, "required": ["query"]},
        risk="low", category="productivity",
    ),
]

# ---------------------------------------------------------------------------
# Memory tools (Obsidian knowledge base + daily tracking)
# ---------------------------------------------------------------------------

MEMORY_SPECS = [
    _spec(
        "learn_from_web",
        "Search the web for useful information on a topic, extract key insights, and save them to the user's Obsidian knowledge base. Use this when you find something interesting or when the user asks you to learn something. The results are saved as a new note in Knowledge/ folder.",
        {"type": "object", "properties": {
            "topic": {"type": "string", "description": "What to learn about"},
            "depth": {"type": "string", "enum": ["quick", "deep"], "description": "Quick = 1 search, Deep = 3 searches"},
            "save_to_obsidian": {"type": "boolean", "description": "Save findings to Obsidian (default: true)"},
        }, "required": ["topic"]},
        risk="low", category="memory",
    ),
    _spec(
        "save_to_obsidian",
        "Save a note to the Obsidian vault. Use this to store knowledge, ideas, decisions, or any information the user might want to reference later. The note is automatically linked to related notes via semantic links.",
        {"type": "object", "properties": {
            "folder": {"type": "string", "enum": ["Knowledge", "Ideas", "Decisions", "Projects", "Daily"], "description": "Which folder to save in"},
            "title": {"type": "string", "description": "Note title"},
            "content": {"type": "string", "description": "Markdown content"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags like ['programming', 'AI']"},
        }, "required": ["folder", "title", "content"]},
        risk="medium", category="memory",
    ),
    _spec(
        "get_daily_summary",
        "Get a summary of what the user has been doing today. Shows recent app usage and logged activities. Use this when you need to understand the user's current context.",
        {"type": "object", "properties": {}},
        risk="low", category="memory",
    ),
    _spec(
        "log_daily_activity",
        "Log what the user is currently doing. This gets saved to the daily activity log and episodic memory. Call this when the user starts a new task or switches to a different activity.",
        {"type": "object", "properties": {
            "summary": {"type": "string", "description": "What is the user doing right now"},
            "category": {"type": "string", "enum": ["work", "learning", "browsing", "coding", "writing", "daily"]},
        }, "required": ["summary"]},
        risk="low", category="memory",
    ),
    _spec(
        "get_current_context",
        "Get the current desktop context: which app is active, what URL is open in the browser, what project is being worked on. Use this to understand what the user is doing RIGHT NOW.",
        {"type": "object", "properties": {
            "detailed": {"type": "boolean", "description": "If true, also gets browser URL (slower but more detailed)"},
        }},
        risk="low", category="memory",
    ),
]

# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------

_ALL_SPECS: list[ToolSpec] = (
    BROWSER_SPECS + DESKTOP_SPECS + UI_SPECS + PRODUCTIVITY_SPECS + MEMORY_SPECS + FOL_SPECS
)


def build_orchestrator_registry() -> ToolRegistry:
    """Build the canonical registry containing every orchestrator tool."""
    registry = ToolRegistry()
    for spec in _ALL_SPECS:
        registry.register_spec(spec)
    return registry


__all__ = [
    "build_orchestrator_registry",
    "BROWSER_SPECS",
    "DESKTOP_SPECS",
    "UI_SPECS",
    "FOL_SPECS",
    "PRODUCTIVITY_SPECS",
    "MEMORY_SPECS",
]
