"""The fn key (🌐), Wispr Flow style: pynput DOES deliver its flagsChanged
(vk 63) but, since it is missing from its _MODIFIER_FLAGS table, `is_press`
always comes out 0 and BOTH transitions — press and release — arrive as
on_release. The manager straightens it out by asking the system whether the fn
bit is still down (_fn_down) and routing that disguised "release" to the
press. Here _fn_down is stubbed: in a test there is no physical key to press.
"""
import threading

from pynput import keyboard

from voooxly import hotkey

FN = keyboard.KeyCode.from_vk(0x3F)


def _mk(on_start, on_stop):
    return hotkey.HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["fn"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start,
        on_stop=on_stop,
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=lambda: None,
        latch_keys=["shift"],
        on_latch=lambda: None,
    )


def test_norm_recognizes_fn_keycode():
    assert hotkey._norm(FN) == "fn"


def test_holding_fn_dictates_and_releasing_stops(monkeypatch):
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    monkeypatch.setattr(hotkey, "_fn_down", lambda: True)
    hk._on_release(FN)                    # the press arrives disguised as a release
    assert started.wait(2.0), "pulsar fn no arrancó el dictado"
    assert not stopped.is_set()
    monkeypatch.setattr(hotkey, "_fn_down", lambda: False)
    hk._on_release(FN)                    # the real release
    assert stopped.wait(2.0), "soltar fn no paró el dictado"


def test_la_captura_ve_fn_como_pulsacion(monkeypatch):
    # The Shortcuts window captures through the SAME listener: fn has to
    # reach it as a pressed key or it could never be assigned.
    capturas = []
    hk = _mk(lambda: None, lambda: None)
    hk.begin_capture(capturas.append)
    monkeypatch.setattr(hotkey, "_fn_down", lambda: True)
    hk._on_release(FN)
    assert capturas and capturas[-1] == ["fn"]


def test_fn_release_without_bit_starts_nothing(monkeypatch):
    # Orphan release (the press was lost, e.g. launching the app with fn
    # already held): without the fn bit down it follows the normal release
    # path and fires no phantom start.
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    monkeypatch.setattr(hotkey, "_fn_down", lambda: False)
    hk._on_release(FN)
    assert not started.wait(0.15)
