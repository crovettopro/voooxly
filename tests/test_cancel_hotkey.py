"""Esc must fire on_cancel exactly once per press (no autorepeat)
and without interfering with the dictation key in hold mode."""
import threading

from pynput import keyboard

from voooxly.hotkey import HotkeyManager


def _mk(on_cancel, on_start=None, on_stop=None):
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start or (lambda: None),
        on_stop=on_stop or (lambda: None),
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=on_cancel,
    )


def test_esc_fires_cancel():
    fired = threading.Event()
    hk = _mk(on_cancel=fired.set)
    hk._on_press(keyboard.Key.esc)
    assert fired.wait(2.0), "Esc no disparó on_cancel"


def test_esc_autorepeat_fires_once():
    count = 0
    done = threading.Event()

    def cb():
        nonlocal count
        count += 1
        done.set()

    hk = _mk(on_cancel=cb)
    hk._on_press(keyboard.Key.esc)   # real press
    assert done.wait(2.0)
    hk._on_press(keyboard.Key.esc)   # autorepeat: the key is still in _pressed
    hk._on_press(keyboard.Key.esc)
    # give spurious threads some slack before counting
    import time

    time.sleep(0.15)
    assert count == 1, f"autorepeat re-disparó el cancel ({count} veces)"


def test_esc_while_holding_dictation_key():
    """Canceling while cmd_r is held: cancel fires and the dictation
    key keeps working on the next press."""
    started = threading.Event()
    canceled = threading.Event()
    hk = _mk(on_cancel=canceled.set, on_start=started.set)

    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.esc)
    assert canceled.wait(2.0)
    # release both and verify that a new press starts again
    hk._on_release(keyboard.Key.esc)
    hk._on_release(keyboard.Key.cmd_r)
    started.clear()
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0), "la tecla de dictado quedó rota tras cancelar"


def test_no_cancel_key_configured():
    """Without cancel_keys the listener must not break on Esc."""
    hk = HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_cycle=lambda: None,
    )
    hk._on_press(keyboard.Key.esc)  # must not raise


def _mk_combo(on_cancel, on_start=None):
    """Cancel as a COMBO (ctrl+shift+x), not a single key: the original bug
    was that only the first key was matched and the combo never canceled."""
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start or (lambda: None),
        on_stop=lambda: None,
        on_cycle=lambda: None,
        cancel_keys=["ctrl", "shift", "x"],
        on_cancel=on_cancel,
    )


def test_combo_de_cancel_dispara_al_pulsar_las_tres():
    fired = threading.Event()
    hk = _mk_combo(on_cancel=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    # Ctrl+X arrives as a control char (\x18), just like Ctrl+M arrives as \r.
    hk._on_press(keyboard.KeyCode(char="\x18", vk=7))
    assert fired.wait(2.0), "ctrl+shift+x no disparó on_cancel"


def test_cancel_combo_does_not_fire_with_only_first_key():
    """The first key of the combo (ctrl) alone does NOT cancel: it used to,
    because cancel only looked at the first key, firing on any stray
    ctrl. Now it requires the full set."""
    fired = threading.Event()
    hk = _mk_combo(on_cancel=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    assert not fired.wait(0.3), "ctrl solo no debería cancelar"


def test_combo_de_cancel_se_reconfigura_desde_rebind():
    """rebind("cancel", combo) sets _cancel_combo and clears _cancel_key, so a
    combo rebound at runtime cancels with the full set and not with the
    first stray key."""
    fired = threading.Event()
    hk = _mk_combo(on_cancel=fired.set)
    # Rebind to another combo and check that the new one (not the old) fires.
    assert hk.rebind("cancel", ["ctrl", "shift", "c"])
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode(char="\x03", vk=8))  # Ctrl+C = \x03
    assert fired.wait(2.0), "el combo reasignado no canceló"


def _mk_combo_hold(on_cancel, on_start=None, on_latch=None):
    """Cancel as a COMBO while the dictation key is HELD down (hold mode).
    Reproduces the user's real configuration: dictation=cmd_r in hold,
    cancel=ctrl+shift, latch=shift. The bug: in hold the dictation key is
    still pressed when canceling, so the combo snapshot included cmd_r and
    the cancel never matched — the text got pasted anyway."""
    return HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start or (lambda: None),
        on_stop=lambda: None,
        on_cycle=lambda: None,
        cancel_keys=["ctrl", "shift"],
        on_cancel=on_cancel,
        latch_keys=["shift"],
        on_latch=on_latch or (lambda: None),
    )


def test_cancel_combo_while_dictation_key_is_held():
    """The bug case: dictating with cmd_r held, you press ctrl+shift to
    cancel and the dictation is canceled (nothing gets pasted). Before, the
    snapshot {cmd_r,ctrl,shift} != {ctrl,shift} and cancel never fired."""
    started = threading.Event()
    canceled = threading.Event()
    hk = _mk_combo_hold(on_cancel=canceled.set, on_start=started.set)
    hk._on_press(keyboard.Key.cmd_r)   # hold: recording starts
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)   # cancel WITHOUT releasing cmd_r
    assert canceled.wait(2.0), "ctrl+shift no canceló mientras se mantenía cmd_r"


def test_combo_cancel_no_lo_dispara_un_modificador_del_combo_solo():
    """Pressing ctrl (one key of the combo) alone, while holding cmd_r, does
    NOT cancel: the full set is required."""
    started = threading.Event()
    canceled = threading.Event()
    hk = _mk_combo_hold(on_cancel=canceled.set, on_start=started.set)
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.ctrl)
    assert not canceled.wait(0.3), "ctrl solo canceló sin formar el combo"


def test_latch_no_se_dispara_si_hay_un_modificador_de_combo_pulsado():
    """Latch (shift) must only latch if shift comes alone with the dictation key.
    If ctrl is also pressed (you are building ctrl+shift to cancel), shift does
    NOT latch — the combo goes to cancel, not latch. Without this guard, the
    latch ate the second key of the combo and the cancel never got to match."""
    started = threading.Event()
    latched = threading.Event()
    canceled = threading.Event()
    hk = _mk_combo_hold(
        on_cancel=canceled.set, on_start=started.set, on_latch=latched.set
    )
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    assert canceled.wait(2.0), "el combo no canceló porque el latch lo interceptó"
    assert not latched.is_set(), "shift con ctrl pulsado fijó el latch en vez de cancelar"
