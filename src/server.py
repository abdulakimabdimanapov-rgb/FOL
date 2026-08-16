"""FastAPI server — local AI mode, no auth required.

Endpoints:
  GET  /health          — health check
  POST /onboard         — build a profile from user info (always demo/fallback)
  POST /chat            — chat with the digital twin (deprecated, use orchestrator)
"""

import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.models.schemas import (
    Behavior,
    ChatRequest,
    ChatResponse,
    Context,
    Identity,
    OnboardRequest,
    OnboardResponse,
    FOLProfile,
    Voice,
)

log = logging.getLogger("second-self")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="FOL — Local AI Mode", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/session/latest")
async def latest_session():
    """Local mode — always returns a demo session."""
    return {
        "found": True,
        "session_id": f"demo-{uuid.uuid4().hex[:12]}",
        "name": "Local User",
        "has_profile": False,
        "has_google_tokens": False,
    }


@app.post("/onboard", response_model=OnboardResponse)
async def onboard(body: OnboardRequest):
    """Build a profile. In local mode, returns a demo profile."""
    effective_session_id = body.session_id or uuid.uuid4().hex

    log.info("Building profile for %s (local mode)", body.name or "unknown")

    # Return a tailored demo profile based on the user's name and role
    slim = FOLProfile(
        identity=Identity(
            name=body.name or "User",
            role=body.context or "creator",
            company="FOL",
        ),
        voice=Voice(
            formality="casual",
            avg_email_length="medium",
            signature_phrases=["lets build something", "sounds good", "on it"],
            opens_with="Hey",
            closes_with="~",
            tone="warm and direct",
        ),
        behavior=Behavior(
            work_hours="flexible",
            meeting_load="light",
            response_style="concise",
            peak_focus_time="varies",
        ),
        context=Context(
            active_projects=["FOL", body.context or "personal projects"],
            top_collaborators=[],
            current_priorities=["building your second self"],
        ),
    )

    return OnboardResponse(
        profile=slim,
        sources_used=["local"],
        session_id=effective_session_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@app.post("/chat", response_model=ChatResponse, deprecated=True)
async def chat(body: ChatRequest):
    """DEPRECATED: Use the orchestrator at port 8420/chat instead.

    The orchestrator now handles all chat with SSE streaming, desktop tools,
    and generative UI. This endpoint is kept for backward compatibility only.
    """
    # In local mode, just return a simple response
    return ChatResponse(
        response=f"Local AI mode active. Please use the orchestrator at port 8420 for chat.\n\nYou said: {body.message[:200]}",
        actions_taken=[],
    )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("src.server:app", host=host, port=port, reload=True)
