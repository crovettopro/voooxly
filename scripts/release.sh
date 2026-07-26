#!/bin/bash
# Public release of Voooxly: build + Developer ID signing + notarization + DMG.
#
# Unlike deploy.sh (local development, self-signed cert only valid on this
# machine), this produces a DMG that opens on anyone's Mac.
#
# Requirements, one time only — see docs/RELEASING.md:
#   1. "Developer ID Application" certificate installed in the keychain
#   2. Notarization profile stored:
#        xcrun notarytool store-credentials voooxly \
#          --apple-id <email> --team-id <TEAMID> --password <app-specific-password>
#
# Usage: ./scripts/release.sh
#        ./scripts/release.sh --dry-run   (signs with the local cert and does NOT
#                                          notarize: validates the whole mechanics
#                                          without an Apple account)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VOOOXLY_VENV:-$HOME/.voooxly/venv}"
PROFILE="${NOTARY_PROFILE:-voooxly}"
ENTITLEMENTS="$ROOT/voooxly.entitlements"
# The repo lives in ~/Desktop, which is iCloud: it keeps re-injecting extended
# attributes and signing dies with "resource fork ... detritus not allowed".
# All signing and packaging happens outside iCloud.
WORK="$HOME/.voooxly/release"
APP="$WORK/Voooxly.app"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

cd "$ROOT"

# ---------- preflight checks (failing here is cheap; halfway through notarization it is not) ----------
if [ "$DRY_RUN" = "1" ]; then
  # Rehearsal: any local identity is enough to check that the signing loop,
  # dmgbuild and the DMG work. The result is NOT distributable.
  IDENTITY="${RELEASE_IDENTITY:-Voooxly Dev}"
  # The cert is created by scripts/make-cert.sh. If it is missing (e.g. only the
  # project's old-name cert is left), fall back to any other local identity while
  # ANNOUNCING IT: discovering this after a full PyInstaller build costs minutes.
  if ! security find-identity -v -p codesigning 2>/dev/null | grep -q "\"$IDENTITY\""; then
    ALT="$(security find-identity -v -p codesigning 2>/dev/null \
      | grep -v "Developer ID Application" | grep -o '"[^"]*"' | head -1 | tr -d '"' || true)"
    if [ -z "$ALT" ]; then
      echo "ERROR: no local signing identity for the dry run."
      echo "       Create one with: ./scripts/make-cert.sh"
      exit 1
    fi
    echo "⚠️  Certificate '$IDENTITY' not found — using '$ALT' for the dry run."
    echo "    For the right name: ./scripts/make-cert.sh"
    IDENTITY="$ALT"
  fi
  echo "⚠️  DRY RUN: signed with '$IDENTITY' and not notarized. The DMG is not distributable."
else
  IDENTITY="$(security find-identity -v -p codesigning \
    | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)"/\1/' || true)"
  if [ -z "$IDENTITY" ]; then
    echo "ERROR: no 'Developer ID Application' certificate in the keychain."
    echo "       Create it at developer.apple.com — steps in docs/RELEASING.md"
    exit 1
  fi

  if ! xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; then
    echo "ERROR: notarization profile '$PROFILE' does not exist."
    echo "       xcrun notarytool store-credentials $PROFILE --apple-id <email> \\"
    echo "         --team-id <TEAMID> --password <app-specific-password>"
    exit 1
  fi
fi

[ -f "$ENTITLEMENTS" ] || { echo "ERROR: $ENTITLEMENTS is missing"; exit 1; }

VERSION="$(grep -E '"CFBundleShortVersionString"' Voooxly.spec | head -1 | sed -E 's/.*: *"([^"]+)".*/\1/')"
[ -n "$VERSION" ] || { echo "ERROR: could not read the version from Voooxly.spec"; exit 1; }

echo "→ Identity : $IDENTITY"
echo "→ Version  : $VERSION"
echo

# ---------- build ----------
# vendor/whisper is not tracked in git (Homebrew binaries): regenerated on the fly
if [ -z "$(ls -A "$ROOT/vendor/whisper" 2>/dev/null)" ]; then
  echo "→ vendor/whisper empty: vendoring whisper-server from Homebrew…"
  bash "$ROOT/scripts/bundle-whisper.sh" >/dev/null
fi

echo "→ Building with PyInstaller…"
rm -rf "$ROOT/dist/Voooxly.app"
"$VENV/bin/pyinstaller" Voooxly.spec --noconfirm | tail -1

echo "→ Copiando fuera de iCloud ($WORK)…"
rm -rf "$WORK"
mkdir -p "$WORK"
cp -R "$ROOT/dist/Voooxly.app" "$APP"
xattr -cr "$APP"

# ---------- signing ----------
# From the INSIDE OUT: each nested Mach-O first, the bundle last. The
# libggml-* are loaded via dlopen and need their own signature or notarization
# rejects them. --timestamp and --options runtime are mandatory for notarizing.
echo "→ Firmando binarios internos…"
signed=0
while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q "Mach-O"; then
    codesign --force --timestamp --options runtime \
      --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$f" >/dev/null 2>&1 && signed=$((signed+1))
  fi
done < <(find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -111 \) -print0)
echo "  $signed binarios internos firmados"

echo "→ Firmando el bundle…"
codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

# ---------- app notarization ----------
if [ "$DRY_RUN" = "1" ]; then
  echo "→ (dry run: app notarization skipped)"
else
  echo "→ Notarizing the app (this can take a few minutes)…"
  ZIP="$WORK/Voooxly-$VERSION.zip"
  rm -f "$ZIP"
  ditto -c -k --keepParent "$APP" "$ZIP"
  xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
  xcrun stapler staple "$APP"
  rm -f "$ZIP"
fi

# ---------- DMG ----------
echo "→ Construyendo el DMG…"
DMG="$WORK/Voooxly-$VERSION.dmg"
rm -f "$DMG"
# dmgbuild writes the .DS_Store with the window layout and the volume icon,
# things a bare `hdiutil create` cannot set. No Finder involved: deterministic
# and no Automation permission needed. It creates the /Applications symlink
# itself, so a staging folder is no longer necessary.
[ -x "$VENV/bin/dmgbuild" ] || { echo "ERROR: falta dmgbuild en $VENV"; \
  echo "       uv pip install --python $VENV/bin/python 'dmgbuild>=1.6'"; exit 1; }
"$VENV/bin/dmgbuild" -s "$ROOT/scripts/dmg_settings.py" \
  -D app="$APP" -D icon="$ROOT/assets/Voooxly.icns" \
  "Voooxly" "$DMG" >/dev/null

echo "→ Firmando el DMG…"
codesign --force --timestamp -s "$IDENTITY" "$DMG"

SIZE="$(du -h "$DMG" | cut -f1)"

if [ "$DRY_RUN" = "1" ]; then
  echo
  echo "✅ DRY RUN complete: $DMG ($SIZE)"
  echo "   The mechanics work. For a distributable DMG run without --dry-run"
  echo "   once you have the Developer ID certificate (docs/RELEASING.md)."
  exit 0
fi

echo "→ Notarizing the DMG…"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"

# ---------- final verification ----------
# This is literally what Gatekeeper runs on the Mac of whoever downloads it.
echo
echo "→ Final verification (Gatekeeper):"
spctl -a -vvv -t install "$DMG"

echo
echo "✅ Done: $DMG ($SIZE)"
echo
echo "   Next steps:"
echo "   1. Upload the DMG to GitHub Releases under the tag v$VERSION."
echo "      CAREFUL: the file must be NAMED 'Voooxly.dmg', with no version in it."
echo ""
echo "        cp \"$DMG\" \"$WORK/Voooxly.dmg\""
echo "        gh release create v$VERSION \"$WORK/Voooxly.dmg\" --title \"Voooxly $VERSION\""
echo ""
echo "      gh's 'file#Voooxly.dmg' syntax does NOT work: that '#' sets a display"
echo "      LABEL, it does not rename the asset (proven in 1.1.0 — it went up as"
echo "      Voooxly-1.1.0.dmg and the URL 404'd). It has to be copied under the"
echo "      right name before uploading."
echo ""
echo "      appcast.json points at /releases/latest/download/Voooxly.dmg, a FIXED"
echo "      name: if the asset is called anything else that URL 404s and breaks"
echo "      the update for everyone who already has the app."
echo "   2. Set appcast.json (voooxly-web repo) to version $VERSION and deploy with"
echo "      'cd ../voooxly-web && ./deploy.sh' — it refuses to publish the site"
echo "      ahead of the GitHub release. Fill in BOTH \"notes\" and \"notes_es\":"
echo "      that is what the 'Update available' pop-up shows BEFORE downloading."
echo "   3. Check that updates.WHATS_NEW (src/voooxly/updates.py) describes THIS"
echo "      version: it is the 'What's new' pop-up shown after installing. It is"
echo "      refreshed in the same commit that bumps the version."
