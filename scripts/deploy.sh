#!/bin/bash
# Build + deploy local de Voooxly.app a /Applications.
#
# - Compila con PyInstaller (el spec ya lleva bundle_identifier + info_plist correctos)
# - Firma SIEMPRE en /Applications (en dist/ iCloud re-inyecta xattrs y la firma
#   falla con "resource fork ... detritus not allowed")
# - Firma con la primera identidad disponible: "Voooxly Dev" (autofirmada, la
#   crea scripts/make-cert.sh) o el Developer ID. Cualquiera de las dos mantiene
#   los permisos TCC estables entre rebuilds; ad-hoc los invalida en cada build
#   y hay que re-conceder Accesibilidad/Monitorización/Micrófono.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${VOOOXLY_VENV:-$HOME/.voooxly/venv}"
APP=/Applications/Voooxly.app

cd "$ROOT"
# vendor/whisper no viaja en git (binarios de Homebrew): se regenera al vuelo
if [ -z "$(ls -A vendor/whisper 2>/dev/null)" ]; then
  echo "→ vendor/whisper vacío: vendorizando whisper-server desde Homebrew…"
  bash scripts/bundle-whisper.sh >/dev/null
fi

echo "→ Compilando con PyInstaller…"
"$VENV/bin/pyinstaller" Voooxly.spec --noconfirm | tail -1

echo "→ Desplegando a /Applications…"
osascript -e 'quit app "Voooxly"' 2>/dev/null || true
pkill -x Voooxly 2>/dev/null || true
# el whisper-server hijo sobrevive al pkill del padre; si queda vivo, la app
# nueva reutiliza el puerto y sigue sirviendo el MODELO VIEJO ya cargado
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
  echo "→ Firmando ad-hoc (¡los permisos TCC se invalidarán! usa make-cert.sh)…"
  codesign --force --deep -s - "$APP"
fi

codesign --verify --deep --strict "$APP"
echo "→ OK: $(codesign -d --verbose=2 "$APP" 2>&1 | grep '^Identifier=')"
echo "→ Lanza con: open $APP"
