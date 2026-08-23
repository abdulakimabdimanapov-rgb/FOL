#!/usr/bin/env bash
# ============================================
#  FOL — Universal Build Script
#  Builds for all platforms from macOS or Linux
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VERSION=$(cat VERSION 2>/dev/null || echo "1.3.0")

echo "╔══════════════════════════════════════════════════╗"
echo "║    FOL v$VERSION — Universal Build                 ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Detect platform
OS="$(uname -s)"
ARCH="$(uname -m)"

echo "Platform: $OS $ARCH"
echo "Version: $VERSION"
echo ""

# ─── Build macOS DMG ───────────────────────────────
if [[ "$OS" == "Darwin" ]]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Building macOS DMG..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bash "$SCRIPT_DIR/build-macos.sh"
    echo ""
fi

# ─── Build Windows ZIP (from macOS/Linux) ──────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Building Windows package..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
bash "$SCRIPT_DIR/build-windows.sh"
echo ""

# ─── Build Linux packages ──────────────────────────
if [[ "$OS" == "Linux" ]]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Building Linux packages..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    bash "$SCRIPT_DIR/build-linux.sh"
    echo ""
else
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ⚠️  Linux packages need Linux to build"
    echo "  Run on Linux: bash installer/build-linux.sh"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
fi

# ─── Summary ───────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║    Build Complete!                               ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                  ║"
echo "║  Check build/ directory for packages:            ║"
echo "║                                                  ║"

# List all built files
for f in "$PROJECT_ROOT/build"/FOL-*; do
    if [ -f "$f" ] && [[ "$f" != *.sha256 ]]; then
        SIZE=$(du -sh "$f" | cut -f1)
        NAME=$(basename "$f")
        printf "║    %-40s %6s ║\n" "$NAME" "$SIZE"
    fi
done

echo "║                                                  ║"
echo "║  Upload to GitHub Releases:                      ║"
echo "║    gh release create v$VERSION build/FOL-*          ║"
echo "║                                                  ║"
echo "╚══════════════════════════════════════════════════╝"
