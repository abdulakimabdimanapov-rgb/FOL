#!/usr/bin/env bash
# ============================================
#  FOL — Linux Launcher
#  Starts all FOL services on Linux
# ============================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  🧠 FOL — Personal AI Assistant         ║${NC}"
echo -e "${CYAN}║  Linux Edition                           ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[ERROR] Python3 not found.${NC}"
    echo "  Install: sudo apt install python3 python3-pip python3-venv"
    echo "  Or:      sudo dnf install python3 python3-pip"
    exit 1
fi

PYTHON=$(command -v python3)
echo -e "${GREEN}[OK]${NC} Python: $($PYTHON --version)"

# Check .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}[SETUP]${NC} No .env found. Running setup wizard..."
    $PYTHON setup/setup_wizard.py || cp .env.template .env
fi

# Install system dependencies
echo -e "${CYAN}[DEPS]${NC} Checking system dependencies..."

# Audio (for STT)
if ! command -v pactl &> /dev/null && ! command -v arecord &> /dev/null; then
    echo -e "${YELLOW}[WARN]${NC} No audio system found. STT may not work."
    echo "  Install: sudo apt install pulseaudio alsa-utils"
fi

# Screenshot tools
if ! command -v scrot &> /dev/null && ! command -v maim &> /dev/null; then
    echo -e "${YELLOW}[WARN]${NC} No screenshot tool. Installing scrot..."
    sudo apt install -y scrot 2>/dev/null || sudo dnf install -y scrot 2>/dev/null || true
fi

# xdotool (for active window detection)
if ! command -v xdotool &> /dev/null; then
    echo -e "${YELLOW}[WARN]${NC} xdotool not found. Installing..."
    sudo apt install -y xdotool 2>/dev/null || sudo dnf install -y xdotool 2>/dev/null || true
fi

# espeak (for TTS)
if ! command -v espeak-ng &> /dev/null && ! command -v espeak &> /dev/null; then
    echo -e "${YELLOW}[WARN]${NC} espeak not found. Installing..."
    sudo apt install -y espeak-ng 2>/dev/null || sudo dnf install -y espeak-ng 2>/dev/null || true
fi

# notify-send (for notifications)
if ! command -v notify-send &> /dev/null; then
    echo -e "${YELLOW}[WARN]${NC} notify-send not found. Installing..."
    sudo apt install -y libnotify-bin 2>/dev/null || sudo dnf install -y libnotify 2>/dev/null || true
fi

# Install Python dependencies
echo -e "${CYAN}[DEPS]${NC} Installing Python dependencies..."
$PYTHON -m pip install -r requirements.txt --quiet 2>/dev/null || true

echo ""
echo -e "${CYAN}[START]${NC} Starting FOL services..."
echo ""

# Start Orchestrator (port 8420)
echo -e "${GREEN}[1/4]${NC} Starting Orchestrator on port 8420..."
$PYTHON orchestrator/server.py &
ORCH_PID=$!
sleep 3

# Start Agent Server (port 8421)
echo -e "${GREEN}[2/4]${NC} Starting Agent Server on port 8421..."
$PYTHON agent-server/server.py &
AGENT_PID=$!
sleep 2

# Start FOL API (port 8754)
echo -e "${GREEN}[3/4]${NC} Starting FOL API on port 8754..."
$PYTHON fol/main.py &
FOL_PID=$!
sleep 2

# Start Next.js Web (port 3000) — optional
if [ -f "package.json" ]; then
    echo -e "${GREEN}[4/4]${NC} Starting Web UI on port 3000..."
    npm run dev &
    WEB_PID=$!
else
    echo -e "${YELLOW}[4/4]${NC} Web UI skipped (no package.json)"
    WEB_PID=""
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ FOL is running!                      ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  Orchestrator:  http://localhost:8420    ║${NC}"
echo -e "${GREEN}║  Agent Server:  http://localhost:8421    ║${NC}"
echo -e "${GREEN}║  FOL API:       http://localhost:8754    ║${NC}"
echo -e "${GREEN}║  Web UI:        http://localhost:3000    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services.${NC}"

# Cleanup on exit
cleanup() {
    echo ""
    echo -e "${CYAN}[STOP]${NC} Stopping FOL services..."
    kill $ORCH_PID $AGENT_PID $FOL_PID $WEB_PID 2>/dev/null || true
    wait $ORCH_PID $AGENT_PID $FOL_PID $WEB_PID 2>/dev/null || true
    echo -e "${GREEN}[OK]${NC} All services stopped."
}
trap cleanup EXIT INT TERM

# Wait
wait
