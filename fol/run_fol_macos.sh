#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# FOL macOS Launcher
# Starts the FOL API server and launches the native macOS notch UI
# ═══════════════════════════════════════════════════════════════════

set -e

FOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MACOS_APP="$FOL_DIR/build/FOL.app"
VENV_PYTHON="$FOL_DIR/.venv/bin/python3"
SYSTEM_PYTHON="/usr/bin/python3"
FOL_PYTHON=""

# Find Python
if [ -f "$VENV_PYTHON" ]; then
    FOL_PYTHON="$VENV_PYTHON"
elif command -v python3.12 &> /dev/null; then
    FOL_PYTHON="python3.12"
elif command -v python3 &> /dev/null; then
    FOL_PYTHON="python3"
else
    echo "❌ Python 3 not found"
    exit 1
fi

# Check if port 8754 is already in use
if lsof -i :8754 -sTCP:LISTEN > /dev/null 2>&1; then
    echo "✅ FOL API server already running on port 8754"
else
    echo "📡 Starting FOL API server..."
    cd "$FOL_DIR"
    nohup "$FOL_PYTHON" run_api_server.py > /dev/null 2>&1 &
    sleep 3
    echo "✅ FOL API server started"
fi

# Launch the native macOS notch app
echo "🖥️  Launching FOL macOS UI..."
open "$MACOS_APP"
