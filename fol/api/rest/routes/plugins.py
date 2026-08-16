"""Plugins routes — manage plugins."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.rest.models import PluginInfo, PluginListResponse, PluginToggleRequest

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _get_fol():
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")
    return fol


@router.get("/", response_model=PluginListResponse)
async def list_plugins() -> PluginListResponse:
    """List all loaded plugins."""
    fol = _get_fol()
    plugin_manager = fol.orchestrator.get_module("plugin_manager")
    if plugin_manager is None:
        return PluginListResponse(plugins=[], total=0)

    plugins = []
    for p in plugin_manager.list_plugins():
        plugins.append(
            PluginInfo(
                name=p.name,
                version=p.version,
                description=getattr(p, "description", ""),
                enabled=True,
            )
        )
    return PluginListResponse(plugins=plugins, total=len(plugins))


@router.post("/{plugin_name}/enable")
async def enable_plugin(plugin_name: str) -> dict[str, str]:
    """Enable a plugin."""
    fol = _get_fol()
    plugin_manager = fol.orchestrator.get_module("plugin_manager")
    if plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not available")

    success = plugin_manager.enable(plugin_name)
    if success:
        return {"status": "enabled", "plugin": plugin_name}
    raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")


@router.post("/{plugin_name}/disable")
async def disable_plugin(plugin_name: str) -> dict[str, str]:
    """Disable a plugin."""
    fol = _get_fol()
    plugin_manager = fol.orchestrator.get_module("plugin_manager")
    if plugin_manager is None:
        raise HTTPException(status_code=503, detail="Plugin manager not available")

    success = plugin_manager.disable(plugin_name)
    if success:
        return {"status": "disabled", "plugin": plugin_name}
    raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")
