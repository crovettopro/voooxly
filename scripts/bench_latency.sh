#!/bin/bash
# Reproducible STT latency benchmark: generates 3 audio clips with `say`,
# runs them through whisper-server and reports the /inference time.
# Usage: ./scripts/bench_latency.sh   (requires the app open, or
#        whisper-server running on the config port, default 8080)
set -euo pipefail
PORT="${1:-8080}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Liveness check: verify that whisper-server responds
if ! curl -sS --max-time 5 -o /dev/null "http://127.0.0.1:$PORT/"; then
  echo "ERROR: whisper-server no responde en el puerto $PORT. Abre Voooxly (o arranca whisper-server) y reintenta." >&2
  exit 1
fi

frases=(
  "mándame el informe de ventas cuando puedas y lo revisamos juntos mañana"
  "the quarterly report needs three more charts before the board meeting"
  "hola qué tal quería confirmar la reunión del jueves a las cinco"
)
# Known language for each phrase: the bench measures what the app really does
# (with language lock and per-request audio_ctx), not the auto-detection worst case.
langs=(es en es)
i=0
for f in "${frases[@]}"; do
  i=$((i+1))
  say -o "$TMP/f$i.aiff" "$f"
  afconvert -f WAVE -d LEI16@16000 -c 1 "$TMP/f$i.aiff" "$TMP/f$i.wav"
  # Same formula as stt.audio_ctx_for: 75 frames/s rounded up to the next
  # multiple of 256 (Metal kernels are only fast when aligned), capped at 1280,
  # full context above that. Computed BEFORE t0: it does not pollute the measurement.
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
