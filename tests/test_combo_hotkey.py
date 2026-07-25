"""Ctrl+Shift+M (mode cycle) HAS to match on macOS, where pynput
delivers the letter as a control character when Ctrl is held
(Ctrl+M = '\\r'). The original bug compared raw chars and the combo
never fired.
"""
import threading

from pynput import keyboard

from voooxly.hotkey import HotkeyManager


def _mk(on_cycle=None):
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_cycle=on_cycle or (lambda: None),
        cancel_keys=["esc"],
        on_cancel=lambda: None,
    )


def test_ctrl_shift_m_con_control_char_dispara_cycle():
    """What macOS actually delivers when pressing Ctrl+Shift+M."""
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode(char="\r", vk=46))  # Ctrl+M arrives as \r
    assert fired.wait(2.0), "ctrl+shift+m no disparó el ciclo de modos"


def test_char_limpio_sigue_funcionando():
    """In case some backend delivers the letter unmapped to a control char."""
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("M"))  # uppercase because of the shift
    assert fired.wait(2.0)


def test_sin_char_cae_al_virtual_keycode():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode(vk=46))  # no char: just the M's vk
    assert fired.wait(2.0)


def test_combo_requires_all_three_keys():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.KeyCode(char="\r", vk=46))  # shift missing
    import time

    time.sleep(0.15)
    assert not fired.is_set()
