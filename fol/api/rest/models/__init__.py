"""Pydantic models for REST API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# --- Conversation ---

class Message(BaseModel):
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(default_factory=datetime.now)


class ConversationRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message to process")


class ConversationResponse(BaseModel):
    response: str = Field(..., description="FOL response")
    conversation_id: Optional[str] = None


class ConversationHistory(BaseModel):
    messages: list[Message]
    total: int


# --- Memory ---

class MemoryStoreRequest(BaseModel):
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    memory_type: str = Field(default="conversation")


class MemoryRetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


class MemoryItem(BaseModel):
    id: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: Optional[float] = None


class MemoryResponse(BaseModel):
    results: list[MemoryItem]
    total: int


class MemoryEpisodeRequest(BaseModel):
    event: str = Field(..., min_length=1, description="What happened (episodic summary)")
    context: str = Field(default="", description="Optional surrounding context")
    importance: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Tools ---

class ToolExecuteRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolResultResponse(BaseModel):
    success: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolListResponse(BaseModel):
    tools: list[ToolInfo]
    total: int


# --- Plugins ---

class PluginInfo(BaseModel):
    name: str
    version: str
    description: str = ""
    enabled: bool = True


class PluginListResponse(BaseModel):
    plugins: list[PluginInfo]
    total: int


class PluginToggleRequest(BaseModel):
    enabled: bool


# --- Settings ---

class SettingsResponse(BaseModel):
    app_name: str
    debug: bool
    log_level: str
    llm_backend: str
    llm_model: str
    api_host: str
    api_port: int


class SettingsUpdateRequest(BaseModel):
    debug: Optional[bool] = None
    log_level: Optional[str] = None
    llm_backend: Optional[str] = None
    llm_model: Optional[str] = None


# --- Proactive (ROADMAP Etap 5) ---

class ProactiveToggleRequest(BaseModel):
    enabled: bool = Field(..., description="Turn proactive mode on/off")


class ProactiveStatusResponse(BaseModel):
    enabled: bool
    total_commands: int = 0
    session_minutes: int = 0
    cooldown_minutes: int = 0
    max_per_hour: int = 0
    emitted_this_hour: int = 0
    rules: int = 0
    last_suggestion: Optional[str] = None


class ProactiveCheckResponse(BaseModel):
    enabled: bool
    suggestion: Optional[dict[str, Any]] = None


class ProactiveExecuteRequest(BaseModel):
    action: str = Field(..., min_length=1, description="Suggestion action label")
    title: str = Field(default="", description="Suggestion title (informational)")


class ProactiveExecuteResponse(BaseModel):
    executed: bool
    needs_confirmation: bool = False
    action_id: Optional[str] = None
    response: str = ""


class ProactiveConfirmRequest(BaseModel):
    action_id: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)


class ProactiveDismissRequest(BaseModel):
    title: str = Field(..., min_length=1)


class ProactiveDismissResponse(BaseModel):
    ok: bool
    title: str


# --- Health ---

class HealthResponse(BaseModel):
    status: str
    version: str
    uptime: float
    modules: dict[str, str] = Field(default_factory=dict)


# --- Generic ---

class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
