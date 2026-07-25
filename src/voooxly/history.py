"""Persistent dictation history: ~/.voooxly/history.jsonl.

Each line = {"ts", "mode", "text"}. Dictations are sensitive text: the
file goes with 0600 permissions and `app.save_history: false` turns it off
entirely. Best-effort writes — a broken history must never get in the way
of dictation — and self-rotation: past MAX_ENTRIES*2 lines the last
MAX_ENTRIES are kept.
Searches ignore case and diacritics (see _fold): the stored text is
never altered, the folding is only for comparing.
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
        log.debug("Couldn't save dictation to history: %s", e)


def load(limit: int = 10, path: Path | None = None) -> list[str]:
    """Latest dictations, most recent first."""
    entries = _read(path or HISTORY_FILE)
    return [e["text"] for e in entries[-limit:]][::-1]


def _fold(s: str) -> str:
    """Lowercase without diacritics: 'Póker' → 'poker', 'Año' → 'ano'.

    You dictate with accents and later search typing fast, without them.
    Comparing raw made "poker" not find "póker". NFD splits the letter from
    its diacritic and the diacritic gets discarded. The ñ is folded too:
    it's the standard in a Spanish search box, and the goal is for searching
    to be easier, not more exact.
    """
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if not unicodedata.combining(c)).lower()


def search(query: str, limit: int = 10, path: Path | None = None) -> list[str]:
    """Dictations containing `query`, ignoring case and accents; recent first."""
    q = _fold((query or "").strip())
    if not q:
        return []
    # BOTH sides are folded so the search is symmetric: "poker"
    # finds "póker" and "póker" finds "poker". Folding only the query
    # would fix only half of the cases.
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
                continue  # corrupt line (crash mid-write): skipped
        return entries
    except FileNotFoundError:
        return []
    except Exception as e:
        log.debug("Couldn't read history: %s", e)
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
