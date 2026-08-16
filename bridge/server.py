"""
Bridge Server — WebSocket bridge between mobile phone and Mac orchestrator.

Architecture:
  Phone (WebSocket) → Bridge (port 8422) → Orchestrator (port 8420, HTTP)
  
The phone connects via WebSocket, sends chat messages, and receives
responses. The bridge proxies requests to the orchestrator's /command endpoint
in a non-blocking way.

Endpoints:
  GET  /            — serves the mobile companion PWA (index.html)
  GET  /manifest.json  — PWA manifest
  GET  /health      — health check with connected clients count
  WS   /ws          — WebSocket endpoint for mobile phones
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import sys
import urllib.request
import urllib.error
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Response Formatter — sanitizes agent output so the phone only ever sees
# natural-language text (never tool-call JSON or tool names).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "orchestrator"))
from response_formatter import humanize_error  # noqa: E402

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.getenv("BRIDGE_PORT", "8422"))
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8420")
MAX_MESSAGE_LENGTH = 10_000  # max characters per WebSocket message

log = logging.getLogger("bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] bridge: %(message)s")

STATIC_DIR = pathlib.Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# Connected clients
# ---------------------------------------------------------------------------

connected_clients: dict[str, WebSocket] = {}


def _call_orchestrator(endpoint: str, body: dict | None = None, method: str = "POST", timeout: int = 10) -> dict | None:
    """Make a synchronous HTTP call to the orchestrator.
    
    This is meant to be called via asyncio.to_thread() to avoid blocking.
    """
    url = f"{ORCHESTRATOR_URL}{endpoint}"
    try:
        if method == "GET":
            req = urllib.request.Request(url, method="GET")
        else:
            data = json.dumps(body or {}).encode()
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}, method=method
            )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"Orchestrator unreachable: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="FOL Bridge", version="0.1.0")

# Mount static directories for icons, service workers, etc.
ICONS_DIR = STATIC_DIR / "icons"
if ICONS_DIR.exists():
    app.mount("/icons", StaticFiles(directory=str(ICONS_DIR)), name="icons")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_mobile_app():
    """Serve the mobile companion PWA."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse(status_code=404, content={"error": "Mobile app not built"})
    return FileResponse(str(index_path), media_type="text/html")


@app.get("/manifest.json")
async def serve_manifest():
    """Serve the PWA manifest."""
    manifest_path = STATIC_DIR / "manifest.json"
    if not manifest_path.exists():
        return JSONResponse({"name": "FOL", "short_name": "FOL", "start_url": "/"})
    return FileResponse(str(manifest_path), media_type="application/manifest+json")


@app.get("/health")
async def health():
    """Health check."""
    orchestrator = await asyncio.to_thread(
        _call_orchestrator, "/health", method="GET", timeout=5
    )
    return {
        "status": "ok",
        "clients": len(connected_clients),
        "orchestrator": orchestrator,
        "version": "0.1.0",
    }


@app.get("/api/status")
async def orchestrator_status():
    """Proxy to orchestrator /status."""
    result = await asyncio.to_thread(
        _call_orchestrator, "/status", method="GET"
    )
    return result or {"error": "orchestrator unavailable"}


@app.get("/api/memory/identity")
async def get_identity():
    """Read identity profile from disk."""
    identity_path = pathlib.Path.home() / ".secondself" / "identity.md"
    try:
        if identity_path.exists():
            return {"content": identity_path.read_text(encoding="utf-8")}
        return {"content": None, "message": "No identity profile yet"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/memory/recent")
async def get_recent_memory():
    """Read recent episodic events from disk."""
    episodic_path = pathlib.Path.home() / ".secondself" / "episodic.md"
    try:
        if episodic_path.exists():
            lines = episodic_path.read_text(encoding="utf-8").splitlines()
            events = [l for l in lines if l and not l.startswith("#")][-20:]
            return {"events": events}
        return {"events": []}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for mobile phones.
    
    Message format (phone → bridge):
      {"type": "chat", "text": "..."}       — send a chat message
      {"type": "ping"}                      — keepalive ping
      {"type": "status"}                    — request current status
      {"type": "profile", "name": "..."}    — profile a person
    
    Message format (bridge → phone):
      {"type": "token", "text": "..."}      — streaming text token
      {"type": "state", "state": "..."}     — thinking|working|complete|error
      {"type": "activity", "label": "..."} — coarse, user-safe status
      {"type": "system", "message": "..."}  — system notification
      {"type": "error", "message": "..."}   — error
      {"type": "pong"}                      — ping response

    Tool calls are internal actions and are NEVER forwarded to the phone.
    """
    await websocket.accept()
    client_id = uuid.uuid4().hex[:8]
    connected_clients[client_id] = websocket
    
    log.info("Mobile connected: %s (total: %d)", client_id, len(connected_clients))
    
    try:
        # Send welcome with orchestrator status
        health = await asyncio.to_thread(
            _call_orchestrator, "/health", method="GET", timeout=5
        )
        orch_ok = health and health.get("status") == "ok"
        
        await websocket.send_text(json.dumps({
            "type": "system",
            "message": "Connected to FOL" if orch_ok else "Bridge active, orchestrator offline",
            "orchestrator": health,
        }))
        
        while True:
            raw = await websocket.receive_text()
            
            # Message size limit
            if len(raw) > MAX_MESSAGE_LENGTH:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Message too long ({len(raw)} chars, max {MAX_MESSAGE_LENGTH})"
                }))
                continue
            
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": "Invalid JSON"
                }))
                continue
            
            msg_type = msg.get("type", "")
            
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            
            elif msg_type == "chat":
                text = msg.get("text", "").strip()
                if not text:
                    continue
                
                log.info("Chat from %s: %.50s", client_id, text)
                await websocket.send_text(json.dumps({
                    "type": "state",
                    "state": "thinking"
                }))
                
                # Call orchestrator /command in a thread (non-blocking)
                try:
                    result = await asyncio.to_thread(
                        _call_orchestrator, "/command",
                        body={"task": text},
                        timeout=180,  # 3 minutes max for agent loop
                    )
                    
                    if not result:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": "Orchestrator returned empty response"
                        }))
                        continue
                    
                    if "error" in result:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "message": humanize_error(result["error"])
                        }))
                        continue
                    
                    # Send response based on what the orchestrator returned
                    actions = result.get("actions", [])
                    task_result = result.get("task", text)
                    
                    # Response Formatter: prefer the orchestrator's sanitized
                    # natural-language response; fall back to the last complete
                    # action message. Tool calls are internal and never sent.
                    response_text = result.get("response", "")
                    if not response_text:
                        for action in reversed(actions):
                            if action.get("type") == "complete" and action.get("message"):
                                response_text = action.get("message", "")
                                break
                    
                    # Send the final response text
                    if response_text:
                        await websocket.send_text(json.dumps({
                            "type": "token",
                            "text": response_text
                        }))
                    
                    await websocket.send_text(json.dumps({
                        "type": "state",
                        "state": "complete",
                        "message": response_text or "Task processed.",
                    }))
                    
                except asyncio.TimeoutError:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Orchestrator timed out (180s)"
                    }))
                except Exception as e:
                    log.error("Chat error for %s: %s", client_id, e)
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": f"Error: {e}"
                    }))
            
            elif msg_type == "status":
                status = await asyncio.to_thread(
                    _call_orchestrator, "/status", method="GET"
                )
                await websocket.send_text(json.dumps({
                    "type": "status_response",
                    "status": status or {"error": "unavailable"},
                    "memory": {
                        "identity": (pathlib.Path.home() / ".secondself" / "identity.md").exists(),
                        "episodic": (pathlib.Path.home() / ".secondself" / "episodic.md").exists(),
                    }
                }))
            
            elif msg_type == "profile":
                name = msg.get("name", "").strip()
                if not name:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "Name required for profiling"
                    }))
                    continue
                
                result = await asyncio.to_thread(
                    _call_orchestrator, "/profile",
                    body={"name": name},
                    timeout=30,
                )
                await websocket.send_text(json.dumps({
                    "type": "profile_response",
                    "profile": result,
                }))
            
            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "message": f"Unknown type: {msg_type}"
                }))
                
    except WebSocketDisconnect:
        log.info("Mobile disconnected: %s", client_id)
    except Exception as e:
        log.error("WS error for %s: %s", client_id, e)
    finally:
        connected_clients.pop(client_id, None)
        log.info("Client cleaned up: %s (total: %d)", client_id, len(connected_clients))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"[bridge] Port {PORT}")
    print(f"[bridge] Mobile: http://localhost:{PORT}")
    print(f"[bridge] WebSocket: ws://localhost:{PORT}/ws")
    uvicorn.run("bridge.server:app", host="0.0.0.0", port=PORT, reload=True)
