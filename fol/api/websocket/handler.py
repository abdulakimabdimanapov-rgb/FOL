"""WebSocket handler for real-time communication with FOL."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.websocket.events import (
    EVENT_CONNECTED,
    EVENT_ERROR,
    EVENT_LLM_RESPONSE,
    EVENT_PROACTIVE,
    EVENT_STATUS,
    EVENT_USER_INPUT,
    WSEvent,
    WSMessage,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])

# Connected clients
_clients: set[WebSocket] = set()


async def broadcast(event: WSEvent) -> None:
    """Broadcast an event to all connected clients."""
    message = event.model_dump_json()
    disconnected = set()
    for client in _clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    _clients.difference_update(disconnected)


async def broadcast_proactive(suggestion: Any) -> None:
    """Broadcast a ProactiveSuggestion to all WebSocket clients.

    Receives the suggestion object produced by the canonical ProactiveService
    (via ``FOL.proactive_tick()`` / EventBus) and forwards it as an
    ``EVENT_PROACTIVE`` message. This is the ONLY delivery path from the
    ambient scheduler to the UI — no parallel channel.
    """
    if suggestion is None:
        return
    # ``context`` is a free-form string on the dataclass; the WS contract
    # exposes it as a dict so clients (SwiftUI expects [String: String])
    # always decode successfully.
    raw_context = getattr(suggestion, "context", "") or ""
    payload = {
        "title": getattr(suggestion, "title", ""),
        "description": getattr(suggestion, "description", ""),
        "action": getattr(suggestion, "action", ""),
        "priority": getattr(suggestion, "priority", 0.5),
        "category": getattr(suggestion, "category", "general"),
        "context": {"note": raw_context} if raw_context else {},
    }
    await broadcast(WSEvent(type=EVENT_PROACTIVE, payload=payload))


async def forward_event_proactive(event: Any) -> None:
    """EventBus → WebSocket bridge for ``PROACTIVE_SUGGESTION`` events.

    The single canonical delivery path: the ambient scheduler publishes on
    the EventBus, this subscriber forwards the suggestion to connected
    WebSocket clients. Kept module-level so it is unit-testable.
    """
    suggestion = event.payload.get("suggestion") if event.payload else None
    if suggestion is not None:
        await broadcast_proactive(suggestion)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time FOL communication."""
    await websocket.accept()
    _clients.add(websocket)
    logger.info("WebSocket client connected", total=len(_clients))

    # Send connected event
    await websocket.send_text(
        WSEvent(type=EVENT_CONNECTED, payload={"message": "Connected to FOL"}).model_dump_json()
    )

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = WSMessage.model_validate_json(data)
            except Exception as exc:
                await websocket.send_text(
                    WSEvent(
                        type=EVENT_ERROR,
                        payload={"error": f"Invalid message format: {exc}"},
                    ).model_dump_json()
                )
                continue

            await _handle_message(websocket, msg)

    except WebSocketDisconnect:
        _clients.discard(websocket)
        logger.info("WebSocket client disconnected", total=len(_clients))


async def _handle_message(websocket: WebSocket, msg: WSMessage) -> None:
    """Handle an incoming WebSocket message."""
    if msg.type == EVENT_USER_INPUT:
        text = msg.payload.get("text", "")
        if not text:
            await websocket.send_text(
                WSEvent(type=EVENT_ERROR, payload={"error": "Empty text"}).model_dump_json()
            )
            return

        # Get FOL instance
        import api.rest.server as server_module
        fol = getattr(server_module, "_fol_instance", None)
        if fol is None:
            await websocket.send_text(
                WSEvent(type=EVENT_ERROR, payload={"error": "FOL not initialized"}).model_dump_json()
            )
            return

        try:
            response = await fol.process(text)
            await websocket.send_text(
                WSEvent(
                    type=EVENT_LLM_RESPONSE,
                    payload={"response": response, "input": text},
                ).model_dump_json()
            )
        except Exception as exc:
            logger.error("WebSocket processing error", error=str(exc))
            await websocket.send_text(
                WSEvent(type=EVENT_ERROR, payload={"error": str(exc)}).model_dump_json()
            )

    elif msg.type == "ping":
        await websocket.send_text(
            WSEvent(type=EVENT_STATUS, payload={"status": "pong"}).model_dump_json()
        )

    else:
        await websocket.send_text(
            WSEvent(
                type=EVENT_ERROR,
                payload={"error": f"Unknown event type: {msg.type}"},
            ).model_dump_json()
        )
