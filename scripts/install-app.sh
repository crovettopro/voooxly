#!/bin/bash
# Voooxly fallback installer (for recipients whose Mac refuses to open the app
# because the build wasn't notarized). scripts/package.sh copies this as
# "install.sh" into the shareable zip. If the app IS notarized, dragging
# Voooxly.app to /Applications is all you need — this script is plan B.
#
# What it does:
#   1. Copies Voooxly.app into /Applications
#   2. Strips quarantine and (if not Developer ID-signed) re-signs it ad-hoc
#      ON THIS Mac — which makes Gatekeeper accept it
#   3. Opens the permission panes and explains what to enable
#
# No Homebrew, no model download needed: the speech engine is embedded and
# Voooxly downloads its model on first launch.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$HERE/Voooxly.app"
APP=/Applications/Voooxly.app

echo "══ Voooxly installer ══"

if [ ! -d "$APP_SRC" ]; then
  echo "ERROR: Voooxly.app not found next to this script."; exit 1
fi
if [ "$(uname -m)" != "arm64" ]; then
  echo "WARNING: this build targets Apple Silicon (M1 or newer)."
fi

echo "→ Installing into /Applications…"
osascript -e 'quit app "Voooxly"' 2>/dev/null || true
rm -rf "$APP"
ditto "$APP_SRC" "$APP"
xattr -cr "$APP"

if codesign -dv "$APP" 2>&1 | grep -q "Developer ID"; then
  echo "→ Developer ID signature found — keeping it."
else
  echo "→ Ad-hoc signing on this Mac (avoids Gatekeeper's 'damaged app')…"
  codesign --force --deep -s - "$APP"
fi

echo ""
echo "══ LAST STEP: macOS permissions (manual, once) ══"
echo "In System Settings → Privacy & Security, add /Applications/Voooxly.app"
echo "with the «+» button and enable it in BOTH panes:"
echo "   • Accessibility"
echo "   • Input Monitoring"
echo "The Microphone one is prompted by the app the first time you dictate."
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" || true
open "$APP" || true
echo ""
echo "First launch downloads the speech model (~550MB) — the 🎙 icon shows progress."
