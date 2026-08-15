#!/bin/bash
# Builds ClaudeUsageBar in release mode and wraps it into a double-clickable
# ClaudeUsageBar.app bundle (no Xcode project — this is a plain SPM
# executable; the bundle only exists so Finder/Dock/login-items treat it like
# a normal app instead of a bare binary).
set -euo pipefail

cd "$(dirname "$0")/.."

swift build -c release

APP_DIR="ClaudeUsageBar.app"
CONTENTS_DIR="$APP_DIR/Contents"
rm -rf "$APP_DIR"
mkdir -p "$CONTENTS_DIR/MacOS"

cp .build/release/ClaudeUsageBar "$CONTENTS_DIR/MacOS/ClaudeUsageBar"

cat > "$CONTENTS_DIR/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>ClaudeUsageBar</string>
    <key>CFBundleIdentifier</key>
    <string>com.deviationlabs.ClaudeUsageBar</string>
    <key>CFBundleName</key>
    <string>ClaudeUsageBar</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
</dict>
</plist>
EOF

# Keychain ACLs identify a trusted app by its code-signing designated
# requirement. The linker's automatic ad-hoc signature has no certificate, so
# that requirement degrades to a bare cdhash — which changes on every rebuild,
# invalidating the "Always Allow" grant and re-prompting for consent. Signing
# with a real certificate makes the requirement (bundle id + certificate leaf)
# stable across rebuilds, so consent is granted once.
#
# Prefers an Apple Development identity, else a self-signed certificate named
# $SIGN_IDENTITY. Falls back to ad-hoc so the build never hard-fails on a
# machine with neither; see README "Code signing" for the one-time setup.
SIGN_IDENTITY="${CLAUDE_USAGE_BAR_SIGN_IDENTITY:-ClaudeUsageBar Self-Signed}"
BUNDLE_ID="com.deviationlabs.ClaudeUsageBar"

# Note: this runs under `set -o pipefail`, so no stage may exit early. `head -1`
# or `grep -q` would SIGPIPE the upstream `security` call, and the resulting 141
# would read as "no identity found" even on a successful match. Hence the list is
# captured once, matched with a bash pattern, and trimmed with awk (which drains
# its input) rather than head.
resolve_identity() {
    local identities apple_dev
    identities=$(security find-identity -v -p codesigning 2>/dev/null || true)
    apple_dev=$(printf '%s\n' "$identities" \
        | grep -o '"Apple Development: [^"]*"' | awk 'NR==1' | tr -d '"' || true)
    if [[ -n "$apple_dev" ]]; then
        printf '%s\n' "$apple_dev"
    elif [[ "$identities" == *"$SIGN_IDENTITY"* ]]; then
        printf '%s\n' "$SIGN_IDENTITY"
    fi
}

IDENTITY=$(resolve_identity)
if [[ -n "$IDENTITY" ]]; then
    codesign --force --sign "$IDENTITY" --identifier "$BUNDLE_ID" "$APP_DIR"
    echo "Signed with: $IDENTITY"
else
    echo "WARNING: no codesigning identity found — falling back to ad-hoc." >&2
    echo "         macOS will re-prompt for Keychain access after every rebuild." >&2
    echo "         See README 'Code signing' to create '$SIGN_IDENTITY' once." >&2
fi

echo "Built $APP_DIR — run with: open $APP_DIR"
