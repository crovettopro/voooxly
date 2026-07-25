"""The Wispr Flow-style chip field and the Reset to defaults.

From Eduardo's feedback (with Wispr screenshots): each key of the shortcut is
its OWN chip inside a field with a pencil ✎ at the end; while capturing, what
you press is reflected live in the field AND on the keyboard; and a button
returns everything to factory settings. The tests instantiate the real AppKit
controller, like the rest of this window's tests.
"""
from PyObjCTools import AppHelper

from voooxly import settings_window, shortcuts, theme

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def _ctl(estado=None, on_change=None):
    return settings_window.ShortcutsController.alloc().initWithState_onChange_(
        estado or ESTADO, on_change or (lambda sid, fila: (True, "")))


def test_chip_texts_gives_one_chip_per_key():
    assert settings_window.chip_texts(["ctrl", "shift", "m"]) == ["⌃", "⇧", "M"]
    assert settings_window.chip_texts(["fn"]) == ["fn"]
    assert settings_window.chip_texts([]) == []


def test_each_row_paints_one_chip_per_key_in_its_binding():
    c = _ctl()
    assert len(c._chips["cycle_mode"]) == 3
    assert len(c._chips["dictation"]) == 1
    # The chip text comes from key_label key by key: the single subview
    # of the theme keycap carries the glyph.
    textos = [chip.subviews()[0].stringValue() for chip in c._chips["cycle_mode"]]
    assert textos == ["⌃", "⇧", "M"]
    c.close()


def test_each_field_has_its_pencil():
    # The pencil IS the edit affordance (the previous "Change" was not
    # recognized as an action): it has to be on all four rows.
    c = _ctl()
    for sid in shortcuts.SHORTCUTS:
        assert c._pencils[sid].stringValue() == settings_window._PENCIL_TXT, sid
    c.close()


def test_on_capture_field_shows_placeholder_until_first_key():
    c = _ctl()
    assert c._hints["dictation"].isHidden()
    c.begin_capture_("dictation")
    assert not c._hints["dictation"].isHidden()
    assert c._chips["dictation"] == []          # no keys yet: empty field
    assert c._hints["cancel"].isHidden()        # only the row being captured
    c.close()


def test_row_being_captured_is_fully_highlighted():
    c = _ctl()
    c.begin_capture_("latch")
    assert c._rows["latch"].layer().backgroundColor() == theme.MODEL_BTN_BG.CGColor()
    assert c._rows["cancel"].layer().backgroundColor() == theme.PAGE_BG.CGColor()
    c.cancel_capture_()
    assert c._rows["latch"].layer().backgroundColor() == theme.PAGE_BG.CGColor()
    c.close()


def test_what_was_pressed_reflects_in_chips_and_keyboard(monkeypatch):
    """The heart of the feedback: "si marco el shortcut que se refleje en el
    teclado". A lone letter does not validate as a dictation shortcut (it
    would cripple the whole keyboard), but the X chip shows up in the field
    and its key cell rises to TEAL_DARK — the user SEES that the press
    arrived even if it is not a valid shortcut, and the capture stays
    armed so they can try again."""
    monkeypatch.setattr(AppHelper, "callAfter", lambda fn, *a, **kw: fn(*a, **kw))
    c = _ctl()
    c.begin_capture_("dictation")
    c._on_captured_(["x"])
    assert c._capturing == "dictation"          # validate rejected: still armed
    textos = [chip.subviews()[0].stringValue() for chip in c._chips["dictation"]]
    assert textos == ["X"]
    assert c._keys["x"].layer().backgroundColor() == theme.TEAL_DARK.CGColor()
    assert c._legends["x"].textColor().isEqual_(theme.PAGE_BG)
    c.close()


def test_valid_capture_leaves_chips_of_new_binding():
    c = _ctl()
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    textos = [chip.subviews()[0].stringValue() for chip in c._chips["cancel"]]
    assert textos == ["F13"]
    assert c._hints["cancel"].isHidden()
    c.close()


def test_reset_returns_four_shortcuts_to_factory():
    cambiados = dict(
        ESTADO,
        dictation={"keys": ["f13"], "style": "hold", "delay_ms": 600},
        cancel={"keys": ["ctrl", "shift"]},
    )
    vistos = []
    c = _ctl(cambiados, lambda sid, fila: (vistos.append(sid), (True, ""))[1])
    c.resetDefaults_(None)
    for sid, sc in shortcuts.SHORTCUTS.items():
        assert c._estado[sid]["keys"] == list(sc.default), sid
    # cmd_r needs no guard: the factory delay is 0, not the earlier 600.
    assert c._estado["dictation"]["delay_ms"] == 0
    assert set(vistos) == set(shortcuts.SHORTCUTS)
    c.close()


def test_reset_cancels_a_half_finished_capture():
    c = _ctl()
    c.begin_capture_("dictation")
    c.resetDefaults_(None)
    assert c._capturing is None
    c.close()
