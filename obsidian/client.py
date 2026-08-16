"""HTTP client for Obsidian Local REST API plugin (v5.x).

Позволяет читать, писать, искать и патчить заметки в Obsidian vault
через HTTPS API локального плагина.

Требования:
1. Obsidian установлен и открыт
2. Плагин "Local REST API" установлен и включён
3. API ключ скопирован из настроек плагина в .env

Использование:
    from obsidian.client import check_connection, read_note, write_note, search

    if check_connection():
        content = read_note("Daily/2026-04-12")
        write_note("Knowledge/new-thing", "# New Knowledge\\n...")
        results = search("Obsidian API")

Контракт v5 (проверен вживую против плагина 5.0.2):
- PUT  /vault/{path}       body = {"content": str, "type": "file"}  → 204
- GET  /vault/{path}       → {"content": str, "type": "file"}
- GET  /vault/{dir}/       → {"files": ["a.md", ...]}
- DELETE /vault/{path}     → 204
- POST /search/simple/?query=... → [ {filename, score, matches: [...]} ]
- PATCH /vault/{path}      body = InstructionInput (markdown-patch 2.0)

Внимание: PATCH работает только для файлов, уже проиндексированных
Obsidian (созданных через сам Obsidian или записанных давно). Сразу после
PUT свежий файл в metadata-cache может отсутствовать — patch_note в этом
случае делает фолбэк «read → modify → write», который всегда работает.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from obsidian.config import (
    OBSIDIAN_API_KEY,
    OBSIDIAN_API_URL,
    VERIFY_SSL,
    is_configured,
)

logger = logging.getLogger(__name__)

# Cached SSL context (avoid creating on every request)
_ssl_context: ssl.SSLContext | None = None


def _get_ssl_context() -> ssl.SSLContext | None:
    """Get SSL context for Obsidian's self-signed cert.

    If VERIFY_SSL is False (default for Local REST API's self-signed cert),
    creates an unverified context so requests don't fail on SSL handshake.
    """
    global _ssl_context
    if _ssl_context is not None:
        return _ssl_context

    if not VERIFY_SSL:
        _ssl_context = ssl._create_unverified_context()
        logger.debug("SSL verification disabled for Obsidian (self-signed cert)")
    else:
        _ssl_context = None  # Use default SSL context (verifies)

    return _ssl_context


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class ObsidianError(Exception):
    """Base Obsidian error."""


class ObsidianConnectionError(ObsidianError):
    """Cannot connect to Obsidian (is it running with the plugin?)."""


class ObsidianAuthError(ObsidianError):
    """Invalid API key."""


class ObsidianNotFoundError(ObsidianError):
    """Note or resource not found."""


# ---------------------------------------------------------------------------
# Internal HTTP client
# ---------------------------------------------------------------------------


def _headers(content_type: str = "application/json") -> dict[str, str]:
    """Build authorization headers for the REST API."""
    return {
        "Authorization": f"Bearer {OBSIDIAN_API_KEY}",
        "Content-Type": content_type,
    }


def _quote_path_segments(value: str) -> str:
    """URL-encode each path segment separately to preserve slashes."""
    return "/".join(urllib.parse.quote(s, safe="") for s in value.split("/"))


def _request(
    method: str,
    url: str,
    body: Any = None,
    content_type: str = "application/json",
) -> dict[str, Any]:
    """Make an HTTP request to the Obsidian REST API.

    Args:
        method: GET, PUT, PATCH, DELETE, POST
        url: full URL (OBSIDIAN_API_URL + path)
        body: request body — dict (JSON-encoded) or str (raw text)
        content_type: Content-Type header

    Returns:
        Parsed JSON response (dict or list), or {} for empty bodies (204).

    Raises:
        ObsidianConnectionError: vault unreachable
        ObsidianAuthError: invalid API key
        ObsidianNotFoundError: note doesn't exist
    """
    if not is_configured():
        raise ObsidianAuthError(
            "OBSIDIAN_API_KEY not set. "
            "Install the Local REST API plugin in Obsidian, "
            "copy the API key, and add it to .env"
        )

    # Build request body
    data = None
    if body is not None:
        if isinstance(body, dict):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        headers=_headers(content_type),
        method=method,
    )

    ssl_ctx = _get_ssl_context()

    try:
        kwargs = {"timeout": 10}
        if ssl_ctx is not None:
            kwargs["context"] = ssl_ctx

        with urllib.request.urlopen(req, **kwargs) as resp:
            response_data = resp.read()
            if response_data:
                try:
                    return json.loads(response_data)
                except (ValueError, json.JSONDecodeError):
                    # markdown-patch 2.0 returns the patched document as plain
                    # text (Content-Type: text/markdown) — surface it as-is.
                    return response_data.decode("utf-8", errors="replace")
            return {}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ObsidianAuthError(
                "Invalid Obsidian API key. "
                "Check OBSIDIAN_API_KEY in .env"
            ) from e
        if e.code == 404:
            raise ObsidianNotFoundError(f"Note not found: {url}") from e
        raise ObsidianConnectionError(f"HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise ObsidianConnectionError(
            f"Cannot connect to Obsidian at {OBSIDIAN_API_URL}. "
            f"Is Obsidian running with the Local REST API plugin enabled?"
        ) from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_connection() -> bool:
    """Check if Obsidian vault is reachable.

    Returns:
        True if Obsidian is running and the REST API responds
    """
    if not is_configured():
        logger.warning("Obsidian not configured: OBSIDIAN_API_KEY missing")
        return False

    try:
        resp = _request("GET", f"{OBSIDIAN_API_URL}/")
        # The plugin returns "OK" (uppercase) — compare case-insensitively so a
        # live vault with a valid key is never reported as disconnected.
        ok = str(resp.get("status", "")).lower() == "ok"
        if ok:
            logger.info("Obsidian vault connected at %s", OBSIDIAN_API_URL)
        return ok
    except (ObsidianConnectionError, ObsidianAuthError, ObsidianError) as e:
        logger.debug("Obsidian connection check failed: %s", e)
        return False


def _normalize_vault_path(vault_path: str) -> str:
    """Strip trailing slash and append .md if missing (v5 requires it)."""
    p = vault_path.strip().strip("/")
    if not p.lower().endswith(".md"):
        p = f"{p}.md"
    return p


def read_note(vault_path: str) -> str:
    """Read a note's markdown content from the vault.

    Args:
        vault_path: relative path in vault, with or without .md.
                    e.g. "Projects/FOL/architecture"

    Returns:
        Full markdown content of the note (including frontmatter if present)

    Raises:
        ObsidianNotFoundError: note doesn't exist
        ObsidianConnectionError: vault unreachable
    """
    path = _normalize_vault_path(vault_path)
    result = _request(
        "GET",
        f"{OBSIDIAN_API_URL}/vault/{_quote_path_segments(path)}",
    )
    if isinstance(result, dict):
        return str(result.get("content", ""))
    return ""


def write_note(vault_path: str, content: str) -> dict[str, Any]:
    """Create or overwrite a note in the vault.

    v5 contract: body must be {"content": str, "type": "file"} — a raw text
    body is rejected. The plugin returns HTTP 204 (empty body).

    Args:
        vault_path: relative path, with or without .md.
                    e.g. "Ideas/new-feature"
        content: full markdown content (including frontmatter)

    Returns:
        API response dict (usually {} on 204)

    Raises:
        ObsidianConnectionError: vault unreachable
        ObsidianAuthError: invalid API key
    """
    path = _normalize_vault_path(vault_path)
    _request(
        "PUT",
        f"{OBSIDIAN_API_URL}/vault/{_quote_path_segments(path)}",
        body={"content": content, "type": "file"},
    )
    return {"status": "ok"}


def patch_note(
    vault_path: str,
    target_type: str,
    target: list[str],
    operation: str,
    content: str,
    scope: str = "content",
) -> dict[str, Any]:
    """Surgically modify a note at a specific heading/block.

    Uses the markdown-patch 2.0 instruction format (v5 plugin). If the target
    cannot be resolved — e.g. the file was just written via the API and Obsidian
    hasn't indexed it yet, or the heading doesn't exist — falls back to
    read → modify → write, which always succeeds.

    Args:
        vault_path: relative path, with or without .md
        target_type: "heading" | "block" | "frontmatter"
        target: ["My Section"] for heading
        operation: "append" | "replace" | "prepend" | "delete"
        content: text to insert
        scope: "content" | "marker" | "markerAndContent" | "parent"

    Returns:
        API response dict
    """
    path = _normalize_vault_path(vault_path)
    body: dict[str, Any] = {
        "targetType": target_type,
        "target": target,
        "operation": operation,
        "content": content,
    }
    if scope:
        body["scope"] = scope

    try:
        result = _request(
            "PATCH",
            f"{OBSIDIAN_API_URL}/vault/{_quote_path_segments(path)}",
            body=body,
        )
        return result if isinstance(result, dict) else {"status": "ok"}
    except ObsidianNotFoundError:
        # Obsidian hasn't indexed the freshly-written file (or the heading is
        # missing) — do it the reliable way: read, modify, write back.
        logger.debug(
            "PATCH target not resolvable for %s — falling back to read/modify/write",
            vault_path,
        )
        return _patch_fallback(path, target_type, target, operation, content)


def _patch_fallback(
    vault_path: str,
    target_type: str,
    target: list[str],
    operation: str,
    content: str,
) -> dict[str, Any]:
    """Apply a patch client-side by reading, editing and rewriting the note."""
    current = read_note(vault_path)

    if target_type == "frontmatter":
        # Not supported in the simple fallback — rewrite whole note via append.
        new_content = current + content if operation == "append" else content
    elif target_type in ("heading", "block"):
        if operation in ("append", "prepend"):
            new_content = _insert_after_heading(current, target, content, operation)
        else:  # replace
            new_content = _replace_heading_content(current, target, content)
    else:
        new_content = current

    write_note(vault_path, new_content)
    return {"status": "ok", "method": "fallback"}


def _insert_after_heading(
    current: str,
    target: list[str],
    content: str,
    operation: str,
) -> str:
    """Insert content after (append) or before (prepend) a heading line.

    Finds the deepest heading from `target` (heading texts), inserts the
    content on its own line after the heading + its body, before the next
    heading of equal or higher level.
    """
    if not target:
        # No heading — append at the end of the document.
        return current.rstrip() + "\n\n" + content.lstrip("\n") + "\n"

    heading_text = target[-1]
    lines = current.splitlines()

    # Find the heading line (case-insensitive, allow trailing # or :).
    # With a nested address (["Alpha", "Subsection"]) we prefer the occurrence
    # nested under the ancestor heading; otherwise the first match wins.
    target_idx = -1
    ancestor_idx = -1
    if len(target) >= 2:
        ancestor_text = target[-2]
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("#"):
                continue
            text = stripped.lstrip("#").strip().rstrip("#").strip()
            if text.lower() == ancestor_text.lower():
                ancestor_idx = i
                break
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip().rstrip("#").strip()
        if text.lower() == heading_text.lower():
            if ancestor_idx != -1 and i < ancestor_idx:
                continue  # heading appears before its ancestor — keep looking
            target_idx = i
            break

    if target_idx == -1:
        # Heading doesn't exist — append at the end of the document.
        return current.rstrip() + "\n\n" + content.lstrip("\n") + "\n"

    if operation == "prepend":
        lines.insert(target_idx + 1, content.strip("\n"))
        return "\n".join(lines) + "\n"

    # append: find the next heading of level <= target's level.
    target_level = len(lines[target_idx]) - len(lines[target_idx].lstrip("#"))
    insert_at = len(lines)
    for j in range(target_idx + 1, len(lines)):
        line = lines[j]
        if line.strip().startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            if level <= target_level:
                insert_at = j
                break
    else:
        insert_at = len(lines)

    # Remove any blank lines between target body and insertion point.
    while insert_at > target_idx + 1 and not lines[insert_at - 1].strip():
        insert_at -= 1

    text = content.strip("\n")
    lines.insert(insert_at, text)
    return "\n".join(lines) + "\n"


def _replace_heading_content(
    current: str,
    target: list[str],
    content: str,
) -> str:
    """Replace the body of a heading with new content."""
    if not target:
        return content
    heading_text = target[-1]
    lines = current.splitlines()

    # Same nested-address preference as _insert_after_heading.
    target_idx = -1
    ancestor_idx = -1
    if len(target) >= 2:
        ancestor_text = target[-2]
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("#"):
                continue
            text = stripped.lstrip("#").strip().rstrip("#").strip()
            if text.lower() == ancestor_text.lower():
                ancestor_idx = i
                break
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip().rstrip("#").strip()
        if text.lower() == heading_text.lower():
            if ancestor_idx != -1 and i < ancestor_idx:
                continue
            target_idx = i
            break

    if target_idx == -1:
        return current.rstrip() + "\n\n" + content.lstrip("\n") + "\n"

    target_level = len(lines[target_idx]) - len(lines[target_idx].lstrip("#"))
    end_idx = len(lines)
    for j in range(target_idx + 1, len(lines)):
        if lines[j].strip().startswith("#"):
            level = len(lines[j]) - len(lines[j].lstrip("#"))
            if level <= target_level:
                end_idx = j
                break

    new_lines = lines[: target_idx + 1]
    new_lines.append("")
    new_lines.extend(content.strip("\n").splitlines())
    new_lines.extend(lines[end_idx:])
    return "\n".join(new_lines) + "\n"


def delete_note(vault_path: str) -> dict[str, Any]:
    """Move a note to system trash.

    Args:
        vault_path: relative path, with or without .md
    """
    path = _normalize_vault_path(vault_path)
    _request("DELETE", f"{OBSIDIAN_API_URL}/vault/{_quote_path_segments(path)}")
    return {"status": "ok"}


def list_notes(directory: str = "") -> list[str]:
    """List files in a vault directory.

    Tries the REST API first; if Obsidian hasn't registered a freshly-created
    folder yet (API 404), falls back to scanning the vault on disk.

    Args:
        directory: vault subdirectory, e.g. "Knowledge" or "" for root.

    Returns:
        List of file paths, e.g. ["Knowledge/api.md", "Profile.md"]
    """
    dir_path = directory.strip().strip("/")
    url = f"{OBSIDIAN_API_URL}/vault/"
    if dir_path:
        url += _quote_path_segments(dir_path) + "/"
    try:
        result = _request("GET", url)
        files = result.get("files", []) if isinstance(result, dict) else []
        out: list[str] = []
        for f in files:
            name = str(f)
            out.append(name if not dir_path else f"{dir_path}/{name}")
        return out
    except ObsidianNotFoundError:
        pass

    # API doesn't know the folder yet — read it straight from disk.
    return _list_from_disk(dir_path)


def _list_from_disk(dir_path: str) -> list[str]:
    """List markdown files under a vault folder via the filesystem."""
    from obsidian.config import VAULT_PATH

    base = VAULT_PATH if not dir_path else VAULT_PATH / dir_path
    if not base.is_dir():
        return []
    out: list[str] = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix.lower() == ".md":
            rel = p.relative_to(VAULT_PATH).as_posix()
            out.append(rel)
    return out


def get_tags() -> list[dict[str, Any]]:
    """List all tags in the vault with usage counts.

    Returns:
        List of dicts: [{"tag": "fol", "count": 3}, ...]
    """
    result = _request("GET", f"{OBSIDIAN_API_URL}/tags/")
    tags = result.get("tags", []) if isinstance(result, dict) else []
    return tags if isinstance(tags, list) else []


def move_note(source_path: str, destination_path: str) -> dict[str, Any]:
    """Move (rename) a note within the vault via read → write → delete.

    Args:
        source_path: current relative path
        destination_path: new relative path

    Returns:
        {"status": "ok", "from": ..., "to": ...}
    """
    content = read_note(source_path)
    write_note(destination_path, content)
    delete_note(source_path)
    logger.info("Moved note %s → %s", source_path, destination_path)
    return {"status": "ok", "from": source_path, "to": destination_path}


def append_to_note(vault_path: str, content: str) -> dict[str, Any]:
    """Append content to the very end of a note (no heading needed).

    Implemented client-side (read → write) so it works even when the file
    is brand-new and Obsidian hasn't indexed it yet.

    Args:
        vault_path: relative path
        content: markdown text to append

    Returns:
        {"status": "ok"}
    """
    path = _normalize_vault_path(vault_path)
    current = read_note(path)
    separator = "" if current.endswith("\n\n") or not current else "\n\n"
    write_note(path, current + separator + content.lstrip("\n") + "\n")
    return {"status": "ok"}


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Full-text search across the entire vault.

    Uses Obsidian's built-in search engine (same as Ctrl+Shift+F).
    v5 contract: POST /search/simple/?query=... returns a bare array.

    Args:
        query: search query string
        limit: max results to return

    Returns:
        List of dicts: {path, filename, content (snippet), score}
    """
    params = urllib.parse.urlencode({"query": query})
    result = _request(
        "POST",
        f"{OBSIDIAN_API_URL}/search/simple/?{params}",
    )

    items = result if isinstance(result, list) else result.get("results", [])
    out: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename", ""))
        # Build a snippet from the first match's context.
        snippet = ""
        matches = item.get("matches") or []
        if isinstance(matches, list) and matches:
            first = matches[0]
            if isinstance(first, dict) and first.get("context"):
                snippet = str(first["context"])
        if not snippet:
            snippet = filename
        out.append({
            "path": filename,
            "filename": filename.rsplit("/", 1)[-1],
            "content": snippet,
            "score": item.get("score", 0),
        })
    return out


def execute_command(command_id: str) -> dict[str, Any]:
    """Execute an Obsidian command by its ID.

    Args:
        command_id: e.g. "workspace:split-vertical"

    Returns:
        API response dict
    """
    return _request(
        "POST",
        f"{OBSIDIAN_API_URL}/commands/{urllib.parse.quote(command_id, safe='')}/",
        body={},
    )
