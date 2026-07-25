"""Learning from the user: what they corrected on a dictation and what earns the dictionary.

Pure module (no AppKit) for the same reason as shortcuts.py: the delicate
logic is tested in pytest; app.py only glues on the window.

The bias is deliberate: PRECISION over exhaustiveness. One replacement
learned in excess corrupts every future dictation (dictionary.apply is
global and case-insensitive); one learned short only costs repeating the
correction by hand. That's why we only learn from short substitutions
(1 wrong word → 1-2 right) and never from deletions, insertions or rewrites.
"""
from __future__ import annotations

import difflib
import re

# Max words on each side of a substitution to consider it a "corrected
# spelling" and not a "rewritten phrase". 1→2 covers "wisperflow" → "Wispr Flow".
_MAX_WRONG = 1
_MAX_RIGHT = 2


def _words(text: str) -> list[str]:
    return [w for w in (text or "").split() if w]


def _strip_punct(w: str) -> str:
    return re.sub(r"^\W+|\W+$", "", w, flags=re.UNICODE)


# --- Automatic path: extra guards on top of corrections() ------------------
# An ASR error SOUNDS like what the user meant to say; a style edit does
# not. Cheap es-aware phonetic normalization (no dependencies) +
# similarity ratio: enough to separate "wisperflow"→"Wispr Flow"
# (learns) from "envía"→"manda" (silence).
_PHONETIC_SUBS = (
    ("ph", "f"), ("qu", "k"), ("ch", "x"), ("ll", "y"), ("h", ""),
    ("v", "b"), ("z", "s"), ("ge", "je"), ("gi", "ji"), ("ce", "se"),
    ("ci", "si"), ("w", "u"), ("y", "i"), ("c", "k"),
)
_SOUNDS_ALIKE_MIN = 0.6


def normalize_phonetic(s: str) -> str:
    """Collapses spellings that sound the same in Spanish (v/b, silent h, ll/y, qu/k…)."""
    import unicodedata

    t = unicodedata.normalize("NFD", (s or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z]+", "", t)
    for a, b in _PHONETIC_SUBS:
        t = t.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", t)


def sounds_alike(wrong: str, right: str) -> bool:
    a, b = normalize_phonetic(wrong), normalize_phonetic(right)
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= _SOUNDS_ALIKE_MIN


def _is_common(word: str) -> bool:
    from .langlock import COMMON_EN, COMMON_ES

    w = (word or "").lower().strip()
    return w in COMMON_ES or w in COMMON_EN


def corrections(original: str, corrected: str) -> list[tuple[str, str]]:
    """(wrong, right) pairs the user corrected, suitable as replacements.

    Only short 'replace' opcodes from the SequenceMatcher over words; the
    punctuation edges are trimmed so that "hola," vs "hola" doesn't count.
    """
    a, b = _words(original), _words(corrected)
    if not a or not b:
        return []
    fuera: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag != "replace":
            continue
        if (i2 - i1) > _MAX_WRONG or (j2 - j1) > _MAX_RIGHT:
            continue
        wrong = _strip_punct(" ".join(a[i1:i2]))
        right = _strip_punct(" ".join(b[j1:j2]))
        if not wrong or not right:
            continue
        # Punctuation-only change: after trimming the edges they're equal.
        if wrong == right:
            continue
        fuera.append((wrong, right))
    return fuera


# Threshold for "the paste is still there": below it, the user switched
# fields, deleted it or rewrote it — and in any of those cases there's
# nothing to learn safely. Accepted limitation: a 1-word paste corrected
# in full can't be located (matched=0) — it fails silently, on purpose.
_LOCATE_MIN_RATIO = 0.6


def locate_pasted(pasted: str, field_text: str) -> str | None:
    """Region of the field corresponding to the paste (perhaps already corrected)."""
    pw, fw = _words(pasted), _words(field_text)
    if not pw or not fw:
        return None
    sm = difflib.SequenceMatcher(None, fw, pw)
    blocks = [b for b in sm.get_matching_blocks() if b.size]
    if not blocks:
        return None
    if sum(b.size for b in blocks) / len(pw) < _LOCATE_MIN_RATIO:
        return None
    first, last = blocks[0], blocks[-1]
    start = max(0, first.a - first.b)
    end = min(len(fw), last.a + last.size + (len(pw) - (last.b + last.size)))
    return " ".join(fw[start:end])


def auto_corrections(pasted: str, field_text: str) -> list[tuple[str, str]]:
    """(wrong, right) pairs from the automatic path: corrections() + phonetics + frequency."""
    region = locate_pasted(pasted, field_text)
    if region is None:
        return []
    fuera: list[tuple[str, str]] = []
    for wrong, right in corrections(pasted, region):
        if not sounds_alike(wrong, right):
            continue  # style edit, not a hearing error
        if _is_common(wrong) or all(_is_common(w) for w in right.split()):
            continue  # a common word as a global replacement is a bomb
        fuera.append((wrong, right))
    return fuera


def _persist(pairs: list[tuple[str, str]], path=None) -> list[str]:
    """Saves pairs into the dictionary; an entry that fails is skipped."""
    from . import dictionary

    descs: list[str] = []
    for wrong, right in pairs:
        try:
            descs.append(dictionary.add(f"{wrong} -> {right}", path=path))
        except Exception:
            continue
    return descs


def learn_from(original: str, corrected: str, path=None) -> list[str]:
    """Learns the corrections and returns descriptions for the HUD.

    Best-effort like everything surrounding dictation: an entry that can't
    be saved is skipped, an exception is never propagated to the menu.
    """
    return _persist(corrections(original, corrected), path=path)


def auto_learn_from(pasted: str, field_text: str, path=None) -> list[str]:
    """Learns from corrections made in place. Best-effort, never raises."""
    try:
        return _persist(auto_corrections(pasted, field_text), path=path)
    except Exception:
        return []
