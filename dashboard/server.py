"""
Dashboard Server — System monitoring dashboard for FOL.

Serves a web dashboard showing:
  - CPU, RAM, Disk, Network usage
  - Orchestrator status and job state
  - Connected services status
  - Top processes
  - Recent events from episodic memory
  - Active projects

Port: 8423
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

# Ensure sibling modules are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from collector import (
    SERVICES,
    collect_all,
    compute_system_state,
    check_service_health,
    get_llm_status,
    get_memory_status,
    get_ollama_status,
    get_orchestrator_runtime,
    get_orchestrator_status,
    get_orchestrator_health,
    get_recent_events,
    get_dashboard_uptime,
)

PORT = 8423
STATIC_DIR = pathlib.Path(__file__).parent / "static"

app = FastAPI(title="FOL Dashboard", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# WebSocket clients for live updates
ws_clients: list[asyncio.Queue] = []


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "version": "0.1.0",
        "clients": len(ws_clients),
    }


@app.get("/api/metrics")
async def api_metrics():
    """Get all system metrics."""
    try:
        metrics = await asyncio.to_thread(collect_all)
        return metrics
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/orchestrator")
async def api_orchestrator():
    """Get orchestrator status + health."""
    status, health = await asyncio.gather(
        asyncio.to_thread(get_orchestrator_status),
        asyncio.to_thread(get_orchestrator_health),
    )
    return {
        "status": status,
        "health": health,
    }


@app.get("/api/events")
async def api_events():
    """Get recent events from episodic memory."""
    try:
        events = await asyncio.to_thread(get_recent_events, 20)
        return {"events": events, "count": len(events)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/services")
async def api_services():
    """Phase 7: deterministic health check of every service (HTTP, not just port).

    Returns per-service status: ok / degraded / down — never faked.
    """
    services = {}
    for name in SERVICES:
        services[name] = await asyncio.to_thread(check_service_health, name)
    state = compute_system_state(services)
    return {"services": services, "system_state": state}


@app.get("/api/health")
async def api_health():
    """Phase 7: overall system health with automatic degraded-state detection."""
    services = {}
    for name in SERVICES:
        services[name] = await asyncio.to_thread(check_service_health, name)
    state = compute_system_state(services)
    return {
        "status": state["state"],
        "system_state": state,
        "services": services,
        "uptime": await asyncio.to_thread(get_dashboard_uptime),
    }


@app.get("/api/runtime")
async def api_runtime():
    """Phase 7: LLM chain/fallback + agent/task + tool calls + errors + memory + uptime.

    Aggregates the orchestrator's /api/runtime (no secrets) with the
    dashboard's own Ollama + memory checks.
    """
    orch_runtime = await asyncio.to_thread(get_orchestrator_runtime)
    llm = await asyncio.to_thread(get_llm_status)
    ollama = await asyncio.to_thread(get_ollama_status)
    memory = await asyncio.to_thread(get_memory_status)
    uptime = await asyncio.to_thread(get_dashboard_uptime)
    return {
        "orchestrator": orch_runtime,
        "llm": llm,
        "ollama": ollama,
        "memory": memory,
        "dashboard_uptime": uptime,
    }


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard_page():
    """Serve the main dashboard HTML page."""
    index_path = STATIC_DIR / "dashboard.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Dashboard not built</h1><p>Missing static/dashboard.html</p>")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# WebSocket for live metrics
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for live dashboard updates."""
    await websocket.accept()

    # Periodic push of metrics to the dashboard
    try:
        while True:
            try:
                metrics = await asyncio.to_thread(collect_all)
                orch_status = await asyncio.to_thread(get_orchestrator_status)
                orch_runtime = await asyncio.to_thread(get_orchestrator_runtime)
                events = await asyncio.to_thread(get_recent_events, 5)
                llm = await asyncio.to_thread(get_llm_status)
                ollama = await asyncio.to_thread(get_ollama_status)
                memory = await asyncio.to_thread(get_memory_status)

                await websocket.send_text(json.dumps({
                    "type": "metrics",
                    "data": {
                        "metrics": metrics,
                        "orchestrator": orch_status,
                        "runtime": orch_runtime,
                        "events": events,
                        "llm": llm,
                        "ollama": ollama,
                        "memory": memory,
                    }
                }))

                await asyncio.sleep(3)  # Push every 3 seconds
            except WebSocketDisconnect:
                break
            except Exception as e:
                try:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": str(e),
                    }))
                except Exception:
                    break
                await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"  Dashboard: http://localhost:{PORT}")
    print(f"  Metrics API: http://localhost:{PORT}/api/metrics")
    print(f"  WebSocket: ws://localhost:{PORT}/ws")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
