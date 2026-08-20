"""Run FOL REST API server on port 8754.

Usage:
    # From fol-app/ directory:
    python fol/run_api_server.py
"""
import os
import sys
from pathlib import Path

# Ensure `fol/` is in sys.path when running from parent directory
_fol_dir = Path(__file__).parent
if str(_fol_dir) not in sys.path:
    sys.path.insert(0, str(_fol_dir))

os.environ["FOL_LOG_LEVEL"] = "WARNING"

import asyncio
from datetime import datetime

import uvicorn
from core.app import FOL
from api.rest.server import app, set_fol_instance


async def _evening_summary_task(fol, *, hour: int = 18, interval_minutes: int = 15):
    """Background task: once the clock passes ``hour`` (default 18:00), write
    the Freebuff Brain daily summary into the Obsidian Daily note —    once per calendar day. Keeps polling every ``interval_minutes`` so a server
    that starts in the morning still fires in the evening."""
    last_written_date: str = ""
    while True:
        try:
            now = datetime.now()
            if now.hour >= hour and now.strftime("%Y-%m-%d") != last_written_date:
                ok = fol.write_daily_summary_now()
                if ok:
                    last_written_date = now.strftime("%Y-%m-%d")
                    print(
                        f"[daily-summary] Brain summary written for {last_written_date}",
                        flush=True,
                    )
        except Exception as exc:
            print(f"[daily-summary] error: {exc}", flush=True)
        await asyncio.sleep(interval_minutes * 60)


async def _proactive_ambient_task(fol, *, interval_minutes: int = 30):
    """Background task: run one proactive check every ``interval_minutes``.

    Follows the ``_evening_summary_task`` pattern. The feature self-gates:
    when proactive mode is OFF (or in cooldown / at the hourly cap),
    ``FOL.proactive_tick()`` returns None and nothing is emitted. Delivery to
    the UI happens ONLY through the EventBus: ``FOL.proactive_tick()``
    publishes ``PROACTIVE_SUGGESTION`` and the subscriber installed in
    ``startup()`` forwards it to the WebSocket. No parallel channel."""
    while True:
        try:
            suggestion = await fol.proactive_tick()
            if suggestion is not None:
                print(
                    f"[proactive] suggestion: {suggestion.title}",
                    flush=True,
                )
        except Exception as exc:
            print(f"[proactive] error: {exc}", flush=True)
        await asyncio.sleep(interval_minutes * 60)


async def startup():
    print("Initializing FOL...", flush=True)
    fol = FOL()
    await fol.lifecycle.start()
    set_fol_instance(fol)
    llm_backends = fol.orchestrator.get_module("llm")
    tools = fol.orchestrator.get_module("tools")
    tools_count = len(tools.list_all()) if tools else 0
    print(f"FOL v{fol.version} initialized!", flush=True)
    print(f"  LLM backends: {llm_backends.available_backends if llm_backends else 'none'}", flush=True)
    print(f"  Tools: {tools_count}", flush=True)
    # Evening Brain summary: fires automatically after 18:00, once per day.
    _task = asyncio.create_task(_evening_summary_task(fol))
    print(f"  Brain daily-summary task scheduled (after 18:00, once/day)", flush=True)
    # Proactive ambient tick: runs every proactive_interval_minutes, self-gates
    # on the enabled toggle / cooldown / hourly cap. Delivery to the UI goes
    # through the canonical EventBus → WebSocket path (single channel):
    # FOL.proactive_tick() publishes PROACTIVE_SUGGESTION, and the subscriber
    # below (forward_event_proactive) forwards it to WebSocket clients.
    from core.event_bus import EventType
    from api.websocket.handler import forward_event_proactive

    fol.event_bus.subscribe(EventType.PROACTIVE_SUGGESTION, forward_event_proactive)

    proactive_interval = getattr(fol.config, "proactive_interval_minutes", 30)
    _proactive_task = asyncio.create_task(
        _proactive_ambient_task(fol, interval_minutes=proactive_interval)
    )
    print(
        f"  Proactive ambient task scheduled (every {proactive_interval} min, "
        f"enabled={getattr(fol.config, 'proactive_enabled', False)})",
        flush=True,
    )
    return fol


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        fol = loop.run_until_complete(startup())
    except Exception as exc:
        print(f"Failed to initialize FOL: {exc}", flush=True)
        sys.exit(1)

    print(f"\nStarting FOL API server on http://127.0.0.1:8754", flush=True)
    print(f"  Web UI: http://127.0.0.1:8754/", flush=True)
    print(f"  Health: http://127.0.0.1:8754/health", flush=True)
    print(f"  Docs:   http://127.0.0.1:8754/docs", flush=True)
    print(f"  Stop:   Ctrl+C\n", flush=True)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8754,
        log_level="warning",
        loop="auto",
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        loop.run_until_complete(server.serve())
    except OSError:
        print(f"Error: Port 8754 is already in use. Kill existing process or use a different port.", flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutting down FOL API server...", flush=True)
    finally:
        loop.run_until_complete(fol.stop())
        loop.close()
