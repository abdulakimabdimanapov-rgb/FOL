"""Proactive routes — status, toggle and on-demand check for Proactive Mode.

Follows the existing FOL REST conventions (see ``api/rest/routes/settings.py``):
a ``_get_fol()`` helper that raises 503 when FOL is not initialized, Pydantic
response models from ``api.rest.models``, and an ``APIRouter`` registered in
``api/rest/server.py``. All suggestions flow through the canonical path
``ProactiveService → EventBus → WebSocket`` — this router only triggers ticks
and reads status, it never duplicates delivery.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.rest.models import (
    ProactiveCheckResponse,
    ProactiveConfirmRequest,
    ProactiveDismissRequest,
    ProactiveDismissResponse,
    ProactiveExecuteRequest,
    ProactiveExecuteResponse,
    ProactiveStatusResponse,
    ProactiveToggleRequest,
)

router = APIRouter(prefix="/proactive", tags=["proactive"])


def _get_fol():
    """Return the live FOL instance or raise 503 (existing convention)."""
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")
    return fol


def _require_proactive(fol):
    """Initialize Proactive Mode and raise 500 if it is unavailable."""
    fol._init_proactive()
    if fol._proactive is None:
        raise HTTPException(status_code=500, detail="Proactive mode not available")
    return fol._proactive


@router.get("/status", response_model=ProactiveStatusResponse)
async def proactive_status() -> ProactiveStatusResponse:
    """Get proactive mode status (enabled, session stats, cap usage)."""
    fol = _get_fol()
    service = _require_proactive(fol)
    return ProactiveStatusResponse(**service.stats())


@router.post("/toggle", response_model=ProactiveStatusResponse)
async def proactive_toggle(request: ProactiveToggleRequest) -> ProactiveStatusResponse:
    """Enable or disable proactive mode (runtime, not persisted)."""
    fol = _get_fol()
    service = _require_proactive(fol)
    if request.enabled:
        fol._proactive_on("en")
    else:
        fol._proactive_off("en")
    return ProactiveStatusResponse(**service.stats())


@router.post("/check", response_model=ProactiveCheckResponse)
async def proactive_check() -> ProactiveCheckResponse:
    """Run one proactive evaluation now (force — bypasses cooldown/cap).

    The suggestion is published on the EventBus (``PROACTIVE_SUGGESTION``)
    and returned in the payload for the calling client.
    """
    fol = _get_fol()
    service = _require_proactive(fol)
    suggestion = await fol.proactive_tick(force=True)
    return ProactiveCheckResponse(
        enabled=service.enabled,
        suggestion=suggestion.__dict__ if suggestion is not None else None,
    )


@router.post("/execute", response_model=ProactiveExecuteResponse)
async def proactive_execute(request: ProactiveExecuteRequest) -> ProactiveExecuteResponse:
    """Execute a proactive suggestion's action through the safe FOL path.

    Unknown actions are rejected (fail closed); risky tools are blocked by
    the canonical ConfirmationGate until the user approves via
    ``POST /proactive/confirm``. Never executes automatically.
    """
    fol = _get_fol()
    _require_proactive(fol)
    result = await fol.execute_proactive_action(request.action)
    return ProactiveExecuteResponse(**result)


@router.post("/confirm", response_model=ProactiveExecuteResponse)
async def proactive_confirm(request: ProactiveConfirmRequest) -> ProactiveExecuteResponse:
    """Approve a gated proactive action (ConfirmationGate) and execute it."""
    fol = _get_fol()
    _require_proactive(fol)
    result = await fol.confirm_proactive_action(request.action_id, request.action)
    return ProactiveExecuteResponse(**result)


@router.post("/dismiss", response_model=ProactiveDismissResponse)
async def proactive_dismiss(request: ProactiveDismissRequest) -> ProactiveDismissResponse:
    """Dismiss a proactive suggestion so it is not re-emitted immediately."""
    fol = _get_fol()
    service = _require_proactive(fol)
    dismissed = await service.dismiss(request.title)
    return ProactiveDismissResponse(ok=dismissed, title=request.title)
