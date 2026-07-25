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
import time

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


# --- Post-paste window ----------------------------------------------------
# Reading once, when the next dictation starts, loses every correction made in
# a field the user then leaves (they send the Slack message, close the tab,
# switch app). Watching the field for a few seconds right after the paste
# catches it — at the price of seeing the text WHILE it is being typed, which
# the single read never did. Hence the rule below: a state is only learnable
# once it has been read identical twice in a row. A half-typed correction
# ("Wispr Flo") is a perfect phonetic match and would be persisted as a global
# replacement that can never be undone, because dictionary.apply() rewrites
# the dictation before it is pasted and the misspelling never comes back.
_MIN_POLL_S = 0.5      # floor: poll_interval: 0 in config must not busy-loop
_MISS_TOLERANCE = 1    # one blind poll is a focus blink, not a departure


def _seconds(value, fallback: float) -> float:
    """Config values are user-editable YAML: coerce, never trust, never raise."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return fallback
    return out if out >= 0 else fallback


def watch_field(
    pasted: str,
    read,
    *,
    window_s: float = 15.0,
    poll_s: float = 2.0,
    stable_s: float = 3.0,
    acquire_s: float = 4.0,
    stop=None,
    trace=None,
    clock=time.monotonic,
    sleep=time.sleep,
) -> str | None:
    """Watches the field just pasted into; returns the text to learn from, or None.

    `read` is injected (axfield in production, a script in the tests) and so
    are `clock`/`sleep`, which is what keeps this module pure and the tests
    instant. Best-effort like the rest of the module: a read that blows up
    counts as an unreadable field, never as an exception.

    Three ways out, and only one of them is generous:
      - the region settled while still in front of us → learn from it;
      - the field went away → learn from the last state confirmed quiet;
      - the window expired → same.
    Never from the last raw read: that is the one that can be half-typed.

    Known limitation, unchanged from the single-read path: matching is by text,
    so a *different* field holding nearly the same words is indistinguishable
    from the one we pasted into. The caller narrows this by refusing to read
    once focus leaves the app that received the paste (axfield.app_locked_reader).
    """
    window_s = _seconds(window_s, 15.0)
    poll_s = max(_seconds(poll_s, 2.0), _MIN_POLL_S)
    stable_s = _seconds(stable_s, 3.0)
    acquire_s = min(_seconds(acquire_s, 4.0), window_s)
    deadline = clock() + window_s
    acquire_deadline = clock() + acquire_s
    polls_left = int(window_s / poll_s) + 2  # hard cap: a frozen clock can't spin
    last_good = last_region = last_stable = None
    last_change = clock()
    misses = 0
    while polls_left > 0 and clock() < deadline:
        if stop is not None and stop.is_set():
            return last_stable  # a newer paste took over: hand in what we confirmed
        polls_left -= 1
        try:
            field = read() or ""
        except Exception:
            field = ""
        region = locate_pasted(pasted, field) if field else None
        if trace is not None:
            # Counts only, never the text: enough to tell "the app exposes
            # nothing" from "it does and we failed to find our paste in it",
            # which are opposite problems with opposite fixes.
            trace.append((len(field), region is not None))
        if region is None:
            if last_good is None:
                # The ⌘V is posted asynchronously: at t=0 the text is usually
                # not in the field yet. "Not there YET" is not "gone".
                if clock() >= acquire_deadline:
                    return None  # unreadable for real (a terminal), or pasted elsewhere
            else:
                misses += 1
                if misses > _MISS_TOLERANCE:
                    return last_stable
            sleep(poll_s)
            continue
        misses = 0
        if last_region is None or region != last_region:
            last_change = clock()  # still correcting
        else:
            last_stable = field  # read identical twice: confirmed quiet
        last_good, last_region = field, region
        if last_stable is not None and (clock() - last_change) >= stable_s:
            return field
        sleep(poll_s)
    return last_stable


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
