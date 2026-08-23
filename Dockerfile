# ============================================
# FOL — Personal AI Assistant
# Multi-stage Dockerfile for cross-platform deployment
# ============================================

# --------------- Stage 1: Base ---------------
FROM python:3.11-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    libespeak-ng-dev \
    scrot \
    xdotool \
    libnotify-bin \
    pulseaudio \
    alsa-utils \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash fol
WORKDIR /app

# --------------- Stage 2: Dependencies ---------------
FROM base AS deps

# Copy requirements first (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# --------------- Stage 3: Application ---------------
FROM deps AS app

# Copy application code
COPY fol/ ./fol/
COPY orchestrator/ ./orchestrator/
COPY agent-server/ ./agent-server/
COPY analyze/ ./analyze/
COPY auth/ ./auth/
COPY fetch/ ./fetch/
COPY clean/ ./clean/
COPY utils/ ./utils/
COPY context_engine/ ./context_engine/
COPY obsidian/ ./obsidian/
COPY setup/ ./setup/

# Copy config files
COPY .env.example ./.env.template
COPY VERSION ./

# Copy main entry points
COPY main.py ./
COPY run_all.sh ./

# Make scripts executable
RUN chmod +x run_all.sh setup/*.py

# Create logs directory
RUN mkdir -p /app/logs && chown -R fol:fol /app

# Switch to non-root user
USER fol

# --------------- Stage 4: Runtime ---------------
FROM app AS runtime

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/fol \
    HOST=0.0.0.0 \
    PORT=8420 \
    FOL_BRAIN=current \
    FOL_STT_PROVIDER=groq

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8420/status || exit 1

# Expose ports
EXPOSE 8420 8421 8754 3000

# Default command: start all services
CMD ["python3", "orchestrator/server.py"]
