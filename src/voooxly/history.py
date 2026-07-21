"""Historial persistente de dictados: ~/.voooxly/history.jsonl.

Cada línea = {"ts", "mode", "text"}. Los dictados son texto sensible: el
fichero va con permisos 0600 y `app.save_history: false` lo apaga entero.
Escritura best-effort — un historial roto jamás debe estorbar al dictado —
y rotación sola: al pasar de MAX_ENTRIES*2 líneas se conservan las últimas
MAX_ENTRIES.
Las búsquedas ignoran mayúsculas y diacríticos (ver _fold): el texto guardado
nunca se altera, el plegado es solo para comparar.
"""
from __future__ import annotations

import json
import logging
import os
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("voooxly.history")

HISTORY_FILE = Path.home() / ".voooxly" / "history.jsonl"
MAX_ENTRIES = 500


def append(text: str, mode: str, path: Path | None = None) -> None:
    path = path or HISTORY_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": mode,
            "text": text,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)
        _rotate(path)
    except Exception as e:
        log.debug("No pude guardar el dictado en el historial: %s", e)


def load(limit: int = 10, path: Path | None = None) -> list[str]:
    """Últimos dictados, el más reciente primero."""
    entries = _read(path or HISTORY_FILE)
    return [e["text"] for e in entries[-limit:]][::-1]


def _fold(s: str) -> str:
    """Minúsculas sin diacríticos: 'Póker' → 'poker', 'Año' → 'ano'.

    Dictas con tildes y luego buscas escribiendo rápido, sin ellas. Comparar
    en crudo hacía que "poker" no encontrara "póker". NFD separa la letra de
    su diacrítico y se descarta el diacrítico. La ñ también se pliega: es lo
    estándar en un buscador en español, y el objetivo es que buscar sea más
    fácil, no más exacto.
    """
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c)).lower()


def search(query: str, limit: int = 10, path: Path | None = None) -> list[str]:
    """Dictados que contienen `query`, ignorando mayúsculas y tildes; recientes primero."""
    q = _fold((query or "").strip())
    if not q:
        return []
    # Se pliegan LOS DOS lados para que la búsqueda sea simétrica: "poker"
    # encuentra "póker" y "póker" encuentra "poker". Plegar solo la consulta
    # arreglaría únicamente la mitad de los casos.
    hits = [e["text"] for e in _read(path or HISTORY_FILE) if q in _fold(e["text"])]
    return hits[-limit:][::-1]


def _read(path: Path) -> list[dict]:
    try:
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
                if isinstance(e, dict) and e.get("text"):
                    entries.append(e)
            except ValueError:
                continue  # línea corrupta (crash a media escritura): se salta
        return entries
    except FileNotFoundError:
        return []
    except Exception as e:
        log.debug("No pude leer el historial: %s", e)
        return []


def _rotate(path: Path) -> None:
    entries = _read(path)
    if len(entries) <= MAX_ENTRIES * 2:
        return
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for e in entries[-MAX_ENTRIES:]:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
