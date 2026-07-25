#!/bin/bash
# Vendors whisper-server (from Homebrew) into the repo → vendor/whisper/
# so Voooxly.app carries it EMBEDDED and the recipient does not need Homebrew.
#
# - Copies the binary + dylib closure (libwhisper, libggml*)
# - IMPORTANT: ggml loads its backends (libggml-cpu/metal/blas) via dlopen
#   from its own directory → ALL the libggml-* get copied
# - Rewrites the install names to @loader_path (everything flat in one dir)
# - Re-signs each Mach-O ad-hoc (the final signature is applied by deploy/package)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/vendor/whisper"
BIN="${WHISPER_SERVER:-/opt/homebrew/bin/whisper-server}"
SEARCH_DIRS=(/opt/homebrew/opt/whisper-cpp/lib /opt/homebrew/opt/ggml/lib /opt/homebrew/lib)

[ -x "$BIN" ] || { echo "ERROR: no encuentro whisper-server ($BIN). brew install whisper-cpp"; exit 1; }

rm -rf "$OUT"; mkdir -p "$OUT"
cp -f "$(realpath "$BIN")" "$OUT/whisper-server"

resolve() {  # dep ref → real path on disk
  local ref="$1"
  if [[ "$ref" == @rpath/* ]]; then
    local name="${ref#@rpath/}"
    for d in "${SEARCH_DIRS[@]}"; do
      [ -e "$d/$name" ] && { realpath "$d/$name"; return; }
    done
    return 1
  fi
  [ -e "$ref" ] && realpath "$ref"
}

# BFS closure of homebrew/@rpath dependencies
copied=1
while [ "$copied" -eq 1 ]; do
  copied=0
  for f in "$OUT"/*; do
    while IFS= read -r dep; do
      name="$(basename "$dep" )"
      if [ ! -e "$OUT/$name" ]; then
        src="$(resolve "$dep")" || { echo "ERROR: no resuelvo $dep"; exit 1; }
        cp -f "$src" "$OUT/$name"
        copied=1
      fi
    done < <(otool -L "$f" | tail -n +2 | awk '{print $1}' | grep -E '^(@rpath/|/opt/homebrew/)' || true)
  done
done

# ggml's dlopen backends (Metal/CPU/BLAS): they live as .so in libexec/ and ggml
# looks for them at a COMPILED-IN path that does not exist on other Macs → copy
# them here and stt.py exports GGML_BACKEND_PATH when launching the embedded server.
for lib in /opt/homebrew/opt/ggml/libexec/*.so; do
  [ -e "$lib" ] || continue
  name="$(basename "$lib")"
  [ -e "$OUT/$name" ] || cp -f "$(realpath "$lib")" "$OUT/$name"
done

# second closure pass: the .so files bring deps of their own
for f in "$OUT"/*.so; do
  [ -e "$f" ] || continue
  while IFS= read -r dep; do
    name="$(basename "$dep")"
    if [ ! -e "$OUT/$name" ]; then
      src="$(resolve "$dep")" || { echo "ERROR: no resuelvo $dep"; exit 1; }
      cp -f "$src" "$OUT/$name"
    fi
  done < <(otool -L "$f" | tail -n +2 | awk '{print $1}' | grep -E '^(@rpath/|/opt/homebrew/)' || true)
done

# install-name rewrite → @loader_path (flat dir)
for f in "$OUT"/*; do
  base="$(basename "$f")"
  if [[ "$base" == *.dylib || "$base" == *.so ]]; then
    install_name_tool -id "@loader_path/$base" "$f" 2>/dev/null
  fi
  while IFS= read -r dep; do
    install_name_tool -change "$dep" "@loader_path/$(basename "$dep")" "$f" 2>/dev/null
  done < <(otool -L "$f" | tail -n +2 | awk '{print $1}' | grep -E '^(@rpath/|/opt/homebrew/)' || true)
  codesign --force -s - "$f" 2>/dev/null
done

echo "OK: $(ls "$OUT" | wc -l | tr -d ' ') ficheros en vendor/whisper ($(du -sh "$OUT" | cut -f1))"
ls -la "$OUT"