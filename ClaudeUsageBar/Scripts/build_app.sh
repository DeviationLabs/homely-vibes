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

echo "Built $APP_DIR — run with: open $APP_DIR"
