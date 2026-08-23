#!/usr/bin/env bash
# ============================================
#  FOL — One-Click Installer
#  Works on macOS, Ubuntu, Fedora, Arch
# ============================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✅${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠️${NC} $1"; }
fail() { echo -e "  ${RED}❌${NC} $1"; exit 1; }
info() { echo -e "  ${CYAN}ℹ️${NC} $1"; }
step() { echo -e "\n${BOLD}${BLUE}[$1/6]${NC} ${BOLD}$2${NC}"; }

# Banner
echo -e "
${CYAN}${BOLD}╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   🧠  FOL — Personal AI Assistant                       ║
║   One-Click Installer                                    ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝${NC}
"

# ─── Step 1: Check/Install Python ───────────────────────────
step 1 "Checking Python..."

PYTHON=""
for py in python3.12 python3.11 python3.10 python3.9 python3 python; do
    if command -v "$py" &>/dev/null; then
        version=$("$py" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$py"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    warn "Python 3.10+ not found. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            brew install python@3.11
            PYTHON="python3.11"
        else
            fail "Install Homebrew first: https://brew.sh"
        fi
    elif command -v apt &>/dev/null; then
        sudo apt update && sudo apt install -y python3.11 python3.11-venv python3-pip
        PYTHON="python3.11"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3.11 python3.11-pip
        PYTHON="python3.11"
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm python python-pip
        PYTHON="python3"
    fi
fi

ok "Python: $($PYTHON --version)"

# ─── Step 2: Install system dependencies ────────────────────
step 2 "Installing system dependencies..."

if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    if command -v brew &>/dev/null; then
        # Only install what's missing
        for pkg in ffmpeg espeak tmux; do
            if ! command -v $pkg &>/dev/null; then
                brew install $pkg 2>/dev/null &
            fi
        done
        wait
        ok "macOS deps installed via Homebrew"
    else
        warn "Homebrew not found — skipping system deps"
    fi
elif command -v apt &>/dev/null; then
    # Ubuntu/Debian (only missing packages)
    sudo apt update -qq 2>/dev/null
    for pkg in ffmpeg espeak-ng scrot xdotool libnotify-bin; do
        if ! command -v $pkg &>/dev/null; then
            sudo apt install -y -qq $pkg 2>/dev/null &
        fi
    done
    wait
    ok "Debian/Ubuntu deps installed"
elif command -v dnf &>/dev/null; then
    # Fedora/RHEL
    sudo dnf install -y ffmpeg espeak-ng scrot xdotool libnotify 2>/dev/null &
    wait
    ok "Fedora deps installed"
elif command -v pacman &>/dev/null; then
    # Arch
    sudo pacman -S --noconfirm ffmpeg espeak-ng scrot xdotool libnotify 2>/dev/null &
    wait
    ok "Arch deps installed"
else
    warn "Unknown package manager — install deps manually"
fi

# ─── Step 3: Install Python dependencies ────────────────────
step 3 "Installing Python packages..."

# Install only if not already present
if $PYTHON -c "import fastapi" 2>/dev/null; then
    ok "Core packages already installed"
else
    $PYTHON -m pip install --quiet -r requirements.txt 2>/dev/null || warn "Some packages failed"
    ok "Python packages installed"
fi

# Optional: system tray
$PYTHON -c "import pystray" 2>/dev/null || $PYTHON -m pip install --quiet pystray Pillow 2>/dev/null || true

# ─── Step 4: Configure .env ─────────────────────────────────
step 4 "Configuring environment..."

if [ ! -f ".env" ]; then
    cp .env.template .env
    ok "Created .env from template"
else
    ok ".env already exists"
fi

# ─── Step 5: Run setup wizard or validate ───────────────────
step 5 "Setting up API keys..."

if [ -t 0 ]; then
    # Interactive terminal — ask user
    echo ""
    echo -e "  ${BOLD}How do you want to configure API keys?${NC}"
    echo ""
    echo -e "  ${CYAN}1.${NC} Run interactive wizard (recommended)"
    echo -e "  ${CYAN}2.${NC} Skip (configure later)"
    echo ""
    read -p "  Choice [1/2]: " choice

    if [ "$choice" = "1" ]; then
        $PYTHON setup/setup_wizard.py
    else
        info "Skipped. Run later: python3 setup/setup_wizard.py"
    fi
else
    # Non-interactive — just validate what's there
    $PYTHON setup/validate_keys.py --all 2>/dev/null || true
fi

# ─── Step 6: Verify installation ────────────────────────────
step 6 "Verifying installation..."

$PYTHON setup/install_deps.py --verify 2>/dev/null || true

# ─── Done! ──────────────────────────────────────────────────
echo -e "
${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   ✅  FOL installed successfully!                        ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║   Start FOL:                                             ║
║     ./run_all.sh              # all services             ║
║     python3 launch_gui.py     # GUI launcher             ║
║     python3 launch_tray.py    # system tray icon         ║
║                                                          ║
║   Configure keys:                                        ║
║     python3 setup/setup_wizard.py                        ║
║                                                          ║
║   Documentation:                                         ║
║     https://github.com/abdulakimabdimanapov-rgb/SecondSelf║
║                                                          ║
╚══════════════════════════════════════════════════════════╝${NC}
"

# Ask to start
if [ -t 0 ]; then
    echo ""
    read -p "  Start FOL now? [Y/n]: " start
    if [ -z "$start" ] || [ "$start" = "y" ] || [ "$start" = "Y" ]; then
        echo ""
        info "Starting FOL..."
        ./run_all.sh
    fi
fi
