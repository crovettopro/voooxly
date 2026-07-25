"""The Shortcuts window: that it builds and that the labels are legible.

The tests instantiate the real AppKit controller, like the onboarding
ones: that validates the window builds without blowing up, which is the
most expensive failure and the easiest one to introduce.

What CANNOT be validated here is that the window is SEEN. On macOS 26 an
NSPanel returns isVisible=True and paints not a single pixel; that is why
the window is an NSWindow and why verifying that it composites is manual,
with screencapture (see the plan, Task 8 step 6).
"""
from voooxly import settings_window, shortcuts, theme

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


def test_key_label_with_empty_list_does_not_crash():
    assert settings_window.key_label([]) == ""


def test_side_label_distingue_izquierda_y_derecha():
    # dictation and cancel match by exact equality in hotkey.py (lines 397 and
    # 432): a sided name always matches only that side. The decision lives in
    # shortcuts.side_hint; side_label is just the presentation wrapper, which
    # is why it needs to know which shortcut (sid) the key belongs to.
    assert settings_window.side_label("dictation", ["cmd_r"]) == "right"
    assert settings_window.side_label("dictation", ["cmd_l"]) == "left"
    assert settings_window.side_label("dictation", ["cmd"]) == "left"      # pynput collapses the left side
    assert settings_window.side_label("cancel", ["esc"]) == ""


def test_side_label_pintado_dice_la_verdad_para_los_cuatro_atajos_por_defecto():
    """The previous tests only checked that the rows existed, never the
    text actually painted on screen — that is why a screenshot was needed
    to catch that "Cycle mode" and "Latch dictation" showed "left" when it
    was a lie (a combo has no side; latch's shift matches both hands).
    This reads stringValue() from the already-rendered label."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    esperado = {
        "dictation": "right",     # cmd_r: exact equality, right side only
        "cycle_mode": "",         # three-key combo, no side
        "latch": "either side",   # "shift" widens to shift_r in hotkey.py
        "cancel": "",             # esc has no side
    }
    for sid, texto in esperado.items():
        assert c._sides[sid].stringValue() == texto, sid
    c.close()


def test_el_controlador_construye():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert c is not None
    c.close()


def test_builds_one_row_per_shortcut():
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert set(c._rows) == set(shortcuts.SHORTCUTS)
    c.close()


def test_la_etiqueta_de_lado_no_corta_either_side():
    """The real bug: the field measured a fixed 58pt, meant for "right",
    and "either side" (latch's factory value) measures more than that with
    its own font — the text was correct (stringValue() already proved it)
    but the glyph was clipped on screen. This cannot prove it does not
    look clipped (a manual screenshot is needed for that), but it can
    blow up as soon as the built frame again falls short for the text it
    actually has to paint."""
    from AppKit import NSFontAttributeName
    from Foundation import NSString

    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    campo = c._sides["latch"]
    ancho_texto = NSString.stringWithString_(campo.stringValue()).sizeWithAttributes_(
        {NSFontAttributeName: campo.font()}).width
    assert campo.frame().size.width >= ancho_texto, (
        campo.frame().size.width, ancho_texto)
    c.close()


def test_los_campos_de_chips_quedan_alineados_en_las_cuatro_filas():
    """field_width() is a SINGLE value for the four rows (the same decision
    as lado_w): four fields of different widths would read staggered. With
    a shared width and right edge, they share the x too."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    xs = {sid: campo.frame().origin.x for sid, campo in c._fields.items()}
    assert len(set(xs.values())) == 1, xs
    c.close()


# The inheritance of Defect 2 of Task 10: with cycle_mode on five keys the
# single keycap clipped the Q. With chips the equivalent risk is that the
# field falls short and the last chip (or the pencil) sticks out.
_ESTADO_COMBO_LARGO = {**ESTADO, "cycle_mode": {"keys": ["ctrl", "alt", "shift", "cmd", "q"]}}


def test_long_combo_chips_fit_in_field():
    """Five chips + the pencil have to fit INSIDE the field: the last
    chip's right edge is compared against the pencil's start, and the
    pencil's against the field width — real frames, not constants."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        _ESTADO_COMBO_LARGO, lambda sid, fila: (True, ""))
    campo = c._fields["cycle_mode"]
    chips = c._chips["cycle_mode"]
    assert len(chips) == 5
    ultimo = chips[-1].frame()
    lapiz = c._pencils["cycle_mode"].frame()
    assert ultimo.origin.x + ultimo.size.width <= lapiz.origin.x, (ultimo, lapiz)
    assert lapiz.origin.x + lapiz.size.width <= campo.frame().size.width
    c.close()


def test_todos_los_campos_comparten_ancho_y_respetan_el_minimo():
    """The shared width never drops below _FIELD_MIN_W (a single-chip
    field would still look like a field, not a splinter) and rises evenly
    for the four rows when a long combo asks for it."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        _ESTADO_COMBO_LARGO, lambda sid, fila: (True, ""))
    anchos = {campo.frame().size.width for campo in c._fields.values()}
    assert len(anchos) == 1
    assert anchos.pop() >= settings_window._FIELD_MIN_W
    c.close()


def test_field_does_not_overlap_side_label():
    """The side label lives to the LEFT of the field: its right edge
    cannot step on the field's start. Real frames against real frames,
    not against layout constants."""
    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        _ESTADO_COMBO_LARGO, lambda sid, fila: (True, ""))
    for sid in shortcuts.SHORTCUTS:
        campo = c._fields[sid]
        lado = c._sides[sid]
        assert lado.frame().origin.x + lado.frame().size.width <= campo.frame().origin.x, (
            sid, lado.frame(), campo.frame())
    c.close()


def test_la_ventana_es_un_nswindow_no_un_nspanel():
    # On macOS 26 (Darwin 25) the window server NEVER composites an NSPanel:
    # isVisible=True, alpha=1, empty CGWindowList and zero pixels. The HUD
    # was silently broken because of this. A cheap test preventing relapse.
    from AppKit import NSPanel

    c = settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, lambda sid, fila: (True, ""))
    assert not isinstance(c._win, NSPanel)
    c.close()
