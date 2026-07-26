#!/bin/bash
# Local build + deploy of Voooxly.app to /Applications.
#
# - Builds with PyInstaller (the spec already carries the correct bundle_identifier + info_plist)
# - ALWAYS signs in /Applications (in dist/ iCloud re-injects xattrs and signing
#   fails with "resource fork ... detritus not allowed")
# - Signs with the first available identity: "Voooxly Dev" (self-signed, created
#   by scripts/make-cert.sh) or the Developer ID. Either one keeps the TCC
#   permissions stable across rebuilds; ad-hoc invalidates them on every build
#   and Accessibility/Input Monitoring/Microphone must be re-granted.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VOOOXLY_VENV:-$HOME/.voooxly/venv}"
APP=/Applications/Voooxly.app

cd "$ROOT"
# vendor/whisper is not tracked in git (Homebrew binaries): regenerated on the fly
if [ -z "$(ls -A vendor/whisper 2>/dev/null)" ]; then
  echo "→ vendor/whisper empty: vendoring whisper-server from Homebrew…"
  bash scripts/bundle-whisper.sh >/dev/null
fi

echo "→ Compilando con PyInstaller…"
"$VENV/bin/pyinstaller" Voooxly.spec --noconfirm | tail -1

echo "→ Desplegando a /Applications…"
osascript -e 'quit app "Voooxly"' 2>/dev/null || true
pkill -x Voooxly 2>/dev/null || true
# the whisper-server child survives its parent's pkill; if it stays alive, the
# new app reuses the port and keeps serving the OLD MODEL already loaded
pkill -f whisper-server 2>/dev/null || true
sleep 1
rm -rf "$APP"
ditto dist/Voooxly.app "$APP"
xattr -cr "$APP"

IDENTITY=""
IDS="$(security find-identity -v -p codesigning 2>/dev/null || true)"
for candidate in "Voooxly Dev" "Developer ID Application: Eduardo Crovetto"; do
  case "$IDS" in *"$candidate"*) IDENTITY="$candidate"; break ;; esac
done

if [ -n "$IDENTITY" ]; then
  echo "→ Firmando con '$IDENTITY' (firma estable)…"
  codesign --force --deep -s "$IDENTITY" "$APP"
else
  echo "→ Ad-hoc signing (TCC permissions WILL be invalidated! use make-cert.sh)…"
  codesign --force --deep -s - "$APP"
fi

codesign --verify --deep --strict "$APP"
echo "→ OK: $(codesign -d --verbose=2 "$APP" 2>&1 | grep '^Identifier=')"
echo "→ Lanza con: open $APP"
