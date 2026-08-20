#!/bin/bash
# Sign and notarize the FOL PKG for Gatekeeper-clean distribution.
#
# Prerequisites:
#   1. Run ./build-app.sh first (produces build/FOL.app signed with
#      Developer ID Application if a codesigning identity exists).
#   2. Run ./build-pkg.sh (produces build/FOL-<VERSION>.pkg).
#   3. Developer ID Application + Developer ID Installer certs in the login
#      keychain (see below).
#   4. App-specific password stored in Keychain:
#        xcrun notarytool store-credentials "SecondSelf-Notary" \
#          --apple-id "your@email.com" \
#          --team-id "YOUR_TEAM_ID" \
#          --password "app-specific-password"
#
# Getting the certificates (developer.apple.com → Certificates → Create):
#   - "Developer ID Application"  → installs into Keychain, used for the .app
#   - "Developer ID Installer"    → used to sign the .pkg
#   Download the .cer files and double-click them (or run
#   `security add-certificates <file>.cer`). The private keys must be present —
#   generate the CSR with Keychain Access, or export/import a .p12 from the Mac
#   that created the certs.
#
# Usage: ./scripts/sign-and-notarize.sh [PKG_PATH] [--wait]
#   PKG_PATH  optional path to the .pkg (default: newest build/FOL-*.pkg)
#   --wait    block until notarization completes (default: submit and exit)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$REPO_DIR/build"
KEYCHAIN_PROFILE="SecondSelf-Notary"

WAIT=false
PKG_FILE=""
for arg in "$@"; do
    if [ "$arg" = "--wait" ]; then
        WAIT=true
    elif [ -f "$arg" ]; then
        PKG_FILE="$arg"
    fi
done

if [ -z "$PKG_FILE" ]; then
    PKG_FILE=$(ls -t "$BUILD_DIR"/FOL-*.pkg 2>/dev/null | head -1 || true)
fi
if [ -z "$PKG_FILE" ] || [ ! -f "$PKG_FILE" ]; then
    echo "PKG not found. Run ./build-app.sh && ./build-pkg.sh first,"
    echo "or pass the path explicitly: $0 /path/to/FOL-<VERSION>.pkg"
    exit 1
fi
PKG_FILE="$(cd "$(dirname "$PKG_FILE")" && pwd)/$(basename "$PKG_FILE")"

# ─── Find signing identities ───

APP_IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null | awk '/Developer ID Application/{print $2; exit}' || true)
INSTALLER_IDENTITY=$(security find-identity -v 2>/dev/null | awk '/Developer ID Installer/{print $2; exit}' || true)

if [ -z "$APP_IDENTITY" ]; then
    echo "❌ No 'Developer ID Application' certificate found in Keychain."
    echo "   Create it at developer.apple.com → Certificates → Create,"
    echo "   download and install the .cer, then retry."
    exit 1
fi
if [ -z "$INSTALLER_IDENTITY" ]; then
    echo "❌ No 'Developer ID Installer' certificate found in Keychain."
    echo "   Create it at developer.apple.com → Certificates → Create,"
    echo "   download and install the .cer, then retry."
    exit 1
fi

echo "==> Identities found:"
echo "    App:      $APP_IDENTITY"
echo "    Installer: $INSTALLER_IDENTITY"
echo "    PKG:      $PKG_FILE"
echo ""

# ─── Verify the bundled .app is Developer ID signed ───
APP_BUNDLE="$BUILD_DIR/FOL.app"
if [ -d "$APP_BUNDLE" ]; then
    echo "==> Checking .app signature..."
    if codesign --verify --deep "$APP_BUNDLE" 2>&1 && codesign -dv "$APP_BUNDLE" 2>&1 | grep -q "Developer ID Application"; then
        echo "    ✓ .app signed with Developer ID Application"
    else
        echo "    ⚠  .app is NOT Developer ID signed. Re-run ./build-app.sh"
        echo "       after the certificate is installed (it signs automatically"
        echo "       when a codesigning identity is present)."
        exit 1
    fi
fi

# ─── Sign the PKG (if not already signed) ───

echo "==> Checking PKG signature..."
if pkgutil --check-signature "$PKG_FILE" 2>/dev/null | grep -q "Developer ID Installer"; then
    echo "    ✓ PKG already signed"
else
    echo "    PKG is unsigned — signing with Developer ID Installer..."
    SIGNED_PKG="${PKG_FILE%.pkg}-signed.pkg"
    rm -f "$SIGNED_PKG"
    productsign --sign "$INSTALLER_IDENTITY" "$PKG_FILE" "$SIGNED_PKG"
    PKG_FILE="$SIGNED_PKG"
    pkgutil --check-signature "$PKG_FILE" | grep -q "Developer ID Installer" \
        && echo "    ✓ PKG signed" || { echo "    ❌ PKG signing failed"; exit 1; }
fi

# ─── Submit for notarization ───

echo "==> Submitting for notarization..."
echo "    Using keychain profile: $KEYCHAIN_PROFILE"

if [ "$WAIT" = true ]; then
    xcrun notarytool submit "$PKG_FILE" \
        --keychain-profile "$KEYCHAIN_PROFILE" \
        --wait
else
    xcrun notarytool submit "$PKG_FILE" \
        --keychain-profile "$KEYCHAIN_PROFILE"
    echo ""
    echo "Notarization submitted. Check status with:"
    echo "  xcrun notarytool history --keychain-profile $KEYCHAIN_PROFILE"
    echo ""
    echo "Once approved, staple with:"
    echo "  xcrun stapler staple $PKG_FILE"
    exit 0
fi

# ─── Staple the ticket ───

echo "==> Stapling notarization ticket..."
xcrun stapler staple "$PKG_FILE"

# ─── Verify ───

echo "==> Verifying..."
spctl --assess --type install "$PKG_FILE" 2>&1 && echo "    ✓ PKG passes Gatekeeper" || echo "    WARNING: Gatekeeper check failed"

# Regenerate checksum (stapling modifies the file)
shasum -a 256 "$PKG_FILE" > "$PKG_FILE.sha256"

echo ""
echo "Notarized PKG ready: $PKG_FILE"
echo "SHA256: $(cat "$PKG_FILE.sha256")"
echo ""
echo "This PKG will install without any Gatekeeper warnings."
