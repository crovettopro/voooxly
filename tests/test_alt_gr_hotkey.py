"""alt_gr is, on macOS, the SAME physical key as alt_r — pynput collapses
Key.alt_gr into Key.alt_r (same virtual keycode, enum.Enum merges them into a
single member; verified against the project's pynput: `Key.alt_gr is Key.alt_r`
and `Key.alt_gr.name == "alt_r"`).

Before this fix, configuring alt_gr as the dictation key left it mute:
_canon() did not translate it, so the configured key ("alt_gr") never matched
the name the keyboard actually reports ("alt_r") and the recording never
started — no error, no log, nothing.
"""
import threading

from pynput import keyboard

from voooxly import hotkey, keys
from voooxly.hotkey import HotkeyManager


def _mk(on_start, on_stop, guard=False):
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["alt_gr"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start,
        on_stop=on_stop,
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=lambda: None,
        toggle_guard=guard,
    )


def test_configured_alt_gr_starts_with_the_key_pynput_actually_reports():
    # What the user presses is the physical AltGr/right Option key; what
    # pynput delivers to the listener is keyboard.Key.alt_r. Without the
    # translation in _canon, this press never matched "alt_gr" and nothing happened.
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.alt_r)
    assert started.wait(2.0), "alt_gr configurado no arrancó con la tecla real (alt_r)"


def test_alt_gr_stops_on_release():
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    hk._on_press(keyboard.Key.alt_r)
    assert started.wait(2.0)
    hk._on_release(keyboard.Key.alt_r)
    assert stopped.wait(2.0)


def test_hotkey_importa_el_alias_de_keys_en_vez_de_duplicarlo():
    # Fix 3: hotkey._ALIAS_MISMA_TECLA and keys._ALIAS_MISMA_TECLA were two
    # separate {"alt_gr": "alt_r"} literals that nothing kept in sync
    # — the same class of bug that once already left the dictation key mute
    # (see this file's docstring). `is` and not `==`: two equal but distinct
    # dicts could still diverge in the future; the import shares the same
    # object.
    assert hotkey._ALIAS_MISMA_TECLA is keys._ALIAS_MISMA_TECLA
