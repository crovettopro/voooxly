"""The drawn keyboard: which keys light up and on whose behalf.

The keyboard and the list are the SAME truth. If they diverge, the user sees
a lit key that the list says is not assigned and stops trusting both. That
is why lit_keys() derives from the same state the list paints.
"""
from voooxly import settings_window, shortcuts, theme

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
    # ⇧ is the latch and also part of ⌃⇧M. Dictation wins over the rest
    # because it is the key the user looks for at a glance; without a
    # tie-breaking rule the color would depend on dictionary order.
    estado = dict(ESTADO, dictation={"keys": ["shift"], "style": "hold", "delay_ms": 400})
    assert settings_window.lit_keys(estado)["shift"] == "dictation"


def test_las_teclas_se_canonicalizan_antes_de_encenderse():
    # "cmd_l" and "cmd" are the same physical key: the keyboard has to
    # light the same cell in both cases or the user sees their key
    # unlit after picking it.
    estado = dict(ESTADO, dictation={"keys": ["cmd_l"], "style": "hold", "delay_ms": 400})
    lit = settings_window.lit_keys(estado)
    assert "cmd" in lit


def test_lit_keys_y_side_hint_cuentan_la_misma_verdad_sobre_los_lados():
    """Defect 1 of Task 9: side_hint() (the row's text) and lit_keys()
    (the cells that light up) were two independent implementations of the
    same runtime fact and could fall out of sync. The real bug: with the
    factory latch (shift), the row said "either side" but the keyboard
    only lit the left ⇧ -shift_r stayed unlit-.

    Both now derive from shortcuts.matched_keys(), so they are tied here
    STRUCTURALLY to that function, not to a hand-pinned dictionary of lit
    keys: for every single-key shortcut, if side_hint() says "either side"
    then BOTH keys from matched_keys(), and only those, must be lit; if it
    says "right"/"left" that single key must be lit. This keeps holding
    even if tomorrow the factory key of any of the four shortcuts changes.
    """
    lit = settings_window.lit_keys(ESTADO)
    for sid, fila in ESTADO.items():
        nombres = list(fila.get("keys") or [])
        if len(nombres) != 1:
            continue  # combos have no side; side_hint returns ""
        lado = shortcuts.side_hint(sid, nombres)
        casadas = shortcuts.matched_keys(sid, nombres)
        if lado == "either side":
            assert len(casadas) == 2, (sid, casadas)
        elif lado in ("right", "left"):
            assert len(casadas) == 1, (sid, casadas)
        else:
            continue
        for tecla in casadas:
            assert lit.get(tecla) == sid, (sid, tecla, lit)


def test_el_teclado_tiene_las_seis_filas_de_un_mac():
    assert len(settings_window.KEYBOARD_ROWS) == 6


def test_el_teclado_incluye_las_teclas_que_importan():
    todas = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in ("esc", "cmd_r", "cmd", "shift", "ctrl", "alt", "m", "f13"):
        assert n in todas, n


def test_las_teclas_de_relleno_llevan_nombre_y_ya_no_quedan_huecos():
    """Defect 2 of Task 9 (first round): KEYBOARD_ROWS drew blank
    rectangles for punctuation and for ⇪/fn; in the screenshot they read
    as broken keys, not as "this cannot be assigned". They now carry a
    name, even though none is assignable, and therefore their cell never
    lights up.

    The two deliberately nameless gaps that remained no longer exist
    (Defects 3 and 4 of the second round): the one in the number row was a
    portrait error -a real ANSI Mac starts that row with the backtick and
    has no gap between "=" and ⌫-, and the arrow block now carries the
    legend "◀▼▶" with the synthetic name "arrows". No nameless cell
    remains.
    """
    nombres = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in ("`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/",
              "caps_lock", "fn", "arrows"):
        assert n in nombres, n

    huecos = [n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n == ""]
    assert huecos == []


def test_keyboard_rows_sin_teclas_huerfanas_devuelve_el_retrato_tal_cual():
    """With no key assigned outside KEYBOARD_ROWS, keyboard_rows() does not
    invent an extra row: it returns KEYBOARD_ROWS as is, so that the
    geometry (alto_fila) does not change without anything justifying it."""
    assert settings_window.keyboard_rows(ESTADO) == settings_window.KEYBOARD_ROWS


def test_toda_tecla_de_lit_keys_aparece_en_el_layout_dibujado():
    """Defect 1 of Task 9 (second round): KEYBOARD_ROWS portrays a MacBook
    and does not contain every assignable key -f14 is the example: the app
    accepts it via config.yaml/prefs.json (keys._FUNCIONES) even though the
    portrait only paints f1..f13-. With the key lit in the list and absent
    from the keyboard, the user sees exactly the contradiction this
    component exists to prevent.

    Structural and not a list of cases: for several states -one with a key
    clearly outside the portrait (f14) and another with two orphans at
    once (f14 and f15)- every key of lit_keys() has to appear among the
    names of keyboard_rows(). No comparing the extra row against a
    hand-pinned list.
    """
    estados = [
        ESTADO,
        dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0}),
        dict(ESTADO, latch={"keys": ["f15"]}),
        dict(ESTADO,
             dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0},
             latch={"keys": ["f15"]}),
    ]
    for estado in estados:
        filas = settings_window.keyboard_rows(estado)
        nombres = {n for fila in filas for n, _ in fila if n}
        for tecla in settings_window.lit_keys(estado):
            assert tecla in nombres, (estado, tecla)


def test_off_portrait_key_is_actually_visible_in_window():
    """It is not enough for keyboard_rows() to include the orphan key in
    theory: _build_keyboard() has to actually use that row so the cell
    exists in the real window, with its legend, or the window would keep
    showing the same contradiction this defect fixes."""
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    assert "f14" in c._keys
    assert c._legends["f14"].stringValue() == settings_window.key_label(["f14"])
    assert settings_window.lit_keys(estado)["f14"] == "dictation"
    c.close()


def test_las_teclas_de_relleno_nombradas_llevan_la_leyenda_de_key_label():
    """Ties the drawn cell to key_label(), the same function the keycaps
    of the four rows already paint with: no parallel table of symbols at
    the drawing site (the brief's explicit instruction).
    Structural over ALL the names in KEYBOARD_ROWS, not a hand-pinned
    list of pairs.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    nombres = {n for fila in settings_window.KEYBOARD_ROWS for n, _ in fila if n}
    for n in nombres:
        assert c._legends[n].stringValue() == settings_window.key_label([n]), n
        assert c._legends[n].stringValue() != "", n
    c.close()


def test_painting_keyboard_does_not_crash():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    c._paint_keyboard()
    assert len(c._keys) > 40
    c.close()


def _se_solapan(a, b):
    """True if two NSRects share any interior point.

    Generic geometric comparison, not a formula tied to this window's
    numbers: it works just the same if PAD, ROW_H or the keyboard
    height change tomorrow.
    """
    ax0, ay0 = a.origin.x, a.origin.y
    ax1, ay1 = ax0 + a.size.width, ay0 + a.size.height
    bx0, by0 = b.origin.x, b.origin.y
    bx1, by1 = bx0 + b.size.width, by0 + b.size.height
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def test_el_teclado_no_se_solapa_con_la_primera_fila():
    """The keyboard is drawn in the empty band above the rows, not on
    top of them. The real relationship between the two frames is
    compared —they do not touch, and the keyboard's sits above— instead
    of pinning an origin.y by hand: that number would go stale as soon
    as the layout was legitimately tweaked, and such a test would pass
    even if the keyboard overlapped any other row again.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    primer_sid = next(iter(shortcuts.SHORTCUTS))
    marco = c._teclado_marco.frame()
    fila = c._rows[primer_sid].frame()

    assert not _se_solapan(marco, fila), "el teclado invade la primera fila"
    # AppKit coordinates: origin at bottom-left. "Above" means that
    # the keyboard's bottom edge does not fall below the row's top
    # edge.
    assert marco.origin.y >= fila.origin.y + fila.size.height

    c.close()


def test_every_named_cell_has_exactly_one_legend_and_fillers_have_none():
    """Neither orphans (a named cell without its legend) nor extras: the
    filler cells ("") exist only so the keyboard is recognizable at a
    glance and never light up (see the KEYBOARD_ROWS comment), so they
    carry no legend either."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert set(c._legends) == set(c._keys)
    assert len(c._legends) > 40
    c.close()


def test_repintar_el_teclado_no_reconstruye_las_leyendas():
    """_paint_keyboard() recolors existing cells, it never rebuilds them
    (see the _build_keyboard docstring: adding and removing subviews on
    every repaint makes the window flicker). The legends have to follow
    the same rule: the NSTextField is created once and recolored, not
    created anew with the same text on every repaint."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    antes = c._legends["cmd_r"]
    c._paint_keyboard()
    c._paint_keyboard()
    assert c._legends["cmd_r"] is antes
    c.close()


def test_la_leyenda_de_una_tecla_encendida_en_solido_cambia_de_color_para_seguir_siendo_legible():
    """dictation paints its cell in solid teal (theme.TEAL): the dark
    gray of an unlit legend (theme.INK_KEYCAP) would be illegible there.
    The legend has to be recolored in the same place where the fill is
    recolored (_paint_keyboard), or the two can fall out of sync: a lit
    cell with its legend in the color of an unlit one.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    encendida = c._legends["cmd_r"]   # dictation in ESTADO: keys=["cmd_r"]
    apagada = c._legends["a"]         # no default assignment touches it

    assert apagada.textColor().isEqual_(theme.INK_KEYCAP)
    assert encendida.textColor().isEqual_(theme.PAGE_BG)
    assert not encendida.textColor().isEqual_(apagada.textColor())
    c.close()


def test_la_leyenda_de_una_tecla_encendida_en_tono_suave_sigue_legible():
    """cycle_mode/latch/cancel paint their cell in a very light teal
    (theme.MODEL_BTN_BG): there the usual dark gray is already legible,
    so the legend does NOT have to change color as in dictation — only
    the solid-fill cell needs that adjustment. This documents the
    decision with a test, not just with a comment."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    suave = c._legends["esc"]   # cancel in ESTADO: keys=["esc"]
    assert suave.textColor().isEqual_(theme.INK_KEYCAP)
    c.close()


def test_la_casilla_huerfana_tiene_ancho_de_modificadora_no_de_fila():
    """Defect 1 of Task 9 (third round): with a single orphan key in the
    row, a proportional weight of 1.0 took 100% of the width and the cell
    was drawn like a space bar -exactly what a drawn keyboard exists not
    to lie about. The orphan cell has to come out with a width comparable
    to that of a normal modifier key of the portrait (here "cmd"), well
    below the full row width. Structural comparison between already-drawn
    widths, no pinned pixel constant whatsoever.
    """
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))

    ancho_huerfana = c._keys["f14"].frame().size.width
    ancho_cmd = c._keys["cmd"].frame().size.width
    ancho_fila = c._teclado_marco.frame().size.width

    # "Comparable", not forcibly identical: a few points of margin
    # absorb the rounding of the weight arithmetic without letting a
    # regression to the old proportional split through.
    assert abs(ancho_huerfana - ancho_cmd) < 2.0, (ancho_huerfana, ancho_cmd)
    assert ancho_huerfana < ancho_fila / 3, (ancho_huerfana, ancho_fila)
    c.close()


def test_orphan_cell_is_not_stretched_with_several_orphans_at_once():
    """The same guarantee as the previous test, but with two orphan keys
    in the row at once (f15 and f14): each one keeps the width of a
    normal modifier, not the row's width split between two.
    """
    estado = dict(ESTADO,
                   dictation={"keys": ["f15"], "style": "hold", "delay_ms": 0},
                   latch={"keys": ["f14"]})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))

    ancho_cmd = c._keys["cmd"].frame().size.width
    for tecla in ("f15", "f14"):
        ancho = c._keys[tecla].frame().size.width
        assert abs(ancho - ancho_cmd) < 2.0, (tecla, ancho, ancho_cmd)
    c.close()


def test_el_resto_de_la_fila_huerfana_no_dibuja_ninguna_casilla():
    """Defect 1 of Task 9 (third round): the width the orphan cell does
    not use stays empty -keyboard background, no drawn view- instead of
    an unlit filler cell, which is exactly the previous round's
    "legendless hole that looks like a broken key". keyboard_rows()
    reserves that remainder with a `None` name; this test checks that
    _build_keyboard() really skips it and creates no cell or legend
    for it.
    """
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    fila_huerfana = settings_window.keyboard_rows(estado)[-1]
    huecos = [n for n, _ in fila_huerfana if n is None]
    assert huecos, "la fila huérfana debería reservar hueco vacío"

    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    # No cell or legend carries a None key: there is no view for the gap.
    assert None not in c._keys
    assert None not in c._legends
    c.close()


def test_la_fila_huerfana_explica_por_que_esa_tecla_esta_ahi():
    """Defect 2 of Task 9 (third round): a loose, unexplained orphan key
    looks randomly placed. The window has to show the text
    "not on this keyboard" when there is an orphan row, and NOT show it
    when there is none (the common case, with the factory state).
    """
    sin_huerfanas = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert sin_huerfanas._nota_huerfana is None
    sin_huerfanas.close()

    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    con_huerfana = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    assert con_huerfana._nota_huerfana is not None
    assert con_huerfana._nota_huerfana.stringValue() == settings_window.NOTA_HUERFANA
    con_huerfana.close()


def test_el_texto_de_la_fila_huerfana_no_se_recorta():
    """Task 8 silently clipped "either side" with a field width pinned by
    eye, and the test that read stringValue() passed anyway because
    stringValue() knows nothing about the cut glyph. Here the same thing
    that avoided that bug is checked: the drawn field measures, measured
    with the SAME function (theme.text_width) that _build_keyboard() uses
    to size it, at least as much as the text needs with its own font -if
    the field were narrower, the text (correct in stringValue()) would be
    clipped when drawn without this test noticing, just as happened to
    Task 8.
    """
    estado = dict(ESTADO, dictation={"keys": ["f14"], "style": "hold", "delay_ms": 0})
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado, lambda sid, fila: (True, ""))
    nota = c._nota_huerfana
    ancho_necesario = theme.text_width(nota.stringValue(), nota.font())
    assert nota.frame().size.width >= ancho_necesario
    c.close()


def test_keyboard_does_not_exceed_window_content():
    """The error symmetric to the overlap: a keyboard shifted too far up
    would run off the window's top edge instead of invading the rows.
    The two tests together cover both directions in which a miscalculated
    origin can fail.
    """
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    marco = c._teclado_marco.frame()

    assert marco.origin.x >= 0
    assert marco.origin.y >= 0
    assert marco.origin.x + marco.size.width <= settings_window.W
    assert marco.origin.y + marco.size.height <= settings_window.H

    c.close()


# --- capture: green = usable, gray = not usable (POMI feedback) ---

def _controller(estado=None):
    return settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado or ESTADO, lambda sid, fila: (True, ""))


def test_durante_la_captura_las_letras_se_apagan_y_las_usables_se_encienden():
    """Capturing Dictation: a letter would render the whole keyboard
    unusable (validate rejects it) → gray; an F key or a sided modifier →
    SOLID teal with a paper-colored legend. The light teal of the first
    version (MODEL_BTN_BG) was indistinguishable from gray on screen —
    "el teclado se ve completo", said Eduardo — so the contrast is part of
    the contract. The truth comes from shortcuts.validate, the SAME
    validator that later accepts or rejects the capture — the color cannot
    promise what validate will deny."""
    c = _controller()
    c.begin_capture_("dictation")

    assert c._legends["a"].textColor().isEqual_(theme.INK_MUTED)     # letter: no
    assert c._legends["esc"].textColor().isEqual_(theme.INK_MUTED)   # owner of cancel
    assert c._legends["shift"].textColor().isEqual_(theme.INK_MUTED) # owner of latch
    assert c._legends["f13"].textColor().isEqual_(theme.PAGE_BG)     # usable: lit
    assert c._legends["cmd_r"].textColor().isEqual_(theme.PAGE_BG)   # its own: usable
    c.close()


def test_decorative_keys_never_light_up_during_capture():
    """⇪ and the arrow block have a legend but are not assignable: during
    capture they come out gray, not as a promise of an eligible key. fn is
    NO longer here: since hotkey.py straightens it out it is a dictation
    key in its own right (see the next test)."""
    c = _controller()
    c.begin_capture_("dictation")
    for nombre in ("caps_lock", "arrows", ";", ","):
        assert c._legends[nombre].textColor().isEqual_(theme.INK_MUTED), nombre
    c.close()


def test_fn_se_enciende_capturando_dictation():
    """Wispr Flow's star key, expressly requested ("es vital tener
    también fn"): capturing Dictation it has to be offered in green."""
    c = _controller()
    c.begin_capture_("dictation")
    assert c._legends["fn"].textColor().isEqual_(theme.PAGE_BG)
    c.close()


def test_los_modificadores_izquierdos_se_encienden_capturando_dictation():
    """The left ⌘/⌥/⌃ are legitimate dictation keys (DICTATION_KEYS
    offers them, with a guard): the keyboard has to offer them in green,
    not leave them gray as if there were no way to pick them. Not shift:
    it stays reserved for latch."""
    c = _controller()
    c.begin_capture_("dictation")
    for nombre in ("cmd", "alt", "ctrl"):
        assert c._legends[nombre].textColor().isEqual_(theme.PAGE_BG), nombre
    assert c._legends["shift"].textColor().isEqual_(theme.INK_MUTED)
    c.close()


def test_cada_atajo_tiene_sus_propias_usables():
    """esc is gray capturing Dictation (it belongs to Cancel) but green
    capturing Cancel (confirming your own key is never a conflict)."""
    c = _controller()
    c.begin_capture_("cancel")
    assert c._legends["esc"].textColor().isEqual_(theme.PAGE_BG)
    assert c._legends["cmd_r"].textColor().isEqual_(theme.INK_MUTED)  # Dictation's
    c.close()


def test_al_salir_de_la_captura_vuelve_el_pintado_por_asignaciones():
    c = _controller()
    c.begin_capture_("dictation")
    c.cancel_capture_()
    # dictation returns to its solid teal (paper-colored legend) and the
    # loose letter gets back the normal dark gray of an unlit key.
    assert c._legends["cmd_r"].textColor().isEqual_(theme.PAGE_BG)
    assert c._legends["a"].textColor().isEqual_(theme.INK_KEYCAP)
    c.close()


def test_applying_valid_capture_also_restores_keyboard():
    c = _controller()
    c.begin_capture_("dictation")
    c.apply_capture_(["f13"])
    assert c._capturing is None
    # f13 is now the dictation key: solid teal with a paper-colored legend.
    assert c._legends["f13"].textColor().isEqual_(theme.PAGE_BG)
    assert c._legends["a"].textColor().isEqual_(theme.INK_KEYCAP)
    c.close()
