"""Upgrading from v1.3.0 cannot change anyone's behavior.

The old format was two loose keys (dictation_key, dictation_mode) and a
delay that was not chosen: 300 ms if the key needed a guard, 0 if not. The
migration has to reproduce EXACTLY that. Bumping someone who had 300 up to
the new default of 400 would change the app's feel behind their back.
"""
from voooxly import shortcuts


def test_migra_la_tecla_y_el_estilo_viejos():
    prefs = {"dictation_key": "alt_r", "dictation_mode": "toggle"}
    assert shortcuts.migrate(prefs) is True
    assert prefs["shortcuts"]["dictation"]["keys"] == ["alt_r"]
    assert prefs["shortcuts"]["dictation"]["style"] == "toggle"


def test_quien_tenia_guarda_conserva_300_no_400():
    prefs = {"dictation_key": "cmd_l"}
    shortcuts.migrate(prefs)
    assert prefs["shortcuts"]["dictation"]["delay_ms"] == 300


def test_quien_no_tenia_guarda_conserva_0():
    prefs = {"dictation_key": "cmd_r"}
    shortcuts.migrate(prefs)
    assert prefs["shortcuts"]["dictation"]["delay_ms"] == 0


def test_no_pisa_un_bloque_shortcuts_que_ya_existe():
    # If the user already used the window, their choices win over the old
    # keys, which stay written for two versions in case they roll back.
    prefs = {
        "dictation_key": "cmd_l",
        "shortcuts": {"dictation": {"keys": ["f13"], "delay_ms": 0}},
    }
    assert shortcuts.migrate(prefs) is False
    assert prefs["shortcuts"]["dictation"]["keys"] == ["f13"]


def test_does_not_delete_old_keys():
    prefs = {"dictation_key": "alt_r", "dictation_mode": "hold"}
    shortcuts.migrate(prefs)
    assert prefs["dictation_key"] == "alt_r"


def test_without_old_keys_does_nothing():
    prefs = {"sounds": True}
    assert shortcuts.migrate(prefs) is False
    assert "shortcuts" not in prefs


def test_una_tecla_vieja_invalida_no_migra_basura():
    prefs = {"dictation_key": "a"}
    shortcuts.migrate(prefs)
    assert "shortcuts" not in prefs
