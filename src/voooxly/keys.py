"""Catalog of dictation keys and their validation.

A data module, no AppKit, for the same reason ai_settings.py exists:
instantiating VoooxlyApp builds menus and can't be done in a test. All the
verifiable logic lives here; app.py only wires the menu.

Validation is the important part. Choosing the dictation key badly is not a
configuration detail: it cripples the keyboard. With "a" as the dictation
key you can no longer type the letter a anywhere in the system, and fixing it
requires editing prefs.json by hand — something the user who needs this menu
doesn't know how to do.

GUARD (guard=True): the LEFT modifiers are used constantly in
combos (⌘C, ⌘V, ⌘S, ⌘Tab). hotkey.py fires on_start() (hold mode) or
on_toggle() (toggle mode) on key-down, so without the guard every ⌘C
would start or toggle a recording IN EITHER of the two modes —
needs_guard() doesn't distinguish by dictation_mode because the key needs it
no matter what's in Settings → Dictation style. With the guard, the trigger
only happens if you hold the key ALONE ~300ms (in toggle mode that changes
the gesture from a tap to a brief hold). The right ones don't carry it:
almost nobody makes combos with them, the current path is already in
production and giving it to them would cost everyone 300ms of latency to fix
a problem only the left ones have.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_KEY = "cmd_r"
DEFAULT_MODE = "hold"

# Dictation button mode. The text is what's shown in the menu.
MODES: dict[str, str] = {
    "hold": "Hold to talk",
    "toggle": "Press to start / stop",
}

# Modifier prefixes: they're used in combos, so they need the guard.
_MODIFICADORES = ("cmd", "alt", "ctrl")

# The sided modifiers pynput actually knows. They're listed in full instead
# of deducing them with an "_l"/"_r" suffix because alt_gr doesn't comply and
# the deduction generated absurd error messages ("prueba alt__r").
_MODIFICADORES_CON_LADO = {
    "cmd_l", "cmd_r", "alt_l", "alt_r", "alt_gr", "ctrl_l", "ctrl_r",
}

# Keys with an owner: can't be reassigned to dictation without crippling the app.
_RESERVADAS = {"esc", "shift", "shift_l", "shift_r"}

# alt_gr isn't in the catalog but pynput collapses it into the same enum
# member as alt_r: on macOS there's no physical AltGr key distinct from the
# right Option, so both share a virtual keycode and `Key.alt_gr is
# Key.alt_r` (verified against the project's pynput). needs_guard() has
# to know it: without this alias it would treat alt_gr as "just another
# modifier" and give it the guard, inconsistent with the catalog already
# treating the right ones — which is what alt_gr really IS — without a guard.
_ALIAS_MISMA_TECLA = {"alt_gr": "alt_r"}

# pynput GOTCHA: on macOS, Key.cmd_l is NOT its own enum member but an
# ALIAS of Key.cmd — the darwin backend gives them the same virtual keycode
# (0x37) and enum.Enum collapses equal values into a single member. So
# `Key.cmd_l is Key.cmd` and its .name is "cmd": the listener never reports
# "cmd_l". The generic name pynput reports IS the left key's, and the
# catalog name has to be translated to the one arriving from the keyboard or
# the key would never match. Lives here and not in hotkey.py because it is
# dictionary arithmetic —doesn't touch pynput— and shortcuts.py needs it to
# see conflicts without dragging pynput into a data module.
_ALIAS_IZQUIERDA = {
    "cmd_l": "cmd",
    "alt_l": "alt",
    "ctrl_l": "ctrl",
    "shift_l": "shift",
}


def canon(name: str | None) -> str | None:
    """Configured key name → the name pynput actually reports."""
    if not name:
        return name
    low = name.lower()
    if low in _ALIAS_IZQUIERDA:
        return _ALIAS_IZQUIERDA[low]
    return _ALIAS_MISMA_TECLA.get(low, low)

# pynput names we accept outside the catalog. There is no "Custom…" menu
# entry anymore (we removed it: see DICTATION_KEYS), but validate_custom
# remains the gate for prefs.json and for config.yaml > hotkeys.toggle, which
# is how anyone wanting an F key gets in today.
# Function keys go up to f20 in pynput.
_FUNCIONES = {f"f{i}" for i in range(1, 21)}

# "fn" is not a pynput name: its flagsChanged (vk 63) is straightened out by
# hotkey.py by hand (pynput always delivers it as a release). It's accepted
# here because it's Wispr Flow's star dictation key and carries no guard:
# nobody does ⌘C combos with fn, so _es_modificador() already gives it False
# with no help.
_ESPECIALES = {"fn"}


@dataclass(frozen=True)
class DictationKey:
    name: str    # pynput name
    label: str   # menu label
    guard: bool  # needs a decision window?


# The order is the menu's (insertion order): the right ones first because
# they're the recommended ones and the left ones after, with the delay written
# into the label itself.
#
# Only the six modifiers of the bottom row. The F keys were here and got
# removed: F13-F15 don't exist on any laptop keyboard, so whoever opened the
# menu on a MacBook had four out of ten rows they couldn't press — and a list
# where almost half doesn't work casts doubt on the rest.
# They're still accepted via config.yaml > hotkeys.toggle (see _FUNCIONES) for
# whoever has a keyboard that carries them and knows how to edit the YAML.
DICTATION_KEYS: dict[str, DictationKey] = {
    "cmd_r": DictationKey("cmd_r", "Right ⌘ (Command)", False),
    "alt_r": DictationKey("alt_r", "Right ⌥ (Option)", False),
    "ctrl_r": DictationKey("ctrl_r", "Right ⌃ (Control)", False),
    "cmd_l": DictationKey("cmd_l", "Left ⌘ (Command) — 300 ms delay", True),
    "alt_l": DictationKey("alt_l", "Left ⌥ (Option) — 300 ms delay", True),
    "ctrl_l": DictationKey("ctrl_l", "Left ⌃ (Control) — 300 ms delay", True),
}


def get(name: str) -> DictationKey | None:
    return DICTATION_KEYS.get(name)


def needs_guard(name: str) -> bool:
    """Does this key need a decision window before starting to record?

    The catalog ones carry it written down. A custom one needs it if it's a
    modifier (used in combos); a function or media key doesn't.
    """
    k = get(_ALIAS_MISMA_TECLA.get(name, name))
    if k is not None:
        return k.guard
    return _es_modificador(name)


def _es_modificador(name: str) -> bool:
    return any(name.startswith(p) for p in _MODIFICADORES)


def validate_custom(name: str) -> tuple[bool, str]:
    """Does `name` work as a dictation key? Returns (ok, message).

    The error message says what's wrong AND how to fix it: whoever gets here
    is precisely the user who doesn't know what a "pynput key name" is.
    Accepts any type, not just str: this function ends up wired to the
    menu's input, and a non-string value there isn't a laboratory case
    but the first thing an unvalidated text field can deliver.
    """
    if not isinstance(name, str):
        return False, "A key name must be text, not a number or other value."
    name = name.strip().lower()
    if not name:
        return False, "Type a key name, for example f13 or alt_r."
    if name in DICTATION_KEYS:
        return True, ""
    if len(name) == 1:
        return False, (
            f'"{name}" is a single character — using it for dictation would stop '
            f'you typing "{name}" anywhere on your Mac. Try f13 or alt_r.'
        )
    if name in _RESERVADAS:
        dueno = "cancel a dictation" if name.startswith("esc") else "latch a long dictation"
        return False, f'"{name}" is already used to {dueno}. Pick another key.'
    if name in _MODIFICADORES:
        # CAREFUL: don't say a plain "{name}" would match both hands — on
        # macOS it only matches the left one (pynput collapses Key.cmd_l into
        # Key.cmd; see hotkey._canon). That message was false, and on top of
        # that the "fix" it used to suggest ({name}_l) canonicalizes back to
        # the same plain "{name}". A side is asked for without asserting
        # which one matches today.
        return False, (
            f'"{name}" needs a side — use {name}_l for the left key '
            f"or {name}_r for the right key."
        )
    if name in _MODIFICADORES_CON_LADO or name in _FUNCIONES or name in _ESPECIALES:
        return True, ""
    return False, (
        f'"{name}" isn\'t a key pynput knows, so it would never fire. '
        f"Try f13, f18 or alt_r."
    )


def resolve(prefs: dict, cfg) -> tuple[str, str, bool]:
    """Effective (key, mode, guard): the user's prefs on top of the YAML.

    Same pattern as `sounds` in app.py — config.yaml is the factory value and
    what the user chose wins. Neither corrupt prefs (a list, a
    number, a key removed in a later version) nor a corrupt YAML
    (a bare string where a list should go, a type that can't even be
    indexed) can leave the app without a hotkey: ~/.voooxly/config.yaml is
    handwritten by whoever has it and "toggle: cmd_r" instead of
    "toggle: [cmd_r]" is a typing mistake, not an exotic case. Both
    sources go through the same gate — validate_custom — and both fall to
    DEFAULT_KEY if they fail it.
    """
    tecla = DEFAULT_KEY
    del_yaml = cfg.get("hotkeys.toggle", [DEFAULT_KEY]) or [DEFAULT_KEY]
    if isinstance(del_yaml, list) and del_yaml:
        candidata_yaml = del_yaml[0]
        if isinstance(candidata_yaml, str) and validate_custom(candidata_yaml)[0]:
            tecla = candidata_yaml

    guardada = prefs.get("dictation_key")
    if isinstance(guardada, str) and validate_custom(guardada)[0]:
        tecla = guardada

    modo = cfg.get("hotkeys.toggle_mode", DEFAULT_MODE)
    modo_guardado = prefs.get("dictation_mode")
    if isinstance(modo_guardado, str) and modo_guardado in MODES:
        modo = modo_guardado
    if modo not in MODES:
        modo = DEFAULT_MODE

    return tecla, modo, needs_guard(tecla)
