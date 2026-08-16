"""Settings routes — view and update FOL settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.rest.models import SettingsResponse, SettingsUpdateRequest

router = APIRouter(prefix="/settings", tags=["settings"])


def _get_fol():
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")
    return fol


@router.get("/", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """Get current FOL settings."""
    fol = _get_fol()
    config = fol.config
    return SettingsResponse(
        app_name=config.app_name,
        debug=config.debug,
        log_level=config.log_level,
        llm_backend=config.llm_backend,
        llm_model=config.llm_model,
        api_host=config.api_host,
        api_port=config.api_port,
    )


@router.patch("/", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdateRequest) -> SettingsResponse:
    """Update FOL settings (runtime only, not persisted)."""
    fol = _get_fol()
    config = fol.config

    if request.debug is not None:
        config.debug = request.debug
    if request.log_level is not None:
        config.log_level = request.log_level
    if request.llm_backend is not None:
        config.llm_backend = request.llm_backend
    if request.llm_model is not None:
        config.llm_model = request.llm_model

    return SettingsResponse(
        app_name=config.app_name,
        debug=config.debug,
        log_level=config.log_level,
        llm_backend=config.llm_backend,
        llm_model=config.llm_model,
        api_host=config.api_host,
        api_port=config.api_port,
    )
