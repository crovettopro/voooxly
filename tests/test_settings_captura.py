"""Capturing a key from the window and adjusting the delay.

The rule that is hardest to get right is the slider's automatic jump: picking
the left ⌘ with 0 ms leaves the app unusable (every ⌘C starts a recording),
so the slider jumps to 400 on its own. But picking the right ⌘ must NOT bump
anyone from 0 to 400: that would change the app's feel behind their back.
"""
from AppKit import NSFontAttributeName, NSStringDrawingUsesLineFragmentOrigin, NSString
from Foundation import NSMakeSize
from PyObjCTools import AppHelper
from pynput.keyboard import Key

from voooxly import keys, settings_window, shortcuts, theme

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def _ctl(on_change=None):
    return settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, on_change or (lambda sid, fila: (True, "")))


class _HotkeyFalso:
    """Test double for HotkeyManager (Finding 2 of the review). NEVER the
    real one: instantiating a second real `keyboard.Listener` makes
    macOS abort with SIGABRT (TIS/TSM called from two threads, see
    attachHotkey_ in settings_window.py), so the double only records the
    call and stores the callback for the test to fire by hand, the way
    pynput would from its own thread."""

    def __init__(self):
        self.capturas = 0
        self.cb = None
        self.canceladas = 0

    def begin_capture(self, cb):
        self.capturas += 1
        self.cb = cb

    def end_capture(self):
        self.canceladas += 1


def test_conflicting_key_raises_delay_to_default():
    assert settings_window.delay_for(["cmd_l"], 0) == shortcuts.DEFAULT_DELAY_MS


def test_non_conflicting_key_keeps_previous_delay():
    # Zero regression: whoever had 0 with the right ⌘ keeps 0.
    assert settings_window.delay_for(["cmd_r"], 0) == 0


def test_non_conflicting_key_does_not_lower_an_already_chosen_delay():
    # If the user had set 600 by hand, changing the key does not clobber it.
    assert settings_window.delay_for(["cmd_r"], 600) == 600


def test_capturing_applies_key_and_notifies_caller():
    visto = []
    c = _ctl(lambda sid, fila: (visto.append((sid, fila)), (True, ""))[1])
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert visto[-1][0] == "cancel"
    assert visto[-1][1]["keys"] == ["f13"]
    c.close()


def test_conflicting_key_is_not_applied():
    visto = []
    c = _ctl(lambda sid, fila: (visto.append(sid), (True, ""))[1])
    c.begin_capture_("dictation")
    c.apply_capture_(["esc"])          # it is already the cancel key
    assert visto == [], "se aplicó una tecla en conflicto"
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    c.close()


def test_conflicting_key_leaves_message_in_row():
    c = _ctl()
    c.begin_capture_("dictation")
    c.apply_capture_(["esc"])
    assert "Cancel dictation" in c._error_text
    c.close()


def test_if_caller_rejects_change_state_is_not_touched():
    # on_change returns (False, msg) when hotkey.rebind() rejects: the
    # window's state has to reflect what is actually in effect, not what
    # was requested, or the keycap would lie.
    c = _ctl(lambda sid, fila: (False, "nope"))
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert c._estado["cancel"]["keys"] == ["esc"]
    assert c._error_text == "nope"
    c.close()


def test_canceling_capture_leaves_shortcut_as_it_was():
    c = _ctl()
    c.begin_capture_("dictation")
    c.cancel_capture_()
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    assert c._capturing is None
    c.close()


def test_delay_is_clamped_to_range():
    c = _ctl()
    c.set_delay_(9999)
    assert c._estado["dictation"]["delay_ms"] == shortcuts.MAX_DELAY_MS
    c.set_delay_(-5)
    assert c._estado["dictation"]["delay_ms"] == 0
    c.close()


def test_capturing_repaints_keyboard():
    c = _ctl()
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert settings_window.lit_keys(c._estado)["f13"] == "cancel"
    c.close()


# ---------- Finding 1 (CRITICAL): the delay value now gets read ----------

def test_delay_value_follows_state_after_set_delay():
    # The structural requirement of the brief: the displayed text has to
    # follow _estado["dictation"]["delay_ms"], not just the slider knob.
    c = _ctl()
    c.set_delay_(600)
    assert c._delay_valor.stringValue() == "600 ms"
    assert c._estado["dictation"]["delay_ms"] == 600
    c.close()


def test_delay_value_also_follows_automatic_jump():
    # apply_capture_ can also change delay_ms (delay_for jumps to the
    # default with a key that needs a guard) without going through set_delay_:
    # the value has to stay in sync through that path too.
    c = _ctl()
    c.begin_capture_("dictation")
    c.apply_capture_(["cmd_l"])
    assert c._delay_valor.stringValue() == f"{shortcuts.DEFAULT_DELAY_MS} ms"
    assert c._estado["dictation"]["delay_ms"] == shortcuts.DEFAULT_DELAY_MS
    c.close()


def test_las_marcas_del_delay_son_0_200_400_600_800():
    c = _ctl()
    textos = [m.stringValue() for m in c._delay_ticks]
    assert textos == ["0", "200", "400", "600", "800 ms"]
    c.close()


def test_delay_marks_are_aligned_with_slider_left_to_right():
    # Not an eyeballed spread: each tick lives at the knob's real position
    # for its value (_marca_x), so they have to come out in increasing order.
    c = _ctl()
    xs = [m.frame().origin.x for m in c._delay_ticks]
    assert xs == sorted(xs)
    assert len(set(xs)) == len(xs)
    c.close()


def test_no_new_delay_field_is_smaller_than_its_text():
    # The same lesson that already burned _lado_ancho(): a field sized by
    # eye gets clipped in silence while stringValue() keeps returning the
    # full text. No hardcoded pixel constants: we compare
    # against theme.text_width() with each field's real font.
    c = _ctl()
    for campo in [*c._delay_ticks, c._delay_valor]:
        necesita = theme.text_width(campo.stringValue(), campo.font())
        assert campo.frame().size.width >= necesita, campo.stringValue()
    c.close()


# ---------- Finding 2 (Important): real capture with a double ----------

def test_filaclicked_builds_row_and_calls_double_begin_capture():
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.filaClicked_(c._fila_boton["latch"])
    assert c._capturing == "latch"
    assert hk.capturas == 1
    c.close()


def test_on_captured_with_valid_combo_applies_to_state(monkeypatch):
    # callAfter is replaced by a spy that DOES run the function (so the
    # effect can be checked), but synchronously: in the test there is no
    # real run loop waiting on the other side.
    monkeypatch.setattr(AppHelper, "callAfter", lambda fn, *a, **kw: fn(*a, **kw))
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.begin_capture_("cancel")
    c._on_captured_(["f13"])
    assert c._estado["cancel"]["keys"] == ["f13"]
    assert c._capturing is None
    c.close()


def test_on_captured_with_esc_cancels_without_touching_state(monkeypatch):
    monkeypatch.setattr(AppHelper, "callAfter", lambda fn, *a, **kw: fn(*a, **kw))
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.begin_capture_("dictation")
    c._on_captured_(["esc"])
    assert c._capturing is None
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    assert hk.canceladas == 1  # cancel_capture_ called the double's end_capture()
    c.close()


def test_on_captured_never_touches_appkit_directly_uses_callafter(monkeypatch):
    # The MOST important invariant of Finding 2: _on_captured_ arrives on
    # the pynput listener thread, and touching AppKit there directly is the
    # usual SIGTRAP/EXC_BREAKPOINT. Here the spy does NOT run the function
    # it is handed -it only records it-, so if _on_captured_ mutated the
    # state or AppKit through any path other than callAfter, this test
    # would see it: the state would have to remain intact.
    llamadas = []
    monkeypatch.setattr(
        AppHelper, "callAfter",
        lambda fn, *a, **kw: llamadas.append((fn, a, kw)))
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.begin_capture_("cancel")
    c._on_captured_(["f13"])

    assert len(llamadas) == 1, "_on_captured_ no pasó (una sola vez) por AppHelper.callAfter"
    fn, args, _kwargs = llamadas[0]
    assert fn == c.apply_capture_
    assert list(args[0]) == ["f13"]
    # Since the spy did not run the deferred function, nothing should have
    # changed yet.
    assert c._estado["cancel"]["keys"] == ["esc"]
    assert c._capturing == "cancel"
    c.close()


# ---------- Finding 3 (Minor): the error field, with real breathing room ----------

def _peor_caso_error(font):
    """The widest message that can end up in _error_text, checking BOTH
    validators -shortcuts.validate AND keys.validate_custom(), not just the
    first one: that was exactly the defect that left the field on the edge-
    over key names actually reachable by a single-key capture: the letters
    and digits reported by pynput.keyboard.KeyCode.char, and the entire
    pynput.keyboard.Key catalog (the "media_volume_..." ones are precisely
    the "from the pynput enum" case the review mentions)."""
    nombres = set("abcdefghijklmnopqrstuvwxyz0123456789")
    nombres |= {k.name for k in Key}
    nombres |= {"ctrl", "alt", "cmd", "shift"}  # side-less modifiers

    mensajes = set()
    for nombre in nombres:
        _, msg = keys.validate_custom(nombre)
        if msg:
            mensajes.add(msg)

    estado = {sid: {"keys": list(sc.default)} for sid, sc in shortcuts.SHORTCUTS.items()}
    for sid in shortcuts.SHORTCUTS:
        for otro_sid, fila in estado.items():
            if otro_sid == sid:
                continue
            _, msg = shortcuts.validate(sid, list(fila["keys"]), estado)
            if msg:
                mensajes.add(msg)
    _, msg = shortcuts.validate("dictation", [], estado)
    mensajes.add(msg)
    _, msg = shortcuts.validate("dictation", ["f5"], estado)
    mensajes.add(msg)

    return max(mensajes, key=lambda m: theme.text_width(m, font))


def _alto_necesario(texto, font, ancho):
    """Real height (via AppKit) that `texto` needs to avoid clipping when
    wrapped at `ancho` points with `font` -the same API a multiline
    NSTextField would use to do real layout, not an eyeballed division of
    theme.text_width() by the field width."""
    rect = NSString.stringWithString_(texto).boundingRectWithSize_options_attributes_(
        NSMakeSize(ancho, 1_000_000.0),
        NSStringDrawingUsesLineFragmentOrigin,
        {NSFontAttributeName: font})
    return rect.size.height


def test_error_field_can_span_two_lines():
    c = _ctl()
    assert c._error.cell().wraps()
    assert not c._error.usesSingleLineMode()
    c.close()


def test_error_field_does_not_clip_worst_case_of_both_validators():
    c = _ctl()
    peor = _peor_caso_error(c._error.font())
    necesita = _alto_necesario(peor, c._error.font(), c._error.frame().size.width)
    assert c._error.frame().size.height >= necesita, peor
    c.close()
