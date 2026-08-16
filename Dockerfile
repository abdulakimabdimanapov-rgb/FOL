# ────────────────────────────────────────────────────────────────
# FOL — Backend image
# Builds the Python FastAPI backend (src.server) plus the orchestrator.
# The orchestrator needs a desktop (agent-server) to run tools, so the
# container ships the API + LLM layer; desktop automation stays native.
#
# Uses requirements-core.txt (cross-platform deps) — macOS-only packages
# (MLX, pyobjc) are intentionally excluded and live in requirements.txt.
# ────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

COPY . .

EXPOSE 8000 8420

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000"]
