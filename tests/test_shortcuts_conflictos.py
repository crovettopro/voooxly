"""Two shortcuts cannot share a key, or one of the two dies in silence.

The comparison runs on CANONICALIZED names. "cmd_l" and "cmd" are the same
physical key on macOS (pynput collapses the enum), so a matrix that
compared raw strings would let through exactly the collision that matters: the
user would see two distinct rows and one of the two would never fire.

Messages are in English because they show up in the window.
"""
from voooxly import shortcuts

ACTUALES = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def test_free_key_passes():
    ok, msg = shortcuts.validate("dictation", ["alt_r"], ACTUALES)
    assert ok, msg


def test_reassigning_own_key_passes():
    # Changing only the delay cannot collide with itself.
    ok, _ = shortcuts.validate("dictation", ["cmd_r"], ACTUALES)
    assert ok


def test_cancel_y_latch_pueden_reasignarse_su_propia_tecla_reservada():
    """cancel and latch default to "esc" and "shift", which are EXACTLY
    the keys that keys._RESERVADAS blocks for dictation. The self-assignment
    check has to compare against the shortcut's own key BEFORE falling
    through to validate_custom(), or confirming the row without changing
    anything would reject the shortcut's own factory key as if it were
    foreign and reserved for dictation.
    """
    ok, msg = shortcuts.validate("cancel", ["esc"], ACTUALES)
    assert ok, msg

    ok, msg = shortcuts.validate("latch", ["shift"], ACTUALES)
    assert ok, msg


def test_la_tecla_de_otro_atajo_choca_y_dice_de_quien():
    ok, msg = shortcuts.validate("dictation", ["esc"], ACTUALES)
    assert not ok
    assert "Cancel dictation" in msg


def test_collision_is_seen_through_side_alias():
    # latch is "shift"; assigning "shift_l" to dictation is the SAME physical key.
    # Without canonicalizing, this would pass and the latch would stop working.
    ok, msg = shortcuts.validate("dictation", ["shift_l"], ACTUALES)
    assert not ok
    assert "Latch dictation" in msg


def test_una_tecla_de_un_solo_caracter_se_rechaza():
    ok, msg = shortcuts.validate("dictation", ["a"], ACTUALES)
    assert not ok
    assert "a" in msg


def test_una_lista_vacia_se_rechaza():
    ok, msg = shortcuts.validate("dictation", [], ACTUALES)
    assert not ok
    assert msg


def test_un_combo_que_comparte_una_tecla_con_otro_combo_no_choca():
    # ⌃⇧M and ⌃⇧V share ⌃ and ⇧ but are distinct combos: no conflict.
    ok, _ = shortcuts.validate("cycle_mode", ["ctrl", "shift", "p"], ACTUALES)
    assert ok


def test_un_combo_identico_a_otro_si_choca():
    otros = dict(ACTUALES, cancel={"keys": ["ctrl", "shift", "p"]})
    ok, msg = shortcuts.validate("cycle_mode", ["ctrl", "shift", "p"], otros)
    assert not ok
    assert "Cancel dictation" in msg


def test_avisa_de_f5_sin_bloquear():
    # F5 is the macOS Dictation key: a documented bad choice, but it is
    # the user's decision. Warn, do not block.
    ok, msg = shortcuts.validate("dictation", ["f5"], ACTUALES)
    assert ok
    assert "F5" in msg or "f5" in msg


def test_captured_left_modifier_is_accepted_with_notice():
    # From capture, side-less "cmd" is the physical left key (pynput
    # collapses cmd_l→cmd). validate_custom rejects it because its audience is
    # typed text (config.yaml), but rejecting it here would leave the left
    # ⌘ —which DICTATION_KEYS offers with its delay— with no possible path
    # in the window: it showed up gray on the keyboard and capture failed.
    for n in ("cmd", "alt", "ctrl"):
        ok, msg = shortcuts.validate("dictation", [n], ACTUALES)
        assert ok, n
        assert "delay" in msg.lower(), "el aviso explica el arranque con retardo"


def test_choosing_fn_advises_turning_off_globe_key_without_blocking():
    # macOS also reacts to fn/🌐 (emoji, language switching…) depending on
    # what is set in System Settings. Choosing it is legitimate — Wispr ships
    # with it by default —, so we advise turning off the system action, we
    # do not block.
    ok, msg = shortcuts.validate("dictation", ["fn"], ACTUALES)
    assert ok
    assert "🌐" in msg or "fn" in msg.lower()
