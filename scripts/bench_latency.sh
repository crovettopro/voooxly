#!/bin/bash
# Benchmark reproducible de latencia STT: genera 3 audios con `say`,
# los pasa por whisper-server y reporta el tiempo de /inference.
# Uso: ./scripts/bench_latency.sh   (requiere la app abierta o
#      whisper-server corriendo en el puerto de config, default 8080)
set -euo pipefail
PORT="${1:-8080}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Comprobación de vida: verifica que whisper-server responde
if ! curl -sS --max-time 5 -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "ERROR: whisper-server no responde en el puerto $PORT. Abre Voooxly (o arranca whisper-server) y reintenta." >&2
  exit 1
fi

frases=(
  "mándame el informe de ventas cuando puedas y lo revisamos juntos mañana"
  "the quarterly report needs three more charts before the board meeting"
  "hola qué tal quería confirmar la reunión del jueves a las cinco"
)
# Idioma conocido de cada frase: el bench mide lo que la app hace de verdad
# (con lock de idioma y audio_ctx por petición), no el peor caso de auto-detección.
langs=(es en es)
i=0
for f in "${frases[@]}"; do
  i=$((i+1))
  say -o "$TMP/f$i.aiff" "$f"
  afconvert -f WAVE -d LEI16@16000 -c 1 "$TMP/f$i.aiff" "$TMP/f$i.wav"
  # Misma fórmula que stt.audio_ctx_for: 75 frames/s redondeados al múltiplo
  # de 256 superior (los kernels Metal solo van rápidos alineados), tope 1280,
  # por encima contexto completo. Se calcula ANTES de t0: no contamina la medición.
  ctx=$(python3 -c "
import math, sys, wave
w = wave.open(sys.argv[1])
d = w.getnframes() / w.getframerate()
c = max(1, math.ceil(d * 75 / 256)) * 256 if d > 0 else 0
print(c if 0 < c <= 1280 else '')
" "$TMP/f$i.wav")
  extra=()
  [ -n "$ctx" ] && extra+=(-F "audio_ctx=$ctx")
  t0=$(python3 -c 'import time; print(time.time())')
  if ! curl -sS --fail --max-time 60 "http://127.0.0.1:$PORT/inference" \
    -F "file=@$TMP/f$i.wav" -F temperature=0 -F response_format=json \
    -F "language=${langs[$((i-1))]}" "${extra[@]}" >/dev/null; then
    echo "ERROR: /inference falló en la frase $i" >&2
    exit 1
  fi
  t1=$(python3 -c 'import time; print(time.time())')
  echo "frase $i: $(python3 -c "print(int(($t1-$t0)*1000))") ms"
done
