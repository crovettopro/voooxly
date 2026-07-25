"""Latch (hold mode): Shift WITHOUT releasing the dictation key latches the
recording; releasing no longer cuts it and a later tap ends it. The autorepeat
of a key held down after the tap must not restart anything, and Esc undoes the
latch.
"""
import threading
import time

from pynput import keyboard

from voooxly.hotkey import HotkeyManager


def _mk(on_start, on_stop, on_latch=None, on_cancel=None):
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start,
        on_stop=on_stop,
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=on_cancel or (lambda: None),
        latch_keys=["shift"],
        on_latch=on_latch or (lambda: None),
    )


def test_latch_pins_and_release_does_not_stop():
    started, stopped, latched = threading.Event(), threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set, latched.set)
    hk._on_press(keyboard.Key.cmd_r)          # hold
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.shift)          # latch without releasing
    assert latched.wait(2.0)
    hk._on_release(keyboard.Key.shift)
    hk._on_release(keyboard.Key.cmd_r)        # release: still recording
    time.sleep(0.15)
    assert not stopped.is_set(), "el latch no evitó el stop al soltar"


def test_tap_after_latch_ends_once():
    stops = 0
    done = threading.Event()

    def on_stop():
        nonlocal stops
        stops += 1
        done.set()

    starts = []
    hk = _mk(lambda: starts.append(1), on_stop)
    hk._on_press(keyboard.Key.cmd_r)
    hk._on_press(keyboard.Key.shift)
    hk._on_release(keyboard.Key.shift)
    hk._on_release(keyboard.Key.cmd_r)
    # tap to finish… but the user keeps the key held down
    hk._on_press(keyboard.Key.cmd_r)
    assert done.wait(2.0)
    hk._on_press(keyboard.Key.cmd_r)          # autorepeat
    hk._on_press(keyboard.Key.cmd_r)
    time.sleep(0.15)
    assert stops == 1, f"el tap paró {stops} veces"
    assert len(starts) == 1, "el autorepeat tras el tap rearrancó la grabación"
    hk._on_release(keyboard.Key.cmd_r)
    time.sleep(0.15)
    assert stops == 1, "la release del tap disparó otro stop"


def test_right_shift_also_pins():
    latched = threading.Event()
    hk = _mk(lambda: None, lambda: None, latched.set)
    hk._on_press(keyboard.Key.cmd_r)
    hk._on_press(keyboard.Key.shift_r)
    assert latched.wait(2.0)


def test_without_holding_shift_pins_nothing():
    latched = threading.Event()
    hk = _mk(lambda: None, lambda: None, latched.set)
    hk._on_press(keyboard.Key.shift)          # stray shift, no dictation
    time.sleep(0.15)
    assert not latched.is_set()


def test_esc_undoes_latch():
    canceled = threading.Event()
    started = []
    hk = _mk(lambda: started.append(1), lambda: None, on_cancel=canceled.set)
    hk._on_press(keyboard.Key.cmd_r)
    hk._on_press(keyboard.Key.shift)
    hk._on_release(keyboard.Key.shift)
    hk._on_release(keyboard.Key.cmd_r)
    hk._on_press(keyboard.Key.esc)            # cancels the latched dictation
    assert canceled.wait(2.0)
    hk._on_release(keyboard.Key.esc)
    # the next press STARTS again (it does not "finish" a phantom latch)
    hk._on_press(keyboard.Key.cmd_r)
    time.sleep(0.15)
    assert len(started) == 2, "tras Esc, la tecla de dictado no volvió a arrancar"


def test_flujo_hold_normal_sigue_intacto():
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0)
    hk._on_release(keyboard.Key.cmd_r)
    assert stopped.wait(2.0)
