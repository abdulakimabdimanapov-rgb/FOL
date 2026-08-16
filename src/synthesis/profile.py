"""LLM synthesis — raw data becomes a second self.

Takes emails, calendar events, and Tavily results, feeds them into
one LLM call (any provider), and outputs a structured FOLProfile.
"""

import json

# Canonical LLM path (Phase 6): same bridge the orchestrator uses, with
# transparent fallback to the legacy adapter when fol/ is unavailable.
from orchestrator.llm_bridge import llm_acompletion

from src.models.schemas import (
    CalendarEvent,
    EmailMessage,
    FOLProfile,
)

SYNTHESIS_PROMPT = """\
You are building a digital twin profile for an AI agent that will act on this person's behalf.
Analyze their data carefully. Return ONLY valid JSON, nothing else.

SENT EMAILS (up to 50):
{emails_text}

CALENDAR (next 2 weeks):
{calendar_text}

PUBLIC INFO:
{tavily_results}

Return this exact JSON structure:
{{
  "identity": {{
    "name": "",
    "role": "",
    "company": ""
  }},
  "voice": {{
    "formality": "casual|professional|casual-professional",
    "avg_email_length": "short|medium|long",
    "signature_phrases": [],
    "opens_with": "",
    "closes_with": "",
    "tone": ""
  }},
  "behavior": {{
    "work_hours": "",
    "meeting_load": "light|medium|heavy",
    "response_style": "",
    "peak_focus_time": ""
  }},
  "context": {{
    "active_projects": [],
    "top_collaborators": [],
    "current_priorities": []
  }}
}}
"""


async def build_fol_profile(
    emails: list[EmailMessage],
    calendar_events: list[CalendarEvent],
    tavily_results: str,
) -> FOLProfile:
    """Synthesize a second-self profile from all collected data."""
    emails_text = "\n\n".join(
        f"To: {e.to}\nSubject: {e.subject}\n{e.body}" for e in emails[:50]
    )
    if not emails_text:
        emails_text = "(no email data available)"

    calendar_text = "\n".join(
        f"- {e.title} | {e.start} | {e.attendee_count} attendees | recurring: {e.recurring}"
        for e in calendar_events
    )
    if not calendar_text:
        calendar_text = "(no calendar data available)"

    if not tavily_results:
        tavily_results = "(no public info available)"

    prompt = SYNTHESIS_PROMPT.format(
        emails_text=emails_text,
        calendar_text=calendar_text,
        tavily_results=tavily_results,
    )

    result = await llm_acompletion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
    )

    raw = result.get("content", "")

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]  # remove first line
        raw = raw.rsplit("```", 1)[0]  # remove closing fence

    profile_data = json.loads(raw)
    return FOLProfile(**profile_data)
