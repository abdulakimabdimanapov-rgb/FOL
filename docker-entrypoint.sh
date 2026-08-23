#!/bin/bash
# ============================================
# FOL — Docker Entrypoint
# Starts services based on the command argument
# ============================================

set -e

echo "╔══════════════════════════════════════════╗"
echo "║  🧠 FOL — Docker Container              ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check Python
echo "✅ Python: $(python3 --version)"

# Check .env
if [ ! -f ".env" ]; then
    echo "⚠️  No .env found — using environment variables"
fi

# Function to start orchestrator
start_orchestrator() {
    echo "🚀 Starting Orchestrator on port 8420..."
    exec python3 orchestrator/server.py
}

# Function to start agent server
start_agent() {
    echo "🚀 Starting Agent Server on port 8421..."
    exec python3 agent-server/server.py
}

# Function to start FOL API
start_fol_api() {
    echo "🚀 Starting FOL API on port 8754..."
    exec python3 fol/main.py
}

# Function to start all services
start_all() {
    echo "🚀 Starting all services..."

    # Start orchestrator in background
    python3 orchestrator/server.py &
    ORCH_PID=$!

    # Wait for orchestrator
    sleep 3

    # Start agent server in background
    python3 agent-server/server.py &
    AGENT_PID=$!

    # Wait for agent server
    sleep 2

    # Start FOL API in foreground (keeps container alive)
    echo "✅ All services started"
    exec python3 fol/main.py
}

# Parse command
case "${1:-orchestrator}" in
    orchestrator|orch)
        start_orchestrator
        ;;
    agent|agent-server)
        start_agent
        ;;
    fol-api|fol)
        start_fol_api
        ;;
    all|full)
        start_all
        ;;
    bash|sh|shell)
        exec /bin/bash
        ;;
    *)
        echo "Unknown command: $1"
        echo ""
        echo "Usage: docker run fol-app [command]"
        echo ""
        echo "Commands:"
        echo "  orchestrator  — Start orchestrator (port 8420) [default]"
        echo "  agent         — Start agent server (port 8421)"
        echo "  fol-api       — Start FOL API (port 8754)"
        echo "  all           — Start all services"
        echo "  shell         — Open bash shell"
        exit 1
        ;;
esac
