"""Session CRUD — simplified for local mode (no Firestore).

All operations are no-ops or return empty results.
Token storage is handled by src/auth/token_store.py with file fallback.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("second-self")


def create_session(
    uid: str,
    google_access_token: str,
    email: str,
    name: str,
) -> str:
    """Create a new session — uses file-based store in local mode."""
    from src.auth.token_store import _file_create
    import uuid
    session_id = uuid.uuid4().hex
    _file_create(session_id, google_access_token, email, name, uid)
    log.info("Session created (file): uid=%s, session=%s", uid, session_id[:8])
    return session_id


def get_session(uid: str, session_id: str) -> dict[str, Any] | None:
    """Get a session — delegates to file-based store."""
    from src.auth.token_store import get_session as _get_session
    token = _get_session(session_id)
    if token:
        return {
            "google_access_token": token.google_access_token,
            "email": token.email,
            "name": token.name,
            "uid": token.uid,
        }
    return None


def get_latest_session(uid: str) -> tuple[str, dict[str, Any]] | None:
    """Get the most recent session — delegates to file-based store."""
    from src.auth.token_store import get_latest_session as _get_latest
    result = _get_latest()
    if result:
        session_id, token = result
        return session_id, {
            "google_access_token": token.google_access_token,
            "email": token.email,
            "name": token.name,
            "uid": token.uid,
        }
    return None


def delete_session(uid: str, session_id: str) -> None:
    """Delete a session — delegates to file-based store."""
    from src.auth.token_store import delete_session as _delete_session
    _delete_session(session_id)
