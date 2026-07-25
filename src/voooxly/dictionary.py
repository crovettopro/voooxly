"""Diccionario personal: nombres, marcas y jerga que Whisper escribe mal.

Dos mecanismos que se complementan:
- **words** → van al initial prompt del whisper-server y SESGAN la
  transcripción hacia esas grafías ("Voooxly" en vez de "Boxli").
- **replacements** → corrección determinista sobre el texto FINAL (palabra
  completa, sin distinguir mayúsculas) para lo que Whisper sigue fallando
  aunque esté en el prompt.

Vive en ~/.voooxly/dictionary.json (editable a mano) y se añade desde el
menú: "wisperflow -> Wispr Flow" crea un reemplazo; "Ucademy" a secas, una
palabra de sesgo. Best-effort siempre: un diccionario roto no estorba.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from pathlib import Path

log = logging.getLogger("voooxly.dictionary")

DICT_FILE = Path.home() / ".voooxly" / "dictionary.json"

# add() is a read-modify-write of the WHOLE file, and auto-learn fires it from
# daemon threads (one per pending dictation) while the dictation path reads it.
# Without this lock the last writer wins and the other's entries vanish.
_LOCK = threading.Lock()


def load(path: Path | None = None) -> dict:
    path = path or DICT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        words = [str(w).strip() for w in data.get("words", []) if str(w).strip()]
        repl = {
            str(k).strip(): str(v).strip()
            for k, v in (data.get("replacements", {}) or {}).items()
            if str(k).strip() and str(v).strip()
        }
        return {"words": words, "replacements": repl}
    except FileNotFoundError:
        return {"words": [], "replacements": {}}
    except Exception as e:
        log.warning("dictionary.json ilegible (%s): se ignora", e)
        return {"words": [], "replacements": {}}


def _write_atomic(path: Path, data: dict) -> None:
    """Writes through a temp file + os.replace, never in place.

    Writing in place truncates first: a concurrent reader — or a quit landing
    between the truncate and the write — sees an empty file, and load()
    swallows that as an EMPTY dictionary. The user would silently lose every
    learned replacement and every bias word.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dictionary-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)  # atomic on the same filesystem
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(entry: str, path: Path | None = None) -> str:
    """Adds what was typed in the menu. "wrong -> right" = replacement; else, word.

    Returns a human-readable description of what was added (for the notification).
    The read-modify-write is serialized: auto-learn calls this from daemon
    threads that can overlap.
    """
    path = path or DICT_FILE
    with _LOCK:
        data = load(path)
        if "->" in entry:
            wrong, _, right = entry.partition("->")
            wrong, right = wrong.strip(), right.strip()
            if not wrong or not right:
                raise ValueError("Use: wrong spelling -> right spelling")
            data["replacements"][wrong] = right
            desc = f"Replacement: “{wrong}” → “{right}”"
            # the correct spelling also biases the transcription
            if right not in data["words"]:
                data["words"].append(right)
        else:
            word = entry.strip()
            if not word:
                raise ValueError("Empty entry")
            if word not in data["words"]:
                data["words"].append(word)
            desc = f"Word: “{word}”"
        _write_atomic(path, data)
    return desc


def stt_terms(path: Path | None = None) -> list[str]:
    """Terms for the Whisper initial prompt (words + correct spellings)."""
    data = load(path)
    seen: list[str] = []
    for t in data["words"] + list(data["replacements"].values()):
        if t not in seen:
            seen.append(t)
    return seen


def apply(text: str, path: Path | None = None) -> str:
    """Aplica los reemplazos al texto final: palabra completa, sin distinguir
    mayúsculas. Si la palabra "mala" empieza por mayúscula en el texto y el
    reemplazo va en minúscula, se respeta la capitalización del reemplazo tal
    cual está definido (el usuario escribió la grafía que quiere ver).
    """
    if not text:
        return text
    repl = load(path)["replacements"]
    for wrong, right in repl.items():
        try:
            text = re.sub(
                rf"(?<!\w){re.escape(wrong)}(?!\w)", right, text, flags=re.IGNORECASE
            )
        except re.error:
            continue
    return text
