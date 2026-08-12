#!/bin/bash
# FOL — One-command Update
# Usage: bash update.sh
#
# What it does:
#   1. Reads current version from VERSION file
#   2. Kills all old FOL processes
#   3. Removes old installation
#   4. Builds new .pkg installer
#   5. Installs new version
#   6. Verifies everything works
#
# This is the recommended way to update FOL.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

VERSION="$(cat VERSION 2>/dev/null || echo '0.0.0')"

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  FOL — Update to v$VERSION${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

# ─── Step 1: Check prerequisites ───
echo -e "${YELLOW}[1/6]${NC} Checking prerequisites..."

# Check Python
PYTHON=""
for p in "/opt/homebrew/bin/python3.12" "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "/usr/bin/python3"; do
    [ -x "$p" ] && { PYTHON="$p"; break; }
done
if [ -z "$PYTHON" ]; then
    echo -e "${RED}  ❌ Python 3 not found. Install: brew install python@3.12${NC}"
    exit 1
fi
echo -e "  ✅ Python: $($PYTHON --version 2>&1)"

# Check swift (for building native app)
if command -v swift &>/dev/null; then
    echo -e "  ✅ Swift: $(swift --version 2>&1 | head -1)"
else
    echo -e "  ⚠️  Swift not found — native app won't be rebuilt"
fi

# Check required tools
for tool in xcrun pkgbuild rsync; do
    if command -v "$tool" &>/dev/null; then
        echo -e "  ✅ $tool"
    else
        echo -e "  ❌ $tool not found"
        exit 1
    fi
done

echo ""

# ─── Step 2: Kill old processes ───
echo -e "${YELLOW}[2/6]${NC} Killing old processes..."

for port in 8420 8421 8000; do
    PID=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$PID" ]; then
        echo -e "  Killing process on port $port (PID $PID)..."
        kill "$PID" 2>/dev/null || true
        sleep 1
        # Force kill if still running
        kill -9 "$PID" 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} Port $port freed"
    else
        echo -e "  ${GREEN}✓${NC} Port $port already free"
    fi
done

# Kill any running FOL processes
for proc in orchestrator agent-server "SecondSelf" "Second Self"; do
    PID=$(pgrep -f "$proc" 2>/dev/null || true)
    if [ -n "$PID" ]; then
        echo -e "  Killing $proc (PID $PID)..."
        pkill -f "$proc" 2>/dev/null || true
        sleep 1
    fi
done

# Kill Chrome launched by secondself (only that specific session)
CHROME_PID=$(pgrep -f "chrome.*9222" 2>/dev/null || true)
if [ -n "$CHROME_PID" ]; then
    # Only kill if it's running from secondself's home dir
    CHROME_INFO=$(ps -p "$CHROME_PID" -o command= 2>/dev/null || echo "")
    if echo "$CHROME_INFO" | grep -qi "secondself\|second-self\|/tmp/secondself"; then
        echo -e "  Killing Chrome (CDP session)..."
        kill "$CHROME_PID" 2>/dev/null || true
    fi
fi

# Unload LaunchAgents
for agent in ai.secondself.agent ai.secondself.orchestrator ai.secondself.chrome; do
    if launchctl list | grep -q "$agent" 2>/dev/null; then
        launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/$agent.plist" 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} Unloaded $agent"
    fi
done

echo -e "  ${GREEN}✅ All old processes stopped${NC}"
echo ""

# ─── Step 3: Remove old installation ───
echo -e "${YELLOW}[3/6]${NC} Removing old version..."

# Remove from /Applications
if [ -d "/Applications/Second Self.app" ]; then
    echo -e "  Removing /Applications/Second Self.app..."
    sudo rm -rf "/Applications/Second Self.app"
    echo -e "  ${GREEN}✓${NC} Old app removed"
else
    echo -e "  ${GREEN}✓${NC} No old app found"
fi

# Remove /Applications/SecondSelf.app
if [ -d "/Applications/SecondSelf.app" ]; then
    echo -e "  Removing /Applications/SecondSelf.app..."
    sudo rm -rf "/Applications/SecondSelf.app"
    echo -e "  ${GREEN}✓${NC} Old app removed"
fi

# Remove from /usr/local/share/second-self/ (keep .env for upgrade)
if [ -d "/usr/local/share/second-self" ]; then
    ENV_BACKUP="/tmp/secondself-env-backup"
    if [ -f "/usr/local/share/second-self/.env" ]; then
        cp "/usr/local/share/second-self/.env" "$ENV_BACKUP"
        echo -e "  📝 Backed up .env to $ENV_BACKUP"
    fi
    echo -e "  Removing old /usr/local/share/second-self/..."
    sudo rm -rf "/usr/local/share/second-self"
    echo -e "  ${GREEN}✓${NC} Old installation removed"
    if [ -f "$ENV_BACKUP" ]; then
        sudo mkdir -p "/usr/local/share/second-self"
        sudo cp "$ENV_BACKUP" "/usr/local/share/second-self/.env"
        rm -f "$ENV_BACKUP"
        echo -e "  ✅ .env restored"
    fi
else
    echo -e "  ${GREEN}✓${NC} No old installation found"
fi

echo ""

# ─── Step 4: Build new version ───
echo -e "${YELLOW}[4/6]${NC} Building v$VERSION..."

# Run the build script
bash "$REPO_DIR/build-pkg.sh"

# Find the built .pkg
PKG_FILE=$(ls -t "$REPO_DIR/build/Second-Self-"*.pkg 2>/dev/null | head -1)
if [ -z "$PKG_FILE" ]; then
    echo -e "${RED}  ❌ Build failed — no .pkg file found${NC}"
    exit 1
fi
echo -e "  ${GREEN}✅ Built: $(basename $PKG_FILE)${NC}"
echo ""

# ─── Step 5: Install new version ───
echo -e "${YELLOW}[5/6]${NC} Installing v$VERSION..."

echo -e "  Installing .pkg (may need password)..."
sudo installer -pkg "$PKG_FILE" -target /
echo -e "  ${GREEN}✅ Installation complete${NC}"
echo ""

# ─── Step 6: Verify ───
echo -e "${YELLOW}[6/6]${NC} Verifying installation..."

# Check app exists
if [ -d "/Applications/Second Self.app" ]; then
    APP_SIZE=$(du -sh "/Applications/Second Self.app" | cut -f1)
    echo -e "  ✅ App installed: /Applications/Second Self.app ($APP_SIZE)"
else
    echo -e "  ⚠️  App not found at /Applications/Second Self.app"
fi

# Check shared files
if [ -d "/usr/local/share/second-self" ]; then
    SHARE_SIZE=$(du -sh "/usr/local/share/second-self" | cut -f1)
    echo -e "  ✅ Shared files: /usr/local/share/second-self ($SHARE_SIZE)"
else
    echo -e "  ⚠️  Shared files not found"
fi

# List what's installed
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN}  ✅ FOL v$VERSION installed!${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""
echo "  📍 App:     /Applications/Second Self.app"
echo "  📍 Backend: /usr/local/share/second-self/"
echo ""
echo "  🚀 To start:"
echo "     open /Applications/Second\\ Self.app"
echo ""
echo "  Or run servers manually:"
echo "     python3 orchestrator/server.py     # :8420"
echo "     python3 agent-server/server.py     # :8421"
echo ""
echo "  🧪 To run tests:"
echo "     python3 -m pytest tests/ -v -n auto"
echo ""

# Optional: launch the app (skip if non-interactive)
if [ -t 0 ]; then
    echo -e "${YELLOW}Launch FOL now? (y/n)${NC}"
    read -r LAUNCH_NOW || true
else
    LAUNCH_NOW="n"
fi
if [ "$LAUNCH_NOW" = "y" ] || [ "$LAUNCH_NOW" = "Y" ]; then
    echo "Launching..."
    open "/Applications/Second Self.app"
    echo -e "${GREEN}✅ FOL launched!${NC}"
fi

echo ""
echo -e "${GREEN}Done!${NC}"
