"""FastAPI REST server for FOL with Web UI."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import wave
import tempfile
from pathlib import Path

from fastapi import UploadFile, File

from api.rest.models import HealthResponse

logger = logging.getLogger(__name__)

_fol_instance = None
_start_time: float = 0.0

UI_DIR = Path(__file__).parent.parent.parent / "ui" / "web"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _fol_instance, _start_time
    _start_time = time.time()
    logger.info("FastAPI server starting")
    yield
    logger.info("FastAPI server shutting down")
    if _fol_instance is not None:
        await _fol_instance.stop()
    _fol_instance = None


app = FastAPI(title="F.O.L. API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static assets for the web UI (JS modules etc.) — served under /ui/.
if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")

from api.rest.routes import (
    conversation_router,
    memory_router,
    tools_router,
    plugins_router,
    proactive_router,
    settings_router,
)

app.include_router(conversation_router)
app.include_router(memory_router)
app.include_router(tools_router)
app.include_router(plugins_router)
app.include_router(proactive_router)
app.include_router(settings_router)


# ─── Web UI ───────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """Serve FOL web UI with camera + chat."""
    index_file = UI_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>F.O.L. UI not found</h1>", status_code=404)


@app.post("/api/chat")
async def web_chat(data: dict):
    """Process chat from web UI."""
    if _fol_instance is None:
        return {"response": "FOL not initialized"}
    message = data.get("message", "")
    if not message:
        return {"response": "Empty message"}
    try:
        response = await _fol_instance.process(message)
        return {"response": response}
    except Exception as exc:
        return {"response": f"Error: {exc}"}


@app.get("/api/status")
async def api_status():
    if _fol_instance is None:
        return {"status": "not running"}
    return {
        "status": "running",
        "version": _fol_instance.version,
        "llm": _fol_instance._llm.available_backends if _fol_instance._llm else [],
        "tools": len(_fol_instance._tools.list_all()) if _fol_instance._tools else 0,
        "voice": _fol_instance._voice.status if _fol_instance._voice else None,
    }


# ─── Health ───────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check():
    uptime = time.time() - _start_time if _start_time else 0.0
    modules = {}
    if _fol_instance is not None:
        for name, module in _fol_instance.orchestrator.modules.items():
            modules[name] = "active"
    return HealthResponse(
        status="healthy" if _fol_instance is not None else "starting",
        version="2.0.0",
        uptime=uptime,
        modules=modules,
    )


@app.post("/api/stt")
async def speech_to_text(file: UploadFile = File(...)):
    """Transcribe an audio file to text using FOL's STT engine."""
    if _fol_instance is None:
        return {"text": "", "error": "FOL not initialized"}
    
    if not file.filename:
        return {"text": "", "error": "No file provided"}
    
    tmp_path = None
    try:
        # Save uploaded file to temp location
        suffix = Path(file.filename).suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)
        
        # Transcribe using mlx-whisper (runs on Apple Silicon)
        try:
            import mlx_whisper
            result = await asyncio.to_thread(
                mlx_whisper.transcribe,
                tmp_path,
                temperature=0.0,
                language="ru",
            )
            text = result.get("text", "").strip()
        except ImportError:
            logger.warning("mlx-whisper not installed, using Google STT fallback")
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.AudioFile(tmp_path) as source:
                audio_data = recognizer.record(source)
            try:
                text = recognizer.recognize_google(audio_data, language="ru-RU")
            except Exception:
                text = recognizer.recognize_sphinx(audio_data)
        
        return {"text": text}
    except Exception as exc:
        logger.error("STT endpoint error: %s", exc)
        return {"text": "", "error": str(exc)}
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@app.post("/api/obsidian/save")
async def save_to_obsidian(data: dict):
    """Save content to Obsidian vault."""
    if _fol_instance is None:
        return {"ok": False, "error": "FOL not initialized"}
    content = data.get("content", "")
    category = data.get("category", "Knowledge")
    if not content:
        return {"ok": False, "error": "Empty content"}
    try:
        if _fol_instance._obsidian:
            path = _fol_instance._obsidian.store(content, category=category)
            return {"ok": True, "path": path}
        return {"ok": False, "error": "Obsidian not initialized"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def set_fol_instance(fol) -> None:
    global _fol_instance
    _fol_instance = fol
