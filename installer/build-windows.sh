#!/usr/bin/env bash
# ============================================
#  FOL — Windows Package Builder
#  Creates: build/FOL-Setup.exe (NSIS) or build/FOL-windows.zip
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VERSION=$(cat VERSION 2>/dev/null || echo "1.3.0")
BUILD_DIR="$PROJECT_ROOT/_build"
PACKAGE_DIR="$BUILD_DIR/windows-package"

echo "============================================"
echo "  Building FOL v$VERSION for Windows"
echo "============================================"
echo ""

# ─── Step 1: Clean ─────────────────────────────────
echo "[1/4] Preparing package..."
rm -rf "$BUILD_DIR"
mkdir -p "$PACKAGE_DIR"

# ─── Step 2: Copy files ────────────────────────────
echo "[2/4] Copying files..."

# Essential Python files
for dir in orchestrator agent-server fol auth fetch clean analyze obsidian context_engine utils setup; do
    [ -d "$dir" ] && rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
        --exclude='.DS_Store' "$dir/" "$PACKAGE_DIR/$dir/"
done

# Essential root files
for f in main.py VERSION requirements.txt requirements-windows.txt run_all.bat install.bat .env.template; do
    [ -f "$f" ] && cp "$f" "$PACKAGE_DIR/"
done

# Setup scripts
mkdir -p "$PACKAGE_DIR/setup"
for f in setup/setup_wizard.py setup/validate_keys.py setup/install_deps.py setup/gui_launcher.py setup/system_tray.py setup/auto_update.py; do
    [ -f "$f" ] && cp "$f" "$PACKAGE_DIR/setup/"
done

echo "  ✅ Files copied: $(du -sh "$PACKAGE_DIR" | cut -f1)"

# ─── Step 3: Create ZIP ────────────────────────────
echo "[3/4] Creating ZIP..."
cd "$BUILD_DIR"
zip -r "FOL-$VERSION-windows.zip" "windows-package/" -q
cd "$PROJECT_ROOT"

ZIP_FILE="$BUILD_DIR/FOL-$VERSION-windows.zip"
echo "  ✅ ZIP created: $(du -sh "$ZIP_FILE" | cut -f1)"

# ─── Step 4: Try NSIS (optional) ───────────────────
echo "[4/4] Checking for NSIS..."
if command -v makensis &>/dev/null; then
    echo "  Building EXE installer with NSIS..."
    makensis "$SCRIPT_DIR/build-windows.nsi" 2>/dev/null && {
        echo "  ✅ EXE installer created: build/FOL-Setup.exe"
    } || {
        echo "  ⚠️ NSIS build failed — ZIP is ready"
    }
else
    echo "  ℹ️  NSIS not found — ZIP is ready"
    echo "     Install NSIS to build .exe: https://nsis.sourceforge.io"
    echo "     Or use: winget install NSIS"
fi

# ─── Generate checksum ─────────────────────────────
shasum -a 256 "$ZIP_FILE" > "$ZIP_FILE.sha256"

echo ""
echo "============================================"
echo "  ✅ FOL v$VERSION — Windows Package Ready"
echo "============================================"
echo ""
echo "  File: $ZIP_FILE"
echo "  Size: $(du -sh "$ZIP_FILE" | cut -f1)"
echo "  SHA256: $(cut -d' ' -f1 "$ZIP_FILE.sha256")"
echo ""
echo "  To install:"
echo "    1. Unzip FOL-$VERSION-windows.zip"
echo "    2. Open the folder"
echo "    3. Double-click install.bat"
echo "    4. Follow the instructions"
echo ""
echo "  Or run directly:"
echo "    1. Unzip FOL-$VERSION-windows.zip"
echo "    2. Double-click run_all.bat"
echo ""
