"""Memory tools for FOL — инструменты для сохранения в Obsidian и обучения из интернета.

Эти инструменты добавляются в ALL_TOOLS в orchestrator/server.py.
LLM может вызывать их чтобы:
- learn_from_web: найти информацию, извлечь полезное, сохранить в Obsidian
- save_to_obsidian: сохранить любую заметку в Obsidian vault
- get_daily_summary: получить сводку что пользователь делал сегодня
- log_activity: записать что пользователь делает сейчас
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tavily helper (self-contained, no dependency on orchestrator)
# ---------------------------------------------------------------------------

def _search_web(query: str, api_key: str = "") -> dict:
    """Search the web using Tavily API. Self-contained."""
    if not api_key:
        import os
        api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return {"error": "TAVILY_API_KEY not set"}
    
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",
        "max_results": 5,
        "include_answer": True,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


# Anthropic-format tool definitions
MEMORY_TOOLS = [
    {
        "name": "learn_from_web",
        "description": (
            "Search the web for useful information on a topic, extract key insights, "
            "and save them to the user's Obsidian knowledge base. "
            "Use this when you find something interesting or when the user asks you to learn something. "
            "The results are saved as a new note in Knowledge/ folder."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "What to learn about"},
                "depth": {
                    "type": "string",
                    "enum": ["quick", "deep"],
                    "description": "Quick = 1 search, Deep = 3 searches",
                },
                "save_to_obsidian": {
                    "type": "boolean",
                    "description": "Save findings to Obsidian (default: true)",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "save_to_obsidian",
        "description": (
            "Save a note to the Obsidian vault. "
            "Use this to store knowledge, ideas, decisions, or any information "
            "the user might want to reference later. "
            "The note is automatically linked to related notes via semantic links."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "enum": ["Knowledge", "Ideas", "Decisions", "Projects", "Daily"],
                    "description": "Which folder to save in",
                },
                "title": {"type": "string", "description": "Note title"},
                "content": {"type": "string", "description": "Markdown content"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional tags like ['programming', 'AI']",
                },
            },
            "required": ["folder", "title", "content"],
        },
    },
    {
        "name": "get_daily_summary",
        "description": (
            "Get a summary of what the user has been doing today. "
            "Shows recent app usage and logged activities. "
            "Use this when you need to understand the user's current context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "log_daily_activity",
        "description": (
            "Log what the user is currently doing. "
            "This gets saved to the daily activity log and episodic memory. "
            "Call this when the user starts a new task or switches to a different activity."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What is the user doing right now"},
                "category": {
                    "type": "string",
                    "enum": ["work", "learning", "browsing", "coding", "writing", "daily"],
                },
            },
            "required": ["summary"],
        },
    },
    {
        "name": "get_current_context",
        "description": (
            "Get the current desktop context: which app is active, "
            "what URL is open in the browser, what project is being worked on. "
            "Use this to understand what the user is doing RIGHT NOW."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "detailed": {
                    "type": "boolean",
                    "description": "If true, also gets browser URL (slower but more detailed)",
                },
            },
        },
    },
]

MEMORY_TOOL_NAMES = {t["name"] for t in MEMORY_TOOLS}


async def execute_memory_tool(tool_name: str, arguments: dict) -> str:
    """Execute a memory tool and return result as JSON string."""
    import json
    from orchestrator.llm_bridge import llm_completion_sync
    from orchestrator.memory_bridge import record_activity
    from utils.daily_tracker import log_activity, get_today_summary
    
    if tool_name == "get_daily_summary":
        summary = get_today_summary()
        return json.dumps({"status": "ok", "summary": summary})
    
    if tool_name == "log_daily_activity":
        summary = arguments.get("summary", "")
        category = arguments.get("category", "daily")
        log_activity(summary=summary, category=category)
        record_activity(summary=summary, category=category, source="memory_tool")
        return json.dumps({"status": "ok", "logged": summary[:60]})
    
    if tool_name == "get_current_context":
        detailed = arguments.get("detailed", False)
        try:
            from context_engine.snapshot import get_snapshot, format_context_for_prompt
            snapshot = get_snapshot(use_cache=not detailed)
            context_str = format_context_for_prompt(snapshot)
            
            # Also log to daily tracker
            log_activity(
                summary=f"Context check: {context_str}",
                app_name=snapshot.app_name,
                category="daily",
            )
            
            return json.dumps({
                "status": "ok",
                "app": snapshot.app_name,
                "category": snapshot.app_category,
                "url": snapshot.browser_url,
                "domain": snapshot.browser_domain,
                "url_category": snapshot.url_category,
                "formatted": context_str,
            })
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})
    
    if tool_name == "learn_from_web":
        topic = arguments.get("topic", "")
        depth = arguments.get("depth", "quick")
        save = arguments.get("save_to_obsidian", True)
        
        if not topic:
            return json.dumps({"status": "error", "error": "No topic specified"})
        
        try:
            # Search the web using self-contained _search_web
            if depth == "deep":
                # 3 searches for comprehensive learning
                queries = [
                    topic,
                    f"{topic} key concepts",
                    f"{topic} best practices 2026",
                ]
            else:
                queries = [topic]
            
            all_results = []
            for query in queries:
                result = _search_web(query)
                if "error" not in result:
                    snippets = [
                        r.get("content", "") for r in result.get("results", [])[:3]
                    ]
                    answer = result.get("answer", "")
                    all_results.append(f"Query: {query}\nAnswer: {answer}\n" + "\n".join(snippets))
            
            combined = "\n\n---\n\n".join(all_results)
            
            # Summarize with LLM
            summary_prompt = (
                f"You researched: {topic}\n\n"
                f"Search results:\n{combined[:4000]}\n\n"
                "Summarize the key insights in a way that's useful for future reference. "
                "Format as markdown with sections: Overview, Key Points, Resources."
            )
            
            summary = llm_completion_sync(
                messages=[{"role": "user", "content": summary_prompt}],
                system="You are a research assistant. Summarize findings concisely.",
                max_tokens=2000,
            )
            
            # Save to memory (canonical path + local mirror)
            record_activity(
                f"Learned about: {topic}",
                category="learning",
                source="web_research",
            )
            
            # Also log to daily tracker
            log_activity(
                summary=f"Learned about: {topic}",
                category="learning",
            )
            
            return json.dumps({
                "status": "ok",
                "topic": topic,
                "summary": summary,
                "saved": save,
            })
        except Exception as exc:
            return json.dumps({"status": "error", "error": f"Learning failed: {exc}"})
    
    if tool_name == "save_to_obsidian":
        folder = arguments.get("folder", "Knowledge")
        title = arguments.get("title", "Untitled")
        content = arguments.get("content", "")
        tags = arguments.get("tags", [])
        
        # Defensive normalization — small local models sometimes pass
        # non-string values for these fields (lists, numbers, dicts).
        if not isinstance(folder, str):
            folder = "Knowledge"
        if not isinstance(title, str):
            title = str(title) if title is not None else "Untitled"
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False) if content is not None else ""
        if isinstance(tags, str):
            tags = [tags]
        elif not isinstance(tags, list):
            tags = []
        
        # Save to memory (canonical path + local mirror)
        summary = f"[{folder}] {title}"
        record_activity(
            summary=summary,
            category="knowledge",
            source="memory_tool",
        )
        
        # Also log to daily tracker
        log_activity(
            summary=f"Saved: {title} → {folder}",
            category="writing",
        )
        
        # Try Obsidian if available
        try:
            from obsidian.vault import save_note
            from datetime import datetime, timezone

            slug = title.lower().replace(" ", "-").replace("/", "-")
            vault_path = f"{folder}/{slug}"

            # save_note теперь запускает auto_link=True по умолчанию
            # → Semantic Linker создаст [[wikilinks]] между заметками
            result = save_note(vault_path, content, tags=tags, auto_link=True)
            logger.info("Saved + auto-linked note to Obsidian: %s", vault_path)
            return json.dumps({
                "status": "ok",
                "saved_to": "obsidian",
                "path": vault_path,
                "auto_linked": True,
            })
        except Exception as obs_exc:
            logger.warning("Obsidian save failed, falling back to episodic: %s", obs_exc)
            return json.dumps({
                "status": "ok",
                "saved_to": "episodic_fallback",
                "note": f"[{folder}] {title}\n\n{content[:200]}...",
                "obsidian_error": str(obs_exc),
            })
    
    return json.dumps({"status": "error", "error": f"Unknown tool: {tool_name}"})
