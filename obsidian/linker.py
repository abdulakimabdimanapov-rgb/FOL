"""Semantic Linker — автоматическое создание связей между заметками.

После каждой записи в vault запускается linker:
1. Извлекает ключевые понятия из новой заметки
2. Ищет похожие заметки через search()
3. LLM решает, какие связи создать
4. Добавляет [[wikilinks]] в заметку
5. Обновляет backlinks в связанных заметках
"""

from __future__ import annotations

import logging
from typing import Any

from obsidian.client import search, patch_note

logger = logging.getLogger(__name__)

# Максимум concepts для поиска
MAX_CONCEPTS = 3
# Максимум кандидатов для LLM
MAX_CANDIDATES = 10


def auto_link_note(vault_path: str, content: str) -> list[dict[str, Any]]:
    """Find and create semantic links for a note.

    This runs after every write to the vault.
    Извлекает concepts, ищет связанные заметки, добавляет [[wikilinks]].

    Если Obsidian REST API недоступен — gracefully skips.

    Args:
        vault_path: path of the note just written
        content: markdown content of the note

    Returns:
        List of created links: [{target, type, reason}]
        Empty list if no links found or LLM unavailable.
    """
    try:
        from orchestrator.llm_bridge import llm_call_json
    except ImportError:
        logger.debug("LLM not available — skipping auto-link")
        return []

    try:
        # 1. Extract concepts from content
        concepts = _extract_concepts(content, llm_call_json)
        if not concepts:
            return []

        # 2. Search for related notes
        related = _find_related_notes(concepts, vault_path)
        if not related:
            return []

        # 3. LLM decides which links to create
        links = _decide_links(content, related, llm_call_json)
        if not links:
            return []

        # 4. Write links to the note
        _write_links_to_note(vault_path, links)

        # 5. Update backlinks in target notes
        _update_backlinks(vault_path, links)

        logger.info("Created %d links for %s", len(links), vault_path)
        return links

    except Exception as exc:
        logger.warning("Auto-link failed for %s: %s", vault_path, exc)
        return []


def _extract_concepts(content: str, llm_call) -> list[str]:
    """Extract key concepts from note content using LLM."""
    prompt = (
        "Extract the top 5 key concepts/entities from this note. "
        "These will be used to find related notes. "
        "Return JSON array of strings. "
        "Focus on: project names, technologies, people, domain terms."
    )

    try:
        result = llm_call(prompt, content[:2000], max_tokens=200)
        if isinstance(result, list):
            return [c for c in result if isinstance(c, str)][:MAX_CONCEPTS]
        return []
    except Exception as exc:
        logger.debug("Concept extraction failed: %s", exc)
        return []


def _find_related_notes(concepts: list[str], exclude_path: str) -> list[dict[str, Any]]:
    """Search for notes related to the given concepts."""
    seen_paths: set[str] = set()
    related: list[dict[str, Any]] = []

    for concept in concepts[:MAX_CONCEPTS]:
        try:
            results = search(concept, limit=5)
            for result in results:
                path = result.get("path", "")
                if path and path != exclude_path and path not in seen_paths:
                    seen_paths.add(path)
                    related.append({
                        "path": path,
                        "content": result.get("content", "")[:500],
                        "score": result.get("score", 0),
                    })
        except Exception as exc:
            logger.debug("Search failed for '%s': %s", concept, exc)

    return related[:MAX_CANDIDATES]


def _decide_links(
    content: str,
    candidates: list[dict[str, Any]],
    llm_call,
) -> list[dict[str, Any]]:
    """Let LLM decide which links to create."""
    existing_summary = "\n\n".join(
        f"--- {n['path']} ---\n{n['content']}"
        for n in candidates
    )

    prompt = (
        "Given a NEW note and a list of EXISTING notes from the vault, "
        "decide which links should be created between them.\n\n"
        "For each link, choose a type:\n"
        '- "related" — shares common topics\n'
        '- "parent" — hierarchical parent\n'
        '- "child" — hierarchical child\n'
        '- "source" — the existing note is a source/inspiration\n'
        '- "implements" — this note implements an idea\n'
        '- "follow_up" — follow-up or continuation\n\n'
        "Return JSON array of: "
        '{"target": "vault/path", "type": "link_type", "reason": "why"}\n\n'
        f"NEW NOTE:\n{content[:1000]}\n\n"
        f"EXISTING NOTES:\n{existing_summary}"
    )

    try:
        links = llm_call(prompt, "", max_tokens=500)
        if isinstance(links, list):
            return links
        return []
    except Exception as exc:
        logger.debug("Link decision failed: %s", exc)
        return []


def _write_links_to_note(vault_path: str, links: list[dict[str, Any]]) -> None:
    """Append [[wikilinks]] section to the note."""
    link_lines = ["\n## Related"]
    for link in links:
        target = link.get("target", "")
        link_type = link.get("type", "related")
        reason = link.get("reason", "")
        link_lines.append(f"- [[{target}]] → {link_type} ({reason})")

    link_section = "\n".join(link_lines)

    try:
        patch_note(
            vault_path=vault_path,
            target_type="heading",
            target=["Links"],
            operation="append",
            content=link_section,
        )
    except Exception as exc:
        logger.debug("Failed to add links to %s: %s", vault_path, exc)


def _update_backlinks(source_path: str, links: list[dict[str, Any]]) -> None:
    """Add backlinks in target notes pointing back to source."""
    for link in links:
        target = link.get("target", "")
        if not target:
            continue

        try:
            backlink_line = (
                f"- [[{source_path}]] → {link.get('type', 'related')}"
            )
            patch_note(
                vault_path=target,
                target_type="heading",
                target=["Links"],
                operation="append",
                content=f"\n{backlink_line}",
            )
        except Exception as exc:
            logger.debug("Backlink update skipped for %s: %s", target, exc)
