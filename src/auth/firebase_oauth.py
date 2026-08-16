"""Firebase auth is disabled in local mode. All endpoints return mock data."""

import hashlib
import logging
import os

from fastapi import APIRouter, Cookie
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.auth.token_store import create_session, get_session

log = logging.getLogger("second-self")

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthCallbackRequest(BaseModel):
    id_token: str
    google_access_token: str
    email: str
    name: str


@router.get("/firebase-config")
async def firebase_config():
    """Return empty Firebase config — auth is disabled in local mode."""
    return {"apiKey": "", "authDomain": "", "projectId": ""}


@router.get("/login")
async def login_page():
    """Serve a minimal login page (or return a message in local mode)."""
    return JSONResponse({
        "status": "local_mode",
        "message": "Auth is disabled. FOL runs with local AI.",
    })


@router.post("/callback")
async def auth_callback(body: AuthCallbackRequest):
    """Accept auth callback but just create a local session."""
    uid = hashlib.sha256(body.email.encode()).hexdigest()[:28]
    session_id = create_session(
        google_access_token=body.google_access_token,
        email=body.email,
        name=body.name,
        uid=uid,
    )
    response = JSONResponse({"status": "ok", "session_id": session_id})
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@router.get("/status")
async def auth_status(session_id: str = Cookie(default=None)):
    """Local mode — always authenticated as demo user."""
    return {
        "authenticated": True,
        "email": "local@fol.ai",
        "name": "Local User",
    }
