#!/bin/bash
# Benchmark reproducible de latencia STT: genera 3 audios con `say`,
# los pasa por whisper-server y reporta el tiempo de /inference.
# Uso: ./scripts/bench_latency.sh   (requiere la app abierta o
#      whisper-server corriendo en el puerto de config, default 8080)
set -euo pipefail
PORT="${1:-8080}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

frases=(
  "mándame el informe de ventas cuando puedas y lo revisamos juntos mañana"
  "the quarterly report needs three more charts before the board meeting"
  "hola qué tal quería confirmar la reunión del jueves a las cinco"
)
i=0
for f in "${frases[@]}"; do
  i=$((i+1))
  say -o "$TMP/f$i.aiff" "$f"
  afconvert -f WAVE -d LEI16@16000 -c 1 "$TMP/f$i.aiff" "$TMP/f$i.wav"
  t0=$(python3 -c 'import time; print(time.time())')
  curl -s "http://127.0.0.1:$PORT/inference" \
    -F "file=@$TMP/f$i.wav" -F temperature=0 -F response_format=json >/dev/null
  t1=$(python3 -c 'import time; print(time.time())')
  echo "frase $i: $(python3 -c "print(int(($t1-$t0)*1000))") ms"
done
