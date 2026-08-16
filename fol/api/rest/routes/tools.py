"""Tools routes — list and execute tools."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.rest.models import (
    ToolExecuteRequest,
    ToolInfo,
    ToolListResponse,
    ToolResultResponse,
)

router = APIRouter(prefix="/tools", tags=["tools"])


def _get_fol():
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")
    return fol


@router.get("/", response_model=ToolListResponse)
async def list_tools() -> ToolListResponse:
    """List all registered tools."""
    fol = _get_fol()
    tools = fol.orchestrator.get_module("tools")
    if tools is None:
        return ToolListResponse(tools=[], total=0)

    tool_list = [
        ToolInfo(
            name=t.name,
            description=t.description,
            parameters=t.parameters,
        )
        for t in tools.list_all()
    ]
    return ToolListResponse(tools=tool_list, total=len(tool_list))


@router.post("/{tool_name}/execute", response_model=ToolResultResponse)
async def execute_tool(tool_name: str, request: ToolExecuteRequest) -> ToolResultResponse:
    """Execute a specific tool by name."""
    fol = _get_fol()
    tools = fol.orchestrator.get_module("tools")
    if tools is None:
        raise HTTPException(status_code=503, detail="Tools module not available")

    result = await tools.execute(tool_name, request.params)
    return ToolResultResponse(
        success=result.success,
        output=result.output,
        error=result.error,
        metadata=result.metadata,
    )


@router.get("/openai-format")
async def get_openai_tools() -> list[dict]:
    """Get tools in OpenAI function calling format."""
    fol = _get_fol()
    tools = fol.orchestrator.get_module("tools")
    if tools is None:
        return []
    return tools.to_openai_tools()
