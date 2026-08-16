#!/bin/bash
# Start all FOL services for local mode with Bridge
#
# Usage: ./bridge/start.sh
# Then open:
#   - Next.js web:     http://localhost:3000
#   - Mobile bridge:   http://localhost:8422
#   - Orchestrator:    http://localhost:8420/health

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "═══════════════════════════════════════════"
echo "  FOL — Local AI Mode"
echo "  Model: $(grep LLM_MODEL "$ROOT_DIR/.env" 2>/dev/null | head -1 || echo 'ollama/llama3.2:3b')"
echo "═══════════════════════════════════════════"
echo ""

# Kill any existing processes on our ports
for port in 3000 8000 8420 8421 8422; do
    pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "  Port $port: killing PID $pid..."
        kill -9 $pid 2>/dev/null || true
    fi
done

sleep 1

# Start Agent Server (port 8421)
echo ""
echo "  [1/4] Starting Agent Server on port 8421..."
cd "$ROOT_DIR"
python3 agent-server/server.py &
AGENT_PID=$!
sleep 2

# Start Orchestrator (port 8420)
echo ""
echo "  [2/4] Starting Orchestrator on port 8420..."
cd "$ROOT_DIR"
python3 orchestrator/server.py &
ORCH_PID=$!
sleep 2

# Start Bridge (port 8422)
echo ""
echo "  [3/4] Starting Bridge on port 8422..."
cd "$ROOT_DIR"
python3 bridge/server.py &
BRIDGE_PID=$!
sleep 1

# Start Next.js (port 3000)
echo ""
echo "  [4/4] Starting Next.js on port 3000..."
cd "$ROOT_DIR"
npm run dev &
NEXT_PID=$!

echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ All services started!"
echo ""
echo "  Web UI:        http://localhost:3000"
echo "  Mobile Bridge: http://localhost:8422"
echo "  Orchestrator:  http://localhost:8420/health"
echo "  Agent Server:  http://localhost:8421/health"
echo ""
echo "  Press Ctrl+C to stop all services"
echo "═══════════════════════════════════════════"

# Trap Ctrl+C to kill all background processes
trap "echo 'Stopping all services...'; kill $AGENT_PID $ORCH_PID $BRIDGE_PID $NEXT_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# Wait for any background process to exit
wait
