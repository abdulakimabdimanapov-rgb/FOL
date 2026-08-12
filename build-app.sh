#!/bin/bash
# Build FOL as a macOS .app bundle
# Usage: ./build-app.sh
#   Produces: build/Second Self.app (drag to /Applications to install)

set -euo pipefail

APP_NAME="Second Self"
BUNDLE_ID="com.secondself.app"
BUILD_DIR="$(pwd)/build"
APP_DIR="$BUILD_DIR/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

echo "==> Building FOL (release)..."
cd SecondSelf
swift build -c release 2>&1 | tail -5

BINARY=$(swift build -c release --show-bin-path)/SecondSelf
if [ ! -f "$BINARY" ]; then
    echo "❌ Build failed — binary not found"
    exit 1
fi
cd ..

echo "==> Assembling $APP_NAME.app..."
rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$RESOURCES"

# Binary
cp "$BINARY" "$MACOS/SecondSelf"

# Info.plist
cp SecondSelf/Info.plist "$CONTENTS/Info.plist"

# App icon (if it exists in xcassets, extract it; otherwise skip)
ICON_DIR="SecondSelf/Assets.xcassets/AppIcon.appiconset"
if [ -d "$ICON_DIR" ]; then
    # Find the largest png and use it
    ICON=$(find "$ICON_DIR" -name '*.png' | head -1)
    if [ -n "$ICON" ]; then
        cp "$ICON" "$RESOURCES/AppIcon.png"
    fi
fi

# Bundle resource files (twin pose images, colors, etc.)
# swift build processes xcassets into a .bundle — copy it
BUNDLE_RESOURCE=$(find SecondSelf/.build/release -name 'SecondSelf_SecondSelf.bundle' 2>/dev/null | head -1)
if [ -n "$BUNDLE_RESOURCE" ] && [ -d "$BUNDLE_RESOURCE" ]; then
    cp -R "$BUNDLE_RESOURCE" "$RESOURCES/SecondSelf_SecondSelf.bundle"
fi

# PkgInfo
echo -n "APPL????" > "$CONTENTS/PkgInfo"

# ─── Sign ───
# Use a real Developer ID if available, otherwise ad-hoc sign so the app
# runs locally without Gatekeeper complaints.
IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | awk '/^[0-9]/{print $2; exit}')
if [ -n "$IDENTITY" ]; then
    echo "==> Signing with identity: $IDENTITY"
    codesign --force --deep --sign "$IDENTITY" "$APP_DIR" 2>&1 | tail -2
else
    echo "==> No Developer ID found — ad-hoc signing"
    codesign --force --deep --sign - "$APP_DIR" 2>&1 | tail -2
fi

# Verify signature
codesign --verify "$APP_DIR" 2>&1 && echo "   ✓ Signature verified"

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
