"""La ventana de Shortcuts: que construya y que las etiquetas sean legibles.

Los tests instancian el controlador de AppKit de verdad, como los de
onboarding: eso valida que la ventana se construye sin reventar, que es el
fallo más caro y el más fácil de meter.

Lo que NO se puede validar aquí es que la ventana se VEA. En macOS 26 un
NSPanel devuelve isVisible=True y no pinta un solo píxel; por eso la ventana
es un NSWindow y por eso la verificación de que compone es manual, con
screencapture (ver el plan, Task 8 paso 6).
"""
from voooxly import settings_window, shortcuts

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def test_key_label_pinta_un_modificador_con_su_simbolo():
    assert settings_window.key_label(["cmd_r"]) == "⌘"
    assert settings_window.key_label(["shift"]) == "⇧"


def test_key_label_pinta_un_combo_en_orden():
    assert settings_window.key_label(["ctrl", "shift", "m"]) == "⌃⇧M"


def test_key_label_pinta_esc_y_las_funciones_por_su_nombre():
    assert settings_window.key_label(["esc"]) == "esc"
    assert settings_window.key_label(["f13"]) == "F13"


def test_key_label_de_una_lista_vacia_no_revienta():
    assert settings_window.key_label([]) == ""


def test_side_label_distingue_izquierda_y_derecha():
    # dictation y cancel casan por igualdad exacta en hotkey.py (líneas 397 y
    # 432): un nombre con lado siempre casa solo ese lado. La decisión vive en
    # shortcuts.side_hint; side_label es solo el envoltorio de presentación,
    # por eso necesita saber a qué atajo (sid) pertenece la tecla.
    assert settings_window.side_label("dictation", ["cmd_r"]) == "right"
    assert settings_window.side_label("dictation", ["cmd_l"]) == "left"
    assert settings_window.side_label("dictation", ["cmd"]) == "left"      # pynput colapsa la izquierda
    assert settings_window.side_label("cancel", ["esc"]) == ""


def test_side_label_pintado_dice_la_verdad_para_los_cuatro_atajos_por_defecto():
    """Las pruebas anteriores solo comprobaban que las filas existían, nunca
    el texto que de verdad se pintaba en pantalla — por eso hizo falta un
    screenshot para pescar que "Cycle mode" y "Latch dictation" mostraban
    "left" siendo mentira (un combo no tiene lado; el shift de latch casa las
    dos manos). Esto lee stringValue() de la etiqueta ya renderizada."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    esperado = {
        "dictation": "right",     # cmd_r: igualdad exacta, solo la derecha
        "cycle_mode": "",         # combo de tres teclas, sin lado
        "latch": "either side",   # "shift" ensancha a shift_r en hotkey.py
        "cancel": "",             # esc no tiene lado
    }
    for sid, texto in esperado.items():
        assert c._sides[sid].stringValue() == texto, sid
    c.close()


def test_el_controlador_construye():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert c is not None
    c.close()


def test_construye_una_fila_por_atajo():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert set(c._rows) == set(shortcuts.SHORTCUTS)
    c.close()


def test_la_ventana_es_un_nswindow_no_un_nspanel():
    # En macOS 26 (Darwin 25) el window server NUNCA compone un NSPanel:
    # isVisible=True, alpha=1, CGWindowList vacío y cero píxeles. El HUD
    # estuvo roto en silencio por esto. Un test barato que impide la recaída.
    from AppKit import NSPanel

    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert not isinstance(c._win, NSPanel)
    c.close()
