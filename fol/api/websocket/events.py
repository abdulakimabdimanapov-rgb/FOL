"""WebSocket event types for real-time communication."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class WSEvent(BaseModel):
    """WebSocket event envelope."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    source: str = "server"
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class WSMessage(BaseModel):
    """Incoming WebSocket message from client."""

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


# Event types
EVENT_CONNECTED = "connected"
EVENT_DISCONNECTED = "disconnected"
EVENT_USER_INPUT = "user_input"
EVENT_LLM_TOKEN = "llm_token"
EVENT_LLM_RESPONSE = "llm_response"
EVENT_TOOL_EXECUTED = "tool_executed"
EVENT_ERROR = "error"
EVENT_STATUS = "status"
EVENT_PROACTIVE = "proactive_suggestion"
