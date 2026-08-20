#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# FOL — Unified Launcher
# Запускает все сервисы одним скриптом
# ═══════════════════════════════════════════════════════════════════════

# Don't use set -e — background processes can cause unexpected exits
set +e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║    FOL — Unified Launcher          ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ─── Check Python ────────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo -e "${RED}✗ Python not found!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python: $($PYTHON --version)${NC}"

# ─── Check ports ──────────────────────────────────────────────────
check_port() {
    local port=$1
    if lsof -ti :"$port" > /dev/null 2>&1; then
        return 0
    fi
    return 1
}

kill_port() {
    local port=$1
    local pids
    pids=$(lsof -ti :"$port" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}  Killing process on port $port...${NC}"
        echo "$pids" | xargs kill -9 2>/dev/null || true
        sleep 0.5
    fi
}

# ─── Detached process launcher (Phase 7) ────────────────────────────
# "nohup ... &" processes are killed when the parent shell/session dies
# (observed: services died between terminal sessions). Launching via
# Python's subprocess with start_new_session=True detaches the child into
# its own session so it survives — this is the macOS-compatible setsid.
detach() {
    local log=$1
    shift
    $PYTHON -c "
import subprocess, sys
log = '$log'
p = subprocess.Popen(
    sys.argv[1:],
    stdout=open(log, 'a'), stderr=subprocess.STDOUT,
    start_new_session=True, close_fds=True,
)
print(p.pid)
" "$@" 2>/dev/null
}

# ─── Help ──────────────────────────────────────────────────────────
show_help() {
    echo "Usage: ./run_all.sh [option]"
    echo ""
    echo "Options:"
    echo "  all         Запустить все сервисы (по умолчанию)"
    echo "  fol         Только FOL API (порт 8754)"
    echo "  orchestrator Только Orchestrator (порт 8420)"
    echo "  agent       Только Agent Server (порт 8421)"
    echo "  bridge      Только Bridge (порт 8422)"
    echo "  dashboard   Только Dashboard (порт 8423)"
    echo "  swift       Только SwiftUI приложение"
    echo "  web         Только Next.js web (порт 3000)"
    echo "  stop        Остановить все сервисы"
    echo "  status      Показать статус сервисов"
    echo "  help        Показать эту справку"
    exit 0
}

# ─── Status ────────────────────────────────────────────────────────
show_status() {
    echo -e "${BLUE}── Service Status ──${NC}"
    for service in "8420:Orchestrator" "8421:Agent Server" "8422:Bridge" "8423:Dashboard" "8754:FOL API" "3000:Next.js"; do
        port="${service%%:*}"
        name="${service##*:}"
        if check_port "$port"; then
            echo -e "  ${GREEN}✓${NC} $name (port $port)"
        else
            echo -e "  ${RED}✗${NC} $name (port $port)"
        fi
    done
}

# ─── Stop all ─────────────────────────────────────────────────────
stop_all() {
    echo -e "${YELLOW}Stopping all services...${NC}"
    for port in 8420 8421 8422 8423 8754; do
        kill_port "$port"
    done
    echo -e "${GREEN}✓ All services stopped${NC}"
    exit 0
}

# ─── Start FOL API (port 8754) ────────────────────────────────────
# ─── Start FOL API (port 8754) ────────────────────────────────────
start_fol() {
    echo -e "${BLUE}── Starting FOL API (port 8754) ──${NC}"
    kill_port 8754
    if [ -f "fol/run_api_server.py" ]; then
        cd fol
        FOL_PID=$(detach /tmp/fol_server.log $PYTHON run_api_server.py)
        cd ..
        echo -e "${GREEN}✓ FOL API starting (PID: $FOL_PID, log: /tmp/fol_server.log)${NC}"
    else
        echo -e "${RED}✗ fol/run_api_server.py not found${NC}"
    fi
}

# ─── Start Orchestrator (port 8420) ───────────────────────────────
start_orchestrator() {
    echo -e "${BLUE}── Starting Orchestrator (port 8420) ──${NC}"
    kill_port 8420
    if [ -f "orchestrator/server.py" ]; then
        ORCH_PID=$(detach /tmp/orchestrator.log $PYTHON orchestrator/server.py)
        echo -e "${GREEN}✓ Orchestrator starting (PID: $ORCH_PID, log: /tmp/orchestrator.log)${NC}"
    else
        echo -e "${RED}✗ orchestrator/server.py not found${NC}"
    fi
}

# ─── Start Agent Server (port 8421) ───────────────────────────────
start_agent() {
    echo -e "${BLUE}── Starting Agent Server (port 8421) ──${NC}"
    kill_port 8421
    if [ -f "agent-server/server.py" ]; then
        AGENT_PID=$(detach /tmp/agent_server.log $PYTHON agent-server/server.py)
        echo -e "${GREEN}✓ Agent Server starting (PID: $AGENT_PID, log: /tmp/agent_server.log)${NC}"
    else
        echo -e "${RED}✗ agent-server/server.py not found${NC}"
    fi
}

# ─── Start SwiftUI app ────────────────────────────────────────────
start_swift() {
    echo -e "${BLUE}── Starting SwiftUI app ──${NC}"
    if [ -d "fol-app" ]; then
        cd fol-app
        SWIFT_PID=$(detach /tmp/fol_swift.log swift run)
        cd ..
        echo -e "${GREEN}✓ SwiftUI app starting (PID: $SWIFT_PID, log: /tmp/fol_swift.log)${NC}"
    else
        echo -e "${RED}✗ fol-app/ directory not found${NC}"
    fi
}

# ─── Start Next.js web ────────────────────────────────────────────
start_web() {
    echo -e "${BLUE}── Starting Next.js web (port 3000) ──${NC}"
    if [ -f "package.json" ]; then
        WEB_PID=$(detach /tmp/nextjs.log npm run dev)
        echo -e "${GREEN}✓ Next.js starting (PID: $WEB_PID, log: /tmp/nextjs.log)${NC}"
    else
        echo -e "${RED}✗ package.json not found${NC}"
    fi
}

# ─── Start Bridge (port 8422) ─────────────────────────────────────
start_bridge() {
    echo -e "${BLUE}── Starting Bridge (port 8422) ──${NC}"
    kill_port 8422
    if [ -f "bridge/server.py" ]; then
        BRIDGE_PID=$(detach /tmp/bridge.log $PYTHON -m uvicorn bridge.server:app --host 0.0.0.0 --port 8422)
        echo -e "${GREEN}✓ Bridge starting (PID: $BRIDGE_PID, log: /tmp/bridge.log)${NC}"
    else
        echo -e "${RED}✗ bridge/server.py not found${NC}"
    fi
}

# ─── Start Dashboard (port 8423) ──────────────────────────────────
start_dashboard() {
    echo -e "${BLUE}── Starting Dashboard (port 8423) ──${NC}"
    kill_port 8423
    if [ -f "dashboard/server.py" ]; then
        DASH_PID=$(detach /tmp/dashboard.log $PYTHON -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8423)
        echo -e "${GREEN}✓ Dashboard starting (PID: $DASH_PID, log: /tmp/dashboard.log)${NC}"
    else
        echo -e "${RED}✗ dashboard/server.py not found${NC}"
    fi
}

# ─── Start all ────────────────────────────────────────────────────
start_all() {
    echo -e "${GREEN}Starting all services...${NC}"
    echo ""
    
    # Kill stale processes first
    for port in 8420 8421 8422 8423 8754; do
        kill_port "$port"
    done
    
    sleep 0.5
    
    start_orchestrator
    sleep 2
    start_agent
    sleep 2
    start_fol
    sleep 2
    start_bridge
    sleep 2
    start_dashboard
    sleep 2
    
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  All services started!                           ║${NC}"
    echo -e "${GREEN}║                                                  ║${NC}"
    echo -e "${GREEN}║  Orchestrator : http://localhost:8420             ║${NC}"
    echo -e "${GREEN}║  Agent Server : http://localhost:8421             ║${NC}"
    echo -e "${GREEN}║  Bridge       : http://localhost:8422             ║${NC}"
    echo -e "${GREEN}║  Dashboard    : http://localhost:8423             ║${NC}"
    echo -e "${GREEN}║  FOL API      : http://localhost:8754             ║${NC}"
    echo -e "${GREEN}║  FOL Web UI   : http://localhost:8754/            ║${NC}"
    echo -e "${GREEN}║  Health       : http://localhost:8754/health      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Hint: Run './run_all.sh status' to check service status${NC}"
    echo -e "${YELLOW}      Run './run_all.sh stop'  to stop all services${NC}"
}

# ─── Main ──────────────────────────────────────────────────────────
case "${1:-all}" in
    all)        start_all ;;
    fol)        start_fol ;;
    orchestrator) start_orchestrator ;;
    agent)      start_agent ;;
    bridge)     start_bridge ;;
    dashboard)  start_dashboard ;;
    swift)      start_swift ;;
    web)        start_web ;;
    stop)       stop_all ;;
    status)     show_status ;;
    help|--help|-h) show_help ;;
    *)
        echo -e "${RED}Unknown option: $1${NC}"
        show_help
        ;;
esac
