"""Conversation routes — send messages and retrieve history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.rest.models import (
    ConversationHistory,
    ConversationRequest,
    ConversationResponse,
    Message,
)

router = APIRouter(prefix="/conversation", tags=["conversation"])


def _get_fol():
    """Get the FOL instance from app state (set during startup)."""
    from fastapi import Request
    # This will be injected at startup
    raise HTTPException(status_code=503, detail="FOL not initialized")


@router.post("/send", response_model=ConversationResponse)
async def send_message(request: ConversationRequest) -> ConversationResponse:
    """Send a message to FOL and get a response."""
    from fastapi import Request
    from starlette.requests import Request as StarletteRequest

    # Access app state — FOL instance is stored there
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")

    try:
        response = await fol.process(request.message)
        return ConversationResponse(response=response)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/history", response_model=ConversationHistory)
async def get_history(limit: int = 50) -> ConversationHistory:
    """Get conversation history."""
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")

    ctx = fol.context_manager
    turns = ctx.get_recent_context()
    messages = []
    for turn in turns:
        if isinstance(turn, dict):
            if "user" in turn:
                messages.append(Message(role="user", content=turn["user"]))
            if "assistant" in turn:
                messages.append(Message(role="assistant", content=turn["assistant"]))

    return ConversationHistory(messages=messages[-limit:], total=len(messages))


@router.delete("/history")
async def clear_history() -> dict[str, str]:
    """Clear conversation history."""
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")

    fol.context_manager.clear()
    return {"status": "cleared"}
