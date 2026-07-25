"""Shortcut registry, its resolution and its conflicts.

A data module, no AppKit and no pynput, for the same reason as keys.py:
instantiating the Shortcuts window builds AppKit and can't be done in a
test. All the verifiable logic lives here; settings_window.py only
paints what this decides.

Resolution is the delicate part. config.yaml is the factory value and
prefs.json what the user chose, and neither of the two can leave the app
without shortcuts: both are hand-edited by people and a wrong type is a
typing mistake, not a laboratory case. Anything that fails validate_custom
falls back to the default silently, just like keys.resolve() did.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import keys

# Range of the window's slider. The default is NOT applied to everyone: it only
# appears when the chosen key needs the guard (see _delay_seguro). Setting
# 400 ms out of the box on the right ⌘ would add a 0.4 s wait to the start of
# dictation for every current user, who would lose the first syllables.
DEFAULT_DELAY_MS = 400
MAX_DELAY_MS = 800

DEFAULT_STYLE = "hold"


@dataclass(frozen=True)
class Shortcut:
    id: str                    # stable API, do not rename
    label: str                 # UI, in English
    subtitle: str              # UI, in English
    default: tuple[str, ...]   # pynput names
    has_delay: bool


# The order is the window's. The ids are stable API: they are written to
# prefs.json and renaming one silently erases the user's shortcut.
SHORTCUTS: dict[str, Shortcut] = {
    "dictation": Shortcut(
        "dictation", "Dictation", "Hold to talk", ("cmd_r",), True),
    "cycle_mode": Shortcut(
        "cycle_mode", "Cycle mode", "Switch to the next mode",
        ("ctrl", "shift", "m"), False),
    "latch": Shortcut(
        "latch", "Latch dictation", "Keep recording hands-free",
        ("shift",), False),
    "cancel": Shortcut(
        "cancel", "Cancel dictation", "Discard what you're saying",
        ("esc",), False),
}

# Where each shortcut's factory value in config.yaml comes from.
_RUTA_YAML = {
    "dictation": "hotkeys.toggle",
    "cycle_mode": "hotkeys.cycle_mode",
    "latch": "hotkeys.latch",
    "cancel": "hotkeys.cancel",
}


def _teclas_validas(valor) -> list[str] | None:
    """Is `valor` a usable list of key names? None if not."""
    if not isinstance(valor, list) or not valor:
        return None
    fuera = []
    for n in valor:
        if not isinstance(n, str):
            return None
        n = n.strip().lower()
        if not n:
            return None
        fuera.append(n)
    # Multi-key combos (like ctrl+shift+m) are returned without
    # validating: a sideless modifier such as 'ctrl' is illegal as a lone
    # dictation key (validate_custom rejects it) but perfectly legitimate
    # in a combo. Only individual keys need validation.
    if len(fuera) == 1:
        return fuera if keys.validate_custom(fuera[0])[0] else None
    return fuera


def _delay_seguro(valor, teclas: list[str]) -> int:
    """Delay in ms, clamped to the range and with a default that breaks nothing.

    If the value isn't usable, the fallback is NOT 0: with a key that needs
    the guard, 0 ms means every ⌘C starts a recording. It falls back to the
    default (400) when the guard is needed and to 0 when it isn't.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return DEFAULT_DELAY_MS if keys.needs_guard(teclas[0]) else 0
    if isinstance(valor, float) and not math.isfinite(valor):
        return DEFAULT_DELAY_MS if keys.needs_guard(teclas[0]) else 0
    return max(0, min(MAX_DELAY_MS, int(valor)))


def resolve(prefs: dict, cfg) -> dict[str, dict]:
    """Effective state of the four shortcuts: prefs on top of the YAML.

    Returns {sid: {"keys": [...]}}, plus "delay_ms" and "style" only in dictation
    (the only one with has_delay=True). The other three (cycle_mode, latch, cancel)
    carry only "keys".
    """
    guardado = prefs.get("shortcuts") if isinstance(prefs, dict) else None
    if not isinstance(guardado, dict):
        guardado = {}

    fuera: dict[str, dict] = {}
    for sid, sc in SHORTCUTS.items():
        teclas = list(sc.default)

        del_yaml = _teclas_validas(cfg.get(_RUTA_YAML[sid], None))
        if del_yaml is not None:
            teclas = del_yaml

        bloque = guardado.get(sid)
        if not isinstance(bloque, dict):
            bloque = {}
        de_prefs = _teclas_validas(bloque.get("keys"))
        if de_prefs is not None:
            teclas = de_prefs

        fila: dict = {"keys": teclas}
        if sc.has_delay:
            fila["delay_ms"] = _delay_seguro(bloque.get("delay_ms"), teclas)
            estilo = bloque.get("style")
            if not isinstance(estilo, str) or estilo not in keys.MODES:
                estilo = cfg.get("hotkeys.toggle_mode", DEFAULT_STYLE)
            if not isinstance(estilo, str) or estilo not in keys.MODES:
                estilo = DEFAULT_STYLE
            fila["style"] = estilo
        fuera[sid] = fila
    return fuera


# The delay v1.3.0 applied without asking to guarded keys. It is NOT
# DEFAULT_DELAY_MS: whoever updates keeps their usual feel and only sees 400
# if they change keys from the new window.
_DELAY_HEREDADO_MS = 300


def migrate(prefs: dict) -> bool:
    """Translates the v1.3.0 format into the `shortcuts` block. Mutates `prefs`.

    Only migrates `dictation`: the other three were never configurable, so
    resolve() already gives them the correct default with no help.

    The old keys are left written on purpose. If the user goes back to a
    previous version, they find them intact; and if they don't, they get
    cleaned up in two versions. Deleting them here would make the downgrade
    destructive.
    """
    if not isinstance(prefs, dict):
        return False
    if isinstance(prefs.get("shortcuts"), dict) and prefs["shortcuts"]:
        return False

    tecla = prefs.get("dictation_key")
    if not isinstance(tecla, str) or not keys.validate_custom(tecla)[0]:
        return False

    fila = {
        "keys": [tecla],
        "delay_ms": _DELAY_HEREDADO_MS if keys.needs_guard(tecla) else 0,
    }
    estilo = prefs.get("dictation_mode")
    fila["style"] = estilo if isinstance(estilo, str) and estilo in keys.MODES else DEFAULT_STYLE

    prefs["shortcuts"] = {"dictation": fila}
    return True


# pynput name → macOS symbol. What the user sees on a keyboard. It lived
# in settings_window.py, but the menu bar's "Shortcuts" submenu moved it up
# here (v1.6 feedback: shortcuts have to be visible without opening any
# window): the bar needs the same legends and this module is the only
# AppKit-free one that the window, the menu and the tests can share. It is
# still THE single table — a second copy at the drawing site is the bug
# settings_window has been avoiding since Task 9.
SIMBOLO = {
    "cmd": "⌘", "cmd_l": "⌘", "cmd_r": "⌘",
    "alt": "⌥", "alt_l": "⌥", "alt_r": "⌥", "alt_gr": "⌥",
    "ctrl": "⌃", "ctrl_l": "⌃", "ctrl_r": "⌃",
    "shift": "⇧", "shift_l": "⇧", "shift_r": "⇧",
    "space": "␣", "enter": "⏎", "tab": "⇥", "backspace": "⌫",
    "caps_lock": "⇪",
    # "arrows" is not a pynput key name (keys.validate_custom rejects
    # it): it is the synthetic name of the filler cell that represents
    # the arrow block of settings_window's visual keyboard
    # (Task 9, Defect 4 — an empty rectangle there read as a broken key).
    "arrows": "◀▼▶",
}


def key_label(names: list[str]) -> str:
    """['ctrl','shift','m'] → '⌃⇧M'. The legend of a binding in any UI.

    Used by settings_window's keycaps and chips, the menu bar's Shortcuts
    submenu and the guide: they all write the same key the same way because
    they all go through here.
    """
    fuera = []
    for n in names or []:
        low = n.lower()
        if low in SIMBOLO:
            fuera.append(SIMBOLO[low])
        elif low in ("esc", "fn"):
            fuera.append(low)
        else:
            fuera.append(low.upper())
    return "".join(fuera)


def menu_summary(state: dict[str, dict]) -> list[tuple[str, str]]:
    """[(sid, "Dictation:  ⌘  (right, hold)"), …] for the menu bar's submenu.

    One row per shortcut with its REAL binding (v1.6 feedback: shortcuts are
    the most important part of the app and were buried in a window). The side
    comes from side_hint — the same truth as the window — and dictation adds
    its style (hold/toggle), which a lone ⌘ doesn't tell.
    """
    fuera = []
    for sid, sc in SHORTCUTS.items():
        fila = state.get(sid) if isinstance(state, dict) else None
        if not isinstance(fila, dict):
            fila = {}
        names = list(fila.get("keys") or sc.default)
        matices = []
        lado = side_hint(sid, names)
        if lado:
            matices.append(lado)
        if sid == "dictation":
            estilo = fila.get("style", DEFAULT_STYLE)
            matices.append("hold" if estilo == "hold" else "toggle")
        texto = f"{sc.label}:  {key_label(names)}"
        if matices:
            texto += f"  ({', '.join(matices)})"
        fuera.append((sid, texto))
    return fuera


# Sideless pynput names: they are the LEFT (pynput collapses cmd_l/alt_l/
# ctrl_l/shift_l into the plain name, see keys._ALIAS_IZQUIERDA) — but in the
# latch shortcut they also widen to the right, because hotkey.py:421 matches
# by PREFIX (`name.startswith(self._latch_key + "_")`) and not by equality.
_MODIFICADORES_SIN_LADO = {"cmd", "alt", "ctrl", "shift"}

# pynput names that identify the right key with no possible ambiguity: there
# is no "<name>_r_something" the latch prefix could keep widening with, so
# these match a single side no matter the shortcut.
_MODIFICADORES_DERECHA = {"cmd_r", "alt_r", "ctrl_r", "shift_r"}


def matched_keys(sid: str, names: list[str]) -> set[str]:
    """Canonical names of the PHYSICAL keys that `hotkey.py` actually
    matches at runtime for shortcut `sid` with `names` as the current binding.

    It is the single fact both `side_hint()` (summarizes it in a word for
    the row) and settings_window.py's `lit_keys()` (lights up cells with it)
    derive from: before, each recomputed it its own way and they could fall
    out of sync — the real Task 9 bug, with "shift" lit on the keyboard and
    "shift_r" off while the row said "either side".

    Each name in `names` is translated separately with `keys.canon()`. A
    combo (len(names) != 1, like cycle_mode's ctrl+shift+m) widens
    nothing: hotkey.py:439 compares the set of pressed keys by exact
    EQUALITY with the combo (`_combo_names`), not by prefix, so each key
    in the combo matches only its own side.

    With a lone key (len(names) == 1), `latch` is the only one that
    widens: hotkey.py:421 matches by PREFIX
    (`name == self._latch_key or name.startswith(self._latch_key + "_")`).
    That prefix only lengthens the result when the configured key is one
    of the four SIDELESS modifiers (`_MODIFICADORES_SIN_LADO`): the
    only suffix pynput actually reports for those four names is
    "_r" (the left already arrives collapsed into the sideless name — see
    `keys._ALIAS_IZQUIERDA` — so there is never a "<name>_l" to match).
    A key that already has its own side (e.g. cmd_r) widens nothing: there
    is no "cmd_r_something" the prefix could keep lengthening with.
    The other three shortcuts (dictation, cancel, single-key cycle_mode)
    match by exact equality (hotkey.py:397 and :432), so they never widen
    no matter the name.
    """
    fuera: set[str] = set()
    for n in names:
        canon = keys.canon(n)
        if not canon:
            continue
        fuera.add(canon)
        if sid == "latch" and len(names) == 1 and canon in _MODIFICADORES_SIN_LADO:
            fuera.add(canon + "_r")
    return fuera


def side_hint(sid: str, names: list[str]) -> str:
    """'right' / 'left' / 'either side' / '' — which side(s) of the key
    REALLY match at runtime for shortcut `sid`, with `names` as the binding.

    Lives here and not in settings_window.py because it's a decision about
    shortcut semantics (what hotkey.py does with this name), not about
    painting. It derives from `matched_keys()`: it doesn't repeat its
    widening logic, it only translates the SET that function computes into
    the word read in the row. That way the two views -the row text and the
    lit cells of the keyboard- are necessarily the same truth.

    A combo (len(names) != 1) has no side: several keys at once and no
    combination of hands is "the" answer — cycle_mode with its factory
    ctrl+shift+m falls here.

    A lone key that is neither a sideless modifier nor one with its own
    side (a letter, "esc", an F key) has no side to announce: "".
    """
    if len(names) != 1:
        return ""
    nombre = keys.canon(names[0])
    if nombre not in _MODIFICADORES_SIN_LADO and nombre not in _MODIFICADORES_DERECHA:
        return ""
    if len(matched_keys(sid, names)) > 1:
        return "either side"
    return "right" if nombre in _MODIFICADORES_DERECHA else "left"


def _firma(names: list[str]) -> frozenset[str]:
    """Canonical set of a binding, to compare two shortcuts.

    Canonicalized on purpose: cmd_l and cmd are the same physical key on
    macOS and comparing them as raw strings would let the collision through.
    """
    return frozenset(keys.canon(n) for n in names)


def validate(sid: str, names: list[str], actuales: dict[str, dict]) -> tuple[bool, str]:
    """Can `names` be assigned to `sid`? Returns (ok, message).

    The message is in ENGLISH: it shows up as-is in the window row. When
    ok is True the message may carry a warning (F5) - it is informative, not a
    rejection, because choosing F5 is legitimate even if it's a bad idea.
    """
    if not names:
        return False, "Press the keys you want to use."

    mia = _firma(names)
    for otro_sid, fila in actuales.items():
        if otro_sid == sid or otro_sid not in SHORTCUTS:
            continue
        other_keys = fila.get("keys") or []
        if _firma(list(other_keys)) == mia:
            label = SHORTCUTS[otro_sid].label
            msg = "That shortcut is already used by “" + label + "”. Pick another one."
            return False, msg

    # Reassigning its own current key (e.g. confirming the row without
    # changing anything) is never a conflict, even if that key is in
    # keys._RESERVADAS: "esc" and "shift" are precisely the factory keys
    # of "cancel" and "latch", so without this cut they would fall into
    # validate_custom() and get rejected as if they belonged to others.
    propia = actuales.get(sid)
    if isinstance(propia, dict) and _firma(list(propia.get("keys") or [])) == mia:
        return True, ""

    if len(names) == 1:
        canon1 = keys.canon(names[0])
        if canon1 in ("cmd", "alt", "ctrl"):
            # Captured from the keyboard, the sideless name IS the left key
            # (pynput collapses cmd_l→cmd): validate_custom rejects it because
            # its audience is text TYPED into config.yaml, where "cmd" is an
            # ambiguous intent that must be returned to its author. Here there
            # is no ambiguity — the key was already pressed — and rejecting it
            # would leave the left ⌘, which DICTATION_KEYS offers with its
            # delay, with no possible path in the window.
            if sid == "dictation":
                return True, ("Left modifier: dictation starts after the "
                              "delay below, so combos like ⌘C keep working.")
            return True, ""
        ok, msg = keys.validate_custom(names[0])
        if not ok:
            return False, msg

    bajos = {n.lower() for n in names}
    if "f5" in bajos:
        msg = "Heads up: F5 is the macOS Dictation key, so macOS may react to it too."
        return True, msg
    if "fn" in bajos:
        # Wispr Flow's factory choice; macOS also listens to it
        # (emoji, language switching…), so it's advised without blocking.
        msg = ("Tip: set “Press 🌐 key to” to “Do Nothing” in System Settings → "
               "Keyboard so macOS doesn't react to it too.")
        return True, msg
    return True, ""
