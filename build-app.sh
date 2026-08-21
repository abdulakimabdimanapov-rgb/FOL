#!/bin/bash
# Build FOL as a macOS .app bundle
# Usage: ./build-app.sh
#   Produces: build/FOL.app (drag to /Applications to install)

set -euo pipefail

APP_NAME="FOL"
BUNDLE_ID="com.secondself.app"
BUILD_DIR="$(pwd)/build"
APP_DIR="$BUILD_DIR/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

echo "==> Building FOL (release)..."
cd fol-app
swift build -c release 2>&1 | tail -5

BINARY=$(swift build -c release --show-bin-path)/FOL
if [ ! -f "$BINARY" ]; then
    echo "❌ Build failed — binary not found"
    exit 1
fi
cd ..

echo "==> Assembling $APP_NAME.app in temp dir..."
TEMP_APP=$(mktemp -d)
TEMP_APP_DIR="$TEMP_APP/$APP_NAME.app"
TEMP_CONTENTS="$TEMP_APP_DIR/Contents"
TEMP_MACOS="$TEMP_CONTENTS/MacOS"
TEMP_RESOURCES="$TEMP_CONTENTS/Resources"
mkdir -p "$TEMP_MACOS" "$TEMP_RESOURCES"

# Binary — use cat to strip xattrs (com.apple.provenance survives cp/ditto)
cat "$BINARY" > "$TEMP_MACOS/FOL"
chmod +x "$TEMP_MACOS/FOL"

# Info.plist
cp fol-app/Info.plist "$TEMP_CONTENTS/Info.plist"

# App icon (if it exists in xcassets, extract it; otherwise skip)
ICON_DIR="fol-app/Assets.xcassets/AppIcon.appiconset"
if [ -d "$ICON_DIR" ]; then
    ICON=$(find "$ICON_DIR" -name '*.png' | head -1)
    if [ -n "$ICON" ]; then
        cp "$ICON" "$TEMP_RESOURCES/AppIcon.png"
    fi
fi

# Bundle resource files (twin pose images, colors, etc.)
BUNDLE_RESOURCE=$(find -L fol-app/.build/release -name 'FOL_FOL.bundle' 2>/dev/null | head -1)
if [ -n "$BUNDLE_RESOURCE" ] && [ -d "$BUNDLE_RESOURCE" ]; then
    cp -R "$BUNDLE_RESOURCE" "$TEMP_RESOURCES/FOL_FOL.bundle"
fi

# Strip all extended attributes (com.apple.provenance breaks codesign)
find "$TEMP_APP" -type f -exec xattr -c {} + 2>/dev/null || true
find "$TEMP_APP" -type d -exec xattr -c {} + 2>/dev/null || true

# Remove .DS_Store
find "$TEMP_APP" -name '.DS_Store' -delete 2>/dev/null || true

# PkgInfo
echo -n "APPL????" > "$TEMP_CONTENTS/PkgInfo"

# Use a real Developer ID if available, otherwise ad-hoc sign so the app
# runs locally without Gatekeeper complaints.
IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | awk '/^[0-9]/{print $2; exit}')
if [ -n "$IDENTITY" ]; then
    echo "==> Signing with identity: $IDENTITY"
    codesign --force --deep --sign "$IDENTITY" "$TEMP_APP_DIR" 2>&1 | tail -2
else
    echo "==> No Developer ID found — ad-hoc signing"
    codesign --force --deep --sign - "$TEMP_APP_DIR" 2>&1 | tail -2
fi

# Verify signature
codesign --verify "$TEMP_APP_DIR" 2>&1 && echo "   ✓ Signature verified"

# Move to final location
rm -rf "$APP_DIR"
mv "$TEMP_APP_DIR" "$APP_DIR"
rm -rf "$TEMP_APP"

echo ""
echo "✅ Built: $APP_DIR"
echo "   Size: $(du -sh "$APP_DIR" | cut -f1)"
echo ""
echo "To install:"
echo "   cp -R \"$APP_DIR\" /Applications/"
echo ""
echo "To run:"
echo "   open \"$APP_DIR\""
echo ""
echo "Note: unsigned app — first launch requires:"
echo "   xattr -cr \"$APP_DIR\""
