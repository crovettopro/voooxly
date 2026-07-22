"""Actualizar desde v1.3.0 no puede cambiarle el comportamiento a nadie.

El formato viejo eran dos claves sueltas (dictation_key, dictation_mode) y un
delay que no se elegía: 300 ms si la tecla necesitaba guarda, 0 si no. La
migración tiene que reproducir EXACTAMENTE eso. Subir a quien tenía 300 hasta
el nuevo default de 400 sería cambiarle el tacto de la app por la cara.
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
    # Si el usuario ya usó la ventana, sus elecciones mandan sobre las claves
    # viejas, que se quedan escritas dos versiones por si vuelve atrás.
    prefs = {
        "dictation_key": "cmd_l",
        "shortcuts": {"dictation": {"keys": ["f13"], "delay_ms": 0}},
    }
    assert shortcuts.migrate(prefs) is False
    assert prefs["shortcuts"]["dictation"]["keys"] == ["f13"]


def test_no_borra_las_claves_viejas():
    prefs = {"dictation_key": "alt_r", "dictation_mode": "hold"}
    shortcuts.migrate(prefs)
    assert prefs["dictation_key"] == "alt_r"


def test_sin_claves_viejas_no_hace_nada():
    prefs = {"sounds": True}
    assert shortcuts.migrate(prefs) is False
    assert "shortcuts" not in prefs


def test_una_tecla_vieja_invalida_no_migra_basura():
    prefs = {"dictation_key": "a"}
    shortcuts.migrate(prefs)
    assert "shortcuts" not in prefs
