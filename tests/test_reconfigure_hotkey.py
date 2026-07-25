"""reconfigure() cannot trust that the caller already went through
keys.resolve/validate_custom. Today that collision is avoided by
keys._RESERVADAS (shift and shift_l are both there), but that only protects
the path that goes through that gate. A task calling reconfigure() directly
from the menu skips it entirely, so reconfigure() has to defend itself.

Without this check, reconfigure(toggle_key="shift_l", ...) leaves _toggle_key
== _latch_key == "shift": shift becomes the dictation key AND the latch key
at once, the latch goes dead (the `return` of the dictation key's own hold
branch never lets execution reach the latch block) and the right shift
silently latches instead of dictating.

"Rejecting" here means returning False and leaving the previous
configuration intact — NOT raising an exception. The caller is AppKit menu
code: an uncaught exception there takes the whole app down over a badly
chosen key.
"""
import threading

from pynput import keyboard

from voooxly.hotkey import HotkeyManager


def _mk():
    return HotkeyManager(
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
    )


def test_shift_l_as_dictation_key_is_rejected_for_colliding_with_latch():
    # shift_l canonicalizes to "shift" (Key.shift_l is Key.shift on macOS),
    # which is also the default latch key.
    hk = _mk()
    ok = hk.reconfigure(toggle_key="shift_l", toggle_mode="hold", guard=True)
    assert ok is False
    assert hk._toggle_key == "cmd_r", "la colisión se aceptó y pisó la tecla anterior"


def test_esc_como_tecla_de_dictado_se_rechaza_por_colisionar_con_cancel():
    hk = _mk()
    ok = hk.reconfigure(toggle_key="esc", toggle_mode="hold", guard=False)
    assert ok is False
    assert hk._toggle_key == "cmd_r"


def test_una_tecla_sin_colision_se_acepta_normalmente():
    hk = _mk()
    ok = hk.reconfigure(toggle_key="f13", toggle_mode="hold", guard=False)
    assert ok is True
    assert hk._toggle_key == "f13"


def test_tras_un_rechazo_la_tecla_anterior_sigue_funcionando():
    # The rejection cannot leave the manager in a half-baked state: cmd_r
    # (the key in force before the rejected call) has to keep starting
    # recordings normally.
    started = threading.Event()
    hk = _mk()
    hk.on_start = started.set
    ok = hk.reconfigure(toggle_key="shift_l", toggle_mode="hold", guard=True)
    assert ok is False
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0), "tras el rechazo, la tecla anterior dejó de funcionar"
