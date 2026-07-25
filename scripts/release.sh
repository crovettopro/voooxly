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
      echo "ERROR: no hay identidad de firma local para el ensayo."
      echo "       Créala con: ./scripts/make-cert.sh"
      exit 1
    fi
    echo "⚠️  No existe el certificado '$IDENTITY' — uso '$ALT' para el ensayo."
    echo "    Para el nombre correcto: ./scripts/make-cert.sh"
    IDENTITY="$ALT"
  fi
  echo "⚠️  DRY RUN: firma con '$IDENTITY' y sin notarizar. El DMG no es distribuible."
else
  IDENTITY="$(security find-identity -v -p codesigning \
    | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)"/\1/' || true)"
  if [ -z "$IDENTITY" ]; then
    echo "ERROR: no hay certificado 'Developer ID Application' en el llavero."
    echo "       Créalo en developer.apple.com — pasos en docs/RELEASING.md"
    exit 1
  fi

  if ! xcrun notarytool history --keychain-profile "$PROFILE" >/dev/null 2>&1; then
    echo "ERROR: no existe el perfil de notarización '$PROFILE'."
    echo "       xcrun notarytool store-credentials $PROFILE --apple-id <email> \\"
    echo "         --team-id <TEAMID> --password <app-specific-password>"
    exit 1
  fi
fi

[ -f "$ENTITLEMENTS" ] || { echo "ERROR: falta $ENTITLEMENTS"; exit 1; }

VERSION="$(grep -E '"CFBundleShortVersionString"' Voooxly.spec | head -1 | sed -E 's/.*: *"([^"]+)".*/\1/')"
[ -n "$VERSION" ] || { echo "ERROR: no pude leer la versión de Voooxly.spec"; exit 1; }

echo "→ Identidad : $IDENTITY"
echo "→ Versión   : $VERSION"
echo

# ---------- build ----------
# vendor/whisper is not tracked in git (Homebrew binaries): regenerated on the fly
if [ -z "$(ls -A "$ROOT/vendor/whisper" 2>/dev/null)" ]; then
  echo "→ vendor/whisper vacío: vendorizando whisper-server desde Homebrew…"
  bash "$ROOT/scripts/bundle-whisper.sh" >/dev/null
fi

echo "→ Compilando con PyInstaller…"
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
  echo "→ (dry run: notarización de la app omitida)"
else
  echo "→ Notarizando la app (puede tardar unos minutos)…"
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
  echo "✅ DRY RUN completado: $DMG ($SIZE)"
  echo "   La mecánica funciona. Para un DMG distribuible ejecuta sin --dry-run"
  echo "   una vez tengas el certificado Developer ID (docs/RELEASING.md)."
  exit 0
fi

echo "→ Notarizando el DMG…"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"

# ---------- final verification ----------
# This is literally what Gatekeeper runs on the Mac of whoever downloads it.
echo
echo "→ Verificación final (Gatekeeper):"
spctl -a -vvv -t install "$DMG"

echo
echo "✅ Listo: $DMG ($SIZE)"
echo
echo "   Siguientes pasos:"
echo "   1. Sube el DMG a GitHub Releases con el tag v$VERSION."
echo "      OJO: el fichero tiene que LLAMARSE 'Voooxly.dmg', sin la versión."
echo ""
echo "        cp \"$DMG\" \"$WORK/Voooxly.dmg\""
echo "        gh release create v$VERSION \"$WORK/Voooxly.dmg\" --title \"Voooxly $VERSION\""
echo ""
echo "      NO sirve la sintaxis 'fichero#Voooxly.dmg' de gh: ese '#' pone una"
echo "      ETIQUETA de display, no renombra el asset (comprobado en 1.1.0 —"
echo "      subió como Voooxly-1.1.0.dmg y la URL daba 404). Hay que copiarlo"
echo "      con el nombre bueno antes de subirlo."
echo ""
echo "      appcast.json apunta a /releases/latest/download/Voooxly.dmg, un"
echo "      nombre FIJO: si el asset se llama de otra forma, esa URL da 404 y"
echo "      rompe la actualización de todos los que ya tienen la app."
echo "   2. Actualiza appcast.json (repo voooxly-web) a la versión $VERSION y despliega."
echo "      Rellena su campo \"notes\": es lo que enseña el pop-up de 'Update"
echo "      available' ANTES de descargar."
echo "   3. Comprueba que updates.WHATS_NEW (src/voooxly/updates.py) describe"
echo "      ESTA versión: es el pop-up de 'What's new' que se enseña tras"
echo "      instalarla. Se refresca en el mismo commit que sube la versión."
