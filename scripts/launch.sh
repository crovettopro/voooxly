#!/usr/bin/env bash
# Arranca Voooxly (dev, desde fuente) en segundo plano (menu bar). Logs en ~/.voooxly/logs.
# El venv vive en ~/.voooxly/venv (fuera de iCloud) vía UV_PROJECT_ENVIRONMENT.
cd "$(dirname "$0")/.."
export UV_PROJECT_ENVIRONMENT="$HOME/.voooxly/venv"
LOG="$HOME/.voooxly/logs/voooxly.log"

case "${1:-}" in
  --check) exec uv run voooxly --check ;;
  --devices) exec uv run voooxly --devices ;;
  --fg) exec uv run voooxly ;;
esac

mkdir -p "$(dirname "$LOG")"

# idempotente: cierra una instancia previa de voooxly (el whisper-server se reutiliza solo)
if pgrep -f "voooxly/venv/bin/voooxly" >/dev/null 2>&1 || pgrep -f "uv run voooxly" >/dev/null 2>&1; then
  echo "Cerrando instancia previa…"
  pkill -f "voooxly/venv/bin/voooxly" 2>/dev/null
  pkill -f "uv run voooxly" 2>/dev/null
  sleep 2
fi

nohup uv run voooxly >> "$LOG" 2>&1 &
echo "Voooxly arrancado (PID $!). Log: $LOG"
echo "Permisos: Sistema > Privacidad y seguridad > Accesibilidad + Micrófono."
echo "Stop:  pkill -f 'uv run voooxly'  (o Cierra desde el menú 🎙)"