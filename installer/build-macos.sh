#!/usr/bin/env bash
# ============================================
#  FOL — macOS Installer Builder
#  Creates: build/FOL.dmg (drag-to-Applications)
# ============================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

APP_NAME="FOL"
VERSION=$(cat VERSION 2>/dev/null || echo "1.3.0")
BUILD_DIR="$PROJECT_ROOT/_build"
DMG_FILE="$BUILD_DIR/FOL-$VERSION.dmg"
APP_DIR="$BUILD_DIR/$APP_NAME.app"

echo "============================================"
echo "  Building FOL v$VERSION for macOS"
echo "============================================"
echo ""

# ─── Step 1: Build Swift app ───────────────────────
echo "[1/5] Building Swift app..."
if [ -d "fol-app" ]; then
    cd fol-app
    if swift build -c release 2>&1 | tail -3; then
        BINARY=$(swift build -c release --show-bin-path 2>/dev/null)/FOL
        if [ -f "$BINARY" ]; then
            echo "  ✅ Swift build OK"
        else
            echo "  ❌ Binary not found"; exit 1
        fi
    else
        echo "  ❌ Swift build failed"; exit 1
    fi
    cd "$PROJECT_ROOT"
else
    echo "  ⚠️ fol-app/ not found — skipping Swift build"
    BINARY=""
fi

# ─── Step 2: Create .app bundle ────────────────────
echo "[2/5] Creating .app bundle..."
rm -rf "$BUILD_DIR/$APP_NAME.app"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

if [ -n "$BINARY" ] && [ -f "$BINARY" ]; then
    cp "$BINARY" "$APP_DIR/Contents/MacOS/$APP_NAME"
    chmod +x "$APP_DIR/Contents/MacOS/$APP_NAME"
fi

# Info.plist — use project's Info.plist
if [ -f "$PROJECT_ROOT/fol-app/Info.plist" ]; then
    cp "$PROJECT_ROOT/fol-app/Info.plist" "$APP_DIR/Contents/Info.plist"
else
cat > "$APP_DIR/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>$APP_NAME</string>
    <key>CFBundleIdentifier</key><string>com.fol.assistant</string>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>FOL — AI Assistant</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>LSUIElement</key><true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
</dict>
</plist>
PLIST
fi
echo -n 'APPL????' > "$APP_DIR/Contents/PkgInfo"

# Icon
ICON_DIR="fol-app/Assets.xcassets/AppIcon.appiconset"
if [ -d "$ICON_DIR" ]; then
    ICON=$(find "$ICON_DIR" -name '*.png' | head -1)
    [ -n "$ICON" ] && cp "$ICON" "$APP_DIR/Contents/Resources/AppIcon.png"
fi

# Resource bundle (twin pose images, etc.)
BUNDLE=$(find -L fol-app/.build/release -name 'FOL_FOL.bundle' 2>/dev/null | head -1)
if [ -n "$BUNDLE" ] && [ -d "$BUNDLE" ]; then
    cp -R "$BUNDLE" "$APP_DIR/Contents/Resources/FOL_FOL.bundle"
fi

# Sign
IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | awk '/^[0-9]/{print $2; exit}')
if [ -n "$IDENTITY" ]; then
    codesign --force --deep --sign "$IDENTITY" "$APP_DIR" 2>/dev/null
    echo "  ✅ Signed with: $IDENTITY"
else
    codesign --force --deep --sign - "$APP_DIR" 2>/dev/null
    echo "  ✅ Ad-hoc signed"
fi

echo "  ✅ .app bundle ready: $(du -sh "$APP_DIR" | cut -f1)"

# ─── Step 3: Bundle Python backend ─────────────────
echo "[3/5] Bundling Python backend..."
BACKEND_DIR="$BUILD_DIR/backend"
rm -rf "$BACKEND_DIR"
mkdir -p "$BACKEND_DIR"

# Copy essential dirs
for dir in orchestrator agent-server fol auth fetch clean analyze obsidian context_engine utils setup; do
    [ -d "$dir" ] && rsync -a --exclude='__pycache__' --exclude='*.pyc' --exclude='.venv' \
        "$dir/" "$BACKEND_DIR/$dir/"
done

# Copy essential files
for f in main.py VERSION requirements.txt requirements-core.txt run_all.sh .env.template; do
    [ -f "$f" ] && cp "$f" "$BACKEND_DIR/"
done

echo "  ✅ Backend bundled: $(du -sh "$BACKEND_DIR" | cut -f1)"

# ─── Step 4: Create DMG ────────────────────────────
echo "[4/5] Creating DMG..."
rm -f "$DMG_FILE"

# Create temporary directory for DMG contents
DMG_TEMP="$BUILD_DIR/dmg-temp"
rm -rf "$DMG_TEMP"
mkdir -p "$DMG_TEMP"

# Copy .app
cp -R "$APP_DIR" "$DMG_TEMP/"

# Create Applications symlink
ln -s /Applications "$DMG_TEMP/Applications"

# Create DMG
hdiutil create -volname "$APP_NAME" \
    -srcfolder "$DMG_TEMP" \
    -ov -format UDZO \
    -imagekey zlib-level=9 \
    "$DMG_FILE"

# Cleanup
rm -rf "$DMG_TEMP"

echo "  ✅ DMG created: $(du -sh "$DMG_FILE" | cut -f1)"

# ─── Step 5: Generate checksum ─────────────────────
echo "[5/5] Generating checksum..."
shasum -a 256 "$DMG_FILE" > "$DMG_FILE.sha256"

echo ""
echo "============================================"
echo "  ✅ FOL v$VERSION — macOS Installer Ready"
echo "============================================"
echo ""
echo "  File: $DMG_FILE"
echo "  Size: $(du -sh "$DMG_FILE" | cut -f1)"
echo "  SHA256: $(cut -d' ' -f1 "$DMG_FILE.sha256")"
echo ""
echo "  To install:"
echo "    1. Open FOL-$VERSION.dmg"
echo "    2. Drag FOL to Applications"
echo "    3. Launch FOL from Applications"
echo "    4. Add your API key in .env"
echo ""
