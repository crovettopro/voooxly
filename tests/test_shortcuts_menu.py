"""The menu bar Shortcuts submenu: key_label and menu_summary (v1.6 feedback).

Pure shortcuts.py: no AppKit, like the rest of the shortcut logic. The symbol
table used to live in settings_window.py and moved up here so the window, the
menu and the guide spell each key in one single way.
"""
from voooxly import shortcuts


# --- key_label: the single legend of a binding ---

def test_key_label_translates_combos_to_symbols():
    assert shortcuts.key_label(["ctrl", "shift", "m"]) == "⌃⇧M"
    assert shortcuts.key_label(["cmd_r"]) == "⌘"
    assert shortcuts.key_label(["shift"]) == "⇧"


def test_key_label_keeps_esc_and_fn_lowercase():
    # esc and fn read as words, not letters: "ESC" would look like another key.
    assert shortcuts.key_label(["esc"]) == "esc"
    assert shortcuts.key_label(["fn"]) == "fn"


def test_key_label_uppercases_letters():
    assert shortcuts.key_label(["a"]) == "A"
    assert shortcuts.key_label([]) == ""
    assert shortcuts.key_label(None) == ""


def test_settings_window_still_uses_same_table():
    """The settings_window alias points to THIS function: if someone copies
    the table back there, chips and menu could spell the same key in two
    ways — the bug that Task 9 caught once."""
    from voooxly import settings_window

    assert settings_window.key_label is shortcuts.key_label


# --- menu_summary: one row per shortcut with its real binding ---

def _estado_de_fabrica():
    return {
        "dictation": {"keys": ["cmd_r"], "delay_ms": 0, "style": "hold"},
        "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
        "latch": {"keys": ["shift"]},
        "cancel": {"keys": ["esc"]},
    }


def test_menu_summary_one_row_per_shortcut_in_order():
    filas = shortcuts.menu_summary(_estado_de_fabrica())
    assert [sid for sid, _ in filas] == list(shortcuts.SHORTCUTS)


def test_menu_summary_paints_factory_binding():
    filas = dict(shortcuts.menu_summary(_estado_de_fabrica()))
    assert "⌘" in filas["dictation"]
    assert "right" in filas["dictation"]      # the side, the same truth as the window
    assert "hold" in filas["dictation"]       # the style, which a lone ⌘ does not convey
    assert "⌃⇧M" in filas["cycle_mode"]
    assert "either side" in filas["latch"]    # latch widens shift to both sides
    assert "esc" in filas["cancel"]


def test_menu_summary_reflects_custom_shortcut():
    estado = _estado_de_fabrica()
    estado["dictation"] = {"keys": ["fn"], "delay_ms": 0, "style": "toggle"}
    filas = dict(shortcuts.menu_summary(estado))
    assert "fn" in filas["dictation"]
    assert "⌘" not in filas["dictation"]
    assert "toggle" in filas["dictation"]


def test_menu_summary_falls_back_to_factory_with_broken_state():
    """prefs.json gets hand-edited by people: a half-formed state cannot leave
    the submenu empty nor raise — same contract as resolve()."""
    filas = dict(shortcuts.menu_summary({}))
    assert "⌘" in filas["dictation"]
    filas = dict(shortcuts.menu_summary({"dictation": "basura"}))
    assert "⌘" in filas["dictation"]
