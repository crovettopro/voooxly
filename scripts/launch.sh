#!/usr/bin/env bash
# Starts Voooxly (dev, from source) in the background (menu bar). Logs in ~/.voooxly/logs.
# The venv lives in ~/.voooxly/venv (outside iCloud) via UV_PROJECT_ENVIRONMENT.
cd "$(dirname "$0")/.."
export UV_PROJECT_ENVIRONMENT="$HOME/.voooxly/venv"
LOG="$HOME/.voooxly/logs/voooxly.log"

case "${1:-}" in
  --check) exec uv run voooxly --check ;;
  --devices) exec uv run voooxly --devices ;;
  --fg) exec uv run voooxly ;;
esac

mkdir -p "$(dirname "$LOG")"

# idempotent: closes a previous voooxly instance (the whisper-server is reused on its own)
if pgrep -f "voooxly/venv/bin/voooxly" >/dev/null 2>&1 || pgrep -f "uv run voooxly" >/dev/null 2>&1; then
  echo "Cerrando instancia previa…"
  pkill -f "voooxly/venv/bin/voooxly" 2>/dev/null
  pkill -f "uv run voooxly" 2>/dev/null
  sleep 2
fi

nohup uv run voooxly >> "$LOG" 2>&1 &
echo "Voooxly arrancado (PID $!). Log: $LOG"
echo "Permisos: Sistema > Privacidad y seguridad > Accesibilidad + Micrófono."
echo "Stop:  pkill -f 'uv run voooxly'  (or Quit from the 🎙 menu)"