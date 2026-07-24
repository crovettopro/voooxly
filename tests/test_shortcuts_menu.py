"""El submenú Shortcuts de la barra: key_label y menu_summary (feedback v1.6).

Puro shortcuts.py: sin AppKit, como el resto de la lógica de atajos. La tabla
de símbolos vivía en settings_window.py y subió aquí para que la ventana, el
menú y la guía escriban cada tecla de una única forma.
"""
from voooxly import shortcuts


# --- key_label: la leyenda única de un binding ---

def test_key_label_traduce_combos_a_simbolos():
    assert shortcuts.key_label(["ctrl", "shift", "m"]) == "⌃⇧M"
    assert shortcuts.key_label(["cmd_r"]) == "⌘"
    assert shortcuts.key_label(["shift"]) == "⇧"


def test_key_label_deja_esc_y_fn_en_minuscula():
    # esc y fn se leen como palabra, no como letra: "ESC" parecería otra tecla.
    assert shortcuts.key_label(["esc"]) == "esc"
    assert shortcuts.key_label(["fn"]) == "fn"


def test_key_label_sube_letras_a_mayuscula():
    assert shortcuts.key_label(["a"]) == "A"
    assert shortcuts.key_label([]) == ""
    assert shortcuts.key_label(None) == ""


def test_settings_window_sigue_usando_la_misma_tabla():
    """El alias de settings_window apunta a ESTA función: si alguien vuelve a
    copiar la tabla allí, chips y menú podrían escribir la misma tecla de dos
    formas — el bug que la Task 9 cazó una vez."""
    from voooxly import settings_window

    assert settings_window.key_label is shortcuts.key_label


# --- menu_summary: una fila por atajo con su binding real ---

def _estado_de_fabrica():
    return {
        "dictation": {"keys": ["cmd_r"], "delay_ms": 0, "style": "hold"},
        "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
        "latch": {"keys": ["shift"]},
        "cancel": {"keys": ["esc"]},
    }


def test_menu_summary_una_fila_por_atajo_en_orden():
    filas = shortcuts.menu_summary(_estado_de_fabrica())
    assert [sid for sid, _ in filas] == list(shortcuts.SHORTCUTS)


def test_menu_summary_pinta_el_binding_de_fabrica():
    filas = dict(shortcuts.menu_summary(_estado_de_fabrica()))
    assert "⌘" in filas["dictation"]
    assert "right" in filas["dictation"]      # el lado, la misma verdad que la ventana
    assert "hold" in filas["dictation"]       # el estilo, que un ⌘ solo no cuenta
    assert "⌃⇧M" in filas["cycle_mode"]
    assert "either side" in filas["latch"]    # latch ensancha shift a ambos lados
    assert "esc" in filas["cancel"]


def test_menu_summary_refleja_un_atajo_personalizado():
    estado = _estado_de_fabrica()
    estado["dictation"] = {"keys": ["fn"], "delay_ms": 0, "style": "toggle"}
    filas = dict(shortcuts.menu_summary(estado))
    assert "fn" in filas["dictation"]
    assert "⌘" not in filas["dictation"]
    assert "toggle" in filas["dictation"]


def test_menu_summary_cae_a_fabrica_con_estado_roto():
    """prefs.json lo edita gente a mano: un estado a medias no puede dejar el
    submenú vacío ni lanzar — mismo contrato que resolve()."""
    filas = dict(shortcuts.menu_summary({}))
    assert "⌘" in filas["dictation"]
    filas = dict(shortcuts.menu_summary({"dictation": "basura"}))
    assert "⌘" in filas["dictation"]
