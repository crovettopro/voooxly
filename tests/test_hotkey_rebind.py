"""Changing the shortcuts that are NOT the dictation one, on the fly.

Until now cycle/latch/cancel were set in the constructor and only moved by
editing config.yaml. The Shortcuts window changes them with the listener
already running, so rebind() has to apply without recreating anything:
recreating the listener is what kills the app (two listeners → SIGABRT in
HIToolbox).
"""
import threading
import time

from pynput import keyboard

from voooxly.hotkey import HotkeyManager

DELAY = 0.05


def _mk(**cbs):
    base = dict(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=lambda: None,
        latch_keys=["shift"],
        on_latch=lambda: None,
        toggle_guard=False,
        guard_delay=DELAY,
    )
    base.update(cbs)
    return HotkeyManager(**base)


def test_rebind_cambia_el_combo_de_cycle():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    assert hk.rebind("cycle_mode", ["ctrl", "shift", "p"]) is True
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("p"))
    assert fired.wait(1.0), "el combo nuevo no disparó"


def test_rebind_leaves_old_combo_dead():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk.rebind("cycle_mode", ["ctrl", "shift", "p"])
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("m"))
    time.sleep(DELAY * 3)
    assert not fired.is_set(), "el combo viejo seguía vivo"


def test_rebind_changes_cancel_key():
    fired = threading.Event()
    hk = _mk(on_cancel=fired.set)
    assert hk.rebind("cancel", ["f13"]) is True
    hk._on_press(keyboard.Key.f13)
    assert fired.wait(1.0)


def test_rebind_changes_latch_key():
    started, latched = threading.Event(), threading.Event()
    hk = _mk(on_start=started.set, on_latch=latched.set)
    assert hk.rebind("latch", ["f14"]) is True
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0)
    hk._on_press(keyboard.Key.f14)
    assert latched.wait(1.0)


def test_rebind_rejects_dictation_key():
    # If latch becomes the dictation key, the latch goes dead: the hold
    # branch returns before reaching it. It is the usual silent failure.
    hk = _mk()
    assert hk.rebind("latch", ["cmd_r"]) is False


def test_rebind_rejects_unknown_id():
    hk = _mk()
    assert hk.rebind("dictation", ["f13"]) is False


def test_reconfigure_changes_delay_live():
    # The window's slider: lowering the delay has to take effect without restarting.
    started = threading.Event()
    hk = _mk(on_start=started.set, toggle_guard=True)
    hk.reconfigure(toggle_key="cmd_r", toggle_mode="hold", guard=True, guard_delay=0.01)
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0)
    assert hk._guard_delay == 0.01


def test_reconfigure_sin_delay_conserva_el_actual():
    hk = _mk()
    hk.reconfigure(toggle_key="cmd_r", toggle_mode="hold", guard=False)
    assert hk._guard_delay == DELAY
