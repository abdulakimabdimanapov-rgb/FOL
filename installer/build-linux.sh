#!/usr/bin/env bash
# ============================================
#  FOL — Linux Package Builder
#  Creates: .deb, .tar.gz, AppImage
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VERSION=$(cat VERSION 2>/dev/null || echo "1.3.0")
BUILD_DIR="$PROJECT_ROOT/_build"
PACKAGE_DIR="$BUILD_DIR/linux-package"

echo "============================================"
echo "  Building FOL v$VERSION for Linux"
echo "============================================"
echo ""

# ─── Step 1: Clean ─────────────────────────────────
echo "[1/5] Preparing package..."
rm -rf "$BUILD_DIR"
mkdir -p "$PACKAGE_DIR/opt/fol"
mkdir -p "$PACKAGE_DIR/usr/share/applications"
mkdir -p "$PACKAGE_DIR/usr/bin"
mkdir -p "$PACKAGE_DIR/DEBIAN"

# ─── Step 2: Copy files ────────────────────────────
echo "[2/5] Copying files..."

# Essential Python files
for dir in orchestrator agent-server fol auth fetch clean analyze obsidian context_engine utils setup; do
    [ -d "$dir" ] && rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
        --exclude='.DS_Store' "$dir/" "$PACKAGE_DIR/opt/fol/$dir/"
done

# Essential root files
for f in main.py VERSION requirements.txt requirements-linux.txt run_all_linux.sh .env.template; do
    [ -f "$f" ] && cp "$f" "$PACKAGE_DIR/opt/fol/"
done

# Setup scripts
mkdir -p "$PACKAGE_DIR/opt/fol/setup"
for f in setup/setup_wizard.py setup/validate_keys.py setup/install_deps.py; do
    [ -f "$f" ] && cp "$f" "$PACKAGE_DIR/opt/fol/setup/"
done

echo "  ✅ Files copied: $(du -sh "$PACKAGE_DIR/opt/fol" | cut -f1)"

# ─── Step 3: Create .tar.gz ────────────────────────
echo "[3/5] Creating .tar.gz..."
cd "$BUILD_DIR"
tar -czf "FOL-$VERSION-linux.tar.gz" "linux-package/opt/fol/"
cd "$PROJECT_ROOT"

TAR_FILE="$BUILD_DIR/FOL-$VERSION-linux.tar.gz"
echo "  ✅ TAR created: $(du -sh "$TAR_FILE" | cut -f1)"

# ─── Step 4: Create .deb ───────────────────────────
echo "[4/5] Creating .deb package..."

DEB_DIR="$BUILD_DIR/fol_$VERSION"
rm -rf "$DEB_DIR"
mkdir -p "$DEB_DIR/DEBIAN"
mkdir -p "$DEB_DIR/opt/fol"
mkdir -p "$DEB_DIR/usr/bin"
mkdir -p "$DEB_DIR/usr/share/applications"

# Copy package files
cp -r "$PACKAGE_DIR/opt/fol/"* "$DEB_DIR/opt/fol/"

# Control file
cat > "$DEB_DIR/DEBIAN/control" << CTRL
Package: fol
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pip, python3-venv
Maintainer: FOL Project <fol@example.com>
Homepage: https://github.com/abdulakimabdimanapov-rgb/SecondSelf
Description: FOL — Personal AI Assistant for Linux
 FOL is a smart assistant that lives on your computer.
 It helps with apps, files, browser, and more.
 Supports Russian and English languages.
 Features: voice input, screen control, memory, AI agents.
CTRL

# Post-install script
cat > "$DEB_DIR/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
# Install Python dependencies
cd /opt/fol
python3 -m pip install -r requirements-linux.txt --quiet 2>/dev/null || true

# Create .env if not exists
if [ ! -f /opt/fol/.env ]; then
    cp /opt/fol/.env.template /opt/fol/.env
fi

# Make scripts executable
chmod +x /opt/fol/run_all_linux.sh

echo "FOL installed! Run: /opt/fol/run_all_linux.sh"
POSTINST
chmod 755 "$DEB_DIR/DEBIAN/postinst"

# Pre-remove script
cat > "$DEB_DIR/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
# Stop FOL if running
pkill -f "orchestrator/server.py" 2>/dev/null || true
pkill -f "agent-server/server.py" 2>/dev/null || true
pkill -f "fol/main.py" 2>/dev/null || true
PRERM
chmod 755 "$DEB_DIR/DEBIAN/prerm"

# Launcher script
cat > "$DEB_DIR/usr/bin/fol" << 'LAUNCHER'
#!/bin/bash
cd /opt/fol
exec ./run_all_linux.sh "$@"
LAUNCHER
chmod 755 "$DEB_DIR/usr/bin/fol"

# Desktop file
cat > "$DEB_DIR/usr/share/applications/fol.desktop" << DESKTOP
[Desktop Entry]
Name=FOL
Comment=Personal AI Assistant
Exec=/opt/fol/run_all_linux.sh
Icon=fol
Terminal=true
Type=Application
Categories=Utility;AI;Assistant;
Keywords=ai;assistant;smart;helper;
DESKTOP

# Build .deb
dpkg-deb --build "$DEB_DIR" "$BUILD_DIR/fol_${VERSION}_all.deb" 2>/dev/null && {
    echo "  ✅ .deb created: $(du -sh "$BUILD_DIR/fol_${VERSION}_all.deb" | cut -f1)"
} || {
    echo "  ⚠️ dpkg-deb not found — skipping .deb"
    echo "     Install: sudo apt install dpkg"
}

# ─── Step 5: Create AppImage ───────────────────────
echo "[5/5] Creating AppImage..."

APPIMAGE_DIR="$BUILD_DIR/FOL.AppDir"
rm -rf "$APPIMAGE_DIR"
mkdir -p "$APPIMAGE_DIR/usr/bin"
mkdir -p "$APPIMAGE_DIR/usr/share/applications"
mkdir -p "$APPIMAGE_DIR/usr/share/icons/hicolor/256x256/apps"

# Copy files
cp -r "$PACKAGE_DIR/opt/fol/"* "$APPIMAGE_DIR/usr/bin/"

# Create launcher
cat > "$APPIMAGE_DIR/usr/bin/fol-app" << 'APPIMAGE_LAUNCHER'
#!/bin/bash
cd "$(dirname "$0")"
exec python3 main.py "$@"
APPIMAGE_LAUNCHER
chmod +x "$APPIMAGE_DIR/usr/bin/fol-app"

# Desktop file
cat > "$APPIMAGE_DIR/fol.desktop" << APPDESKTOP
[Desktop Entry]
Name=FOL
Comment=Personal AI Assistant
Exec=fol-app
Icon=fol
Terminal=true
Type=Application
Categories=Utility;
APPDESKTOP

# Try to build AppImage with appimagetool
if command -v appimagetool &>/dev/null; then
    appimagetool "$APPIMAGE_DIR" "$BUILD_DIR/FOL-$VERSION.AppImage" 2>/dev/null && {
        echo "  ✅ AppImage created"
    } || {
        echo "  ⚠️ AppImage build failed — tar.gz is ready"
    }
else
    echo "  ℹ️  appimagetool not found — tar.gz is ready"
    echo "     Install: sudo apt install appimagetool"
fi

# ─── Cleanup ───────────────────────────────────────
rm -rf "$PACKAGE_DIR" "$DEB_DIR" "$APPIMAGE_DIR"

# ─── Generate checksums ────────────────────────────
echo ""
echo "Generating checksums..."
for f in "$BUILD_DIR"/FOL-$VERSION-linux*; do
    [ -f "$f" ] && shasum -a 256 "$f" > "$f.sha256"
done

echo ""
echo "============================================"
echo "  ✅ FOL v$VERSION — Linux Packages Ready"
echo "============================================"
echo ""
echo "  Packages in build/:"
ls -lh "$BUILD_DIR"/FOL-$VERSION-linux* 2>/dev/null || echo "  (check build/ directory)"
echo ""
echo "  Install .deb (Ubuntu/Debian):"
echo "    sudo dpkg -i fol_${VERSION}_all.deb"
echo "    sudo apt install -f"
echo ""
echo "  Install .tar.gz (any Linux):"
echo "    tar -xzf FOL-$VERSION-linux.tar.gz -C /"
echo "    cd /opt/fol && ./run_all_linux.sh"
echo ""
echo "  Install AppImage:"
echo "    chmod +x FOL-$VERSION.AppImage"
echo "    ./FOL-$VERSION.AppImage"
echo ""
