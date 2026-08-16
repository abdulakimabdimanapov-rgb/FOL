from pydantic import BaseModel
from datetime import datetime


# --- Request / Input Models ---

class OnboardRequest(BaseModel):
    name: str
    email: str = ""
    context: str = ""  # optional: company, Twitter handle, etc.
    session_id: str = ""  # optional: reuse an existing auth session


# --- Intermediate Data Models ---

class EmailMessage(BaseModel):
    subject: str
    to: str
    body: str
    date: str


class CalendarEvent(BaseModel):
    title: str
    start: str
    recurring: bool
    attendee_count: int


# --- FOL Profile (the handoff contract) ---

class Identity(BaseModel):
    name: str
    role: str
    company: str


class Voice(BaseModel):
    formality: str  # casual | professional | casual-professional
    avg_email_length: str  # short | medium | long
    signature_phrases: list[str]
    opens_with: str
    closes_with: str
    tone: str


class Behavior(BaseModel):
    work_hours: str
    meeting_load: str  # light | medium | heavy
    response_style: str
    peak_focus_time: str


class Context(BaseModel):
    active_projects: list[str]
    top_collaborators: list[str]
    current_priorities: list[str]


class FOLProfile(BaseModel):
    identity: Identity
    voice: Voice
    behavior: Behavior
    context: Context


class RichProfile(FOLProfile):
    """Extended profile carrying full memory layer data for the chat agent."""
    identity_md: str = ""
    preferences_md: str = ""
    episodic_md: str = ""
    relationships: dict = {}
    voice_raw: dict = {}
    topics: list = []
    behavior_raw: dict = {}
    public_profile: dict = {}


# --- Response Model ---

class OnboardResponse(BaseModel):
    profile: FOLProfile
    sources_used: list[str]  # e.g. ["tavily", "gmail", "calendar"]
    session_id: str
    created_at: str


# --- Chat Models ---

class ChatRequest(BaseModel):
    message: str
    session_id: str


class ActionTaken(BaseModel):
    tool: str
    summary: str
    # Phase 6: whether this action was gated behind user confirmation. Set by
    # the web-tier chat handler when the canonical ConfirmationGate blocked a
    # high-risk tool call (so the UI can surface pending approvals).
    requires_confirmation: bool = False


class ChatResponse(BaseModel):
    response: str
    actions_taken: list[ActionTaken]
