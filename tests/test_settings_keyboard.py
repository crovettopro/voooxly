"""El teclado dibujado: qué teclas se encienden y de parte de quién.

El teclado y la lista son la MISMA verdad. Si divergen, el usuario ve una
tecla encendida que la lista dice que no está asignada y deja de fiarse de
las dos. Por eso lit_keys() sale del mismo estado que pinta la lista.
"""
from voooxly import settings_window, shortcuts

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def test_se_encienden_todas_las_teclas_asignadas():
    lit = settings_window.lit_keys(ESTADO)
    assert lit["cmd_r"] == "dictation"
    assert lit["esc"] == "cancel"
    assert lit["m"] == "cycle_mode"


def test_una_tecla_compartida_la_reclama_dictation():
    # ⇧ es el latch y también parte de ⌃⇧M. Dictation manda sobre el resto
    # porque es la tecla que el usuario busca de un vistazo; sin una regla de
    # desempate el color dependería del orden del diccionario.
    estado = dict(ESTADO, dictation={"keys": ["shift"], "style": "hold", "delay_ms": 400})
    assert settings_window.lit_keys(estado)["shift"] == "dictation"


def test_las_teclas_se_canonicalizan_antes_de_encenderse():
    # "cmd_l" y "cmd" son la misma tecla física: el teclado tiene que
    # encender la misma casilla en los dos casos o el usuario ve su tecla
    # apagada tras elegirla.
    estado = dict(ESTADO, dictation={"keys": ["cmd_l"], "style": "hold", "delay_ms": 400})
    lit = settings_window.lit_keys(estado)
    assert "cmd" in lit


def test_el_teclado_tiene_las_seis_filas_de_un_mac():
    assert len(settings_window.KEYBOARD_ROWS) == 6


def test_el_teclado_incluye_las_teclas_que_importan():
    todas = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in ("esc", "cmd_r", "cmd", "shift", "ctrl", "alt", "m", "f13"):
        assert n in todas, n


def test_pintar_el_teclado_no_revienta():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    c._paint_keyboard()
    assert len(c._keys) > 40
    c.close()


def _se_solapan(a, b):
    """Verdadero si dos NSRect comparten algún punto interior.

    Comparación geométrica genérica, no una fórmula atada a los números
    de esta ventana: sirve igual si mañana cambian PAD, ROW_H o la altura
    del teclado.
    """
    ax0, ay0 = a.origin.x, a.origin.y
    ax1, ay1 = ax0 + a.size.width, ay0 + a.size.height
    bx0, by0 = b.origin.x, b.origin.y
    bx1, by1 = bx0 + b.size.width, by0 + b.size.height
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def test_el_teclado_no_se_solapa_con_la_primera_fila():
    """El teclado se dibuja en la banda vacía de encima de las filas, no
    sobre ellas. Se compara la relación real entre los dos marcos —no se
    tocan, y el del teclado queda por encima— en vez de fijar un
    origin.y a mano: ese número quedaría obsoleto en cuanto la
    disposición se retocara legítimamente, y un test así pasaría aunque
    el teclado volviera a solaparse con cualquier otra fila.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    primer_sid = next(iter(shortcuts.SHORTCUTS))
    marco = c._teclado_marco.frame()
    fila = c._rows[primer_sid].frame()

    assert not _se_solapan(marco, fila), "el teclado invade la primera fila"
    # Coordenadas AppKit: origen abajo-izquierda. "Por encima" significa
    # que el borde inferior del teclado no cae por debajo del borde
    # superior de la fila.
    assert marco.origin.y >= fila.origin.y + fila.size.height

    c.close()


def test_el_teclado_no_se_sale_del_contenido_de_la_ventana():
    """El error simétrico al solapamiento: un teclado desplazado de más
    hacia arriba se saldría del borde superior de la ventana en lugar de
    invadir las filas. Las dos pruebas juntas cubren los dos sentidos en
    los que un origen mal calculado puede fallar.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    marco = c._teclado_marco.frame()

    assert marco.origin.x >= 0
    assert marco.origin.y >= 0
    assert marco.origin.x + marco.size.width <= settings_window.W
    assert marco.origin.y + marco.size.height <= settings_window.H

    c.close()
