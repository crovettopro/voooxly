"""The decision window that makes a left modifier usable.

In hold mode, _on_press fires on_start() as soon as the key goes down. With
the left ⌘ as dictation key, that means every ⌘C, ⌘V and ⌘Tab starts a
recording: the app becomes unusable and the user has no idea why.

With the guard, recording only starts if you hold the key ALONE for the
window. Any other key within that span cancels it and lets the combo through
untouched.

The tests use a short guard_delay to avoid real sleeping; the logic is the
same.
"""
import threading
import time

from pynput import keyboard

from voooxly.hotkey import HotkeyManager

DELAY = 0.05


def _mk(on_start, on_stop, guard=True, on_latch=None, on_cancel=None, toggle_mode="hold"):
    return HotkeyManager(
        toggle_mode=toggle_mode,
        toggle_keys=["cmd_l"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=on_start,
        on_stop=on_stop,
        on_cycle=lambda: None,
        cancel_keys=["esc"],
        on_cancel=on_cancel or (lambda: None),
        latch_keys=["shift"],
        on_latch=on_latch or (lambda: None),
        toggle_guard=guard,
        guard_delay=DELAY,
    )


def test_mantener_la_tecla_sola_acaba_grabando():
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(2.0), "la guarda nunca dejó arrancar la grabación"


def test_does_not_record_before_window_expires():
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.cmd_l)
    assert not started.is_set(), "arrancó al instante: la guarda no se aplicó"


def test_a_combo_inside_window_does_not_record():
    # ⌘C: the case that makes the app unusable without the guard.
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_press(keyboard.KeyCode.from_char("c"))
    time.sleep(DELAY * 4)
    assert not started.is_set(), "un ⌘C arrancó una grabación"


def test_releasing_inside_window_does_not_record_or_stop():
    # A stray tap of the modifier: it neither records nor can it fire an
    # on_stop for a recording that never started.
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_release(keyboard.Key.cmd_l)
    time.sleep(DELAY * 4)
    assert not started.is_set()
    assert not stopped.is_set(), "paró una grabación que nunca arrancó"


def test_full_cycle_with_guard_records_and_stops():
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(2.0)
    hk._on_release(keyboard.Key.cmd_l)
    assert stopped.wait(2.0)


def test_el_latch_sigue_funcionando_con_guarda():
    started, latched = threading.Event(), threading.Event()
    hk = _mk(started.set, lambda: None, on_latch=latched.set)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(2.0)            # wait for the window to expire
    hk._on_press(keyboard.Key.shift)
    assert latched.wait(2.0)


def test_el_shift_dentro_de_la_ventana_cancela_en_vez_de_fijar():
    # You cannot latch a recording that has not started yet.
    started, latched = threading.Event(), threading.Event()
    hk = _mk(started.set, lambda: None, on_latch=latched.set)
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_press(keyboard.Key.shift)
    time.sleep(DELAY * 4)
    assert not latched.is_set()
    assert not started.is_set()


def test_un_tecleo_rapido_no_dispara_la_ventana_de_una_pulsacion_vieja():
    # The generation counter: without it, the timer of an already-released
    # press fires late and starts a phantom recording.
    starts = []
    hk = _mk(lambda: starts.append(1), lambda: None)
    for _ in range(5):
        hk._on_press(keyboard.Key.cmd_l)
        hk._on_release(keyboard.Key.cmd_l)
    time.sleep(DELAY * 6)
    assert starts == [], f"pulsaciones fantasma: {len(starts)}"


def test_without_guard_start_waits_for_no_window():
    # The path already in production does not change: zero regression. wait()
    # is used instead of is_set() because on_start runs in its own thread —
    # with is_set() the test would fail now and then due to a race, not a bug.
    started = threading.Event()
    hk = _mk(started.set, lambda: None, guard=False)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(1.0), "la tecla sin guarda ya no arranca"


def test_without_guard_another_key_does_not_cancel_recording():
    # Canceling mid-dictation throws away already-recorded audio. That is only
    # acceptable INSIDE the window, and without the guard there is no window.
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set, guard=False)
    hk._on_press(keyboard.Key.cmd_l)
    assert started.wait(1.0)
    hk._on_press(keyboard.KeyCode.from_char("c"))
    time.sleep(DELAY * 4)
    assert not stopped.is_set(), "una tecla suelta mató un dictado en curso"


def test_reconfigure_changes_key_and_saves_it_live():
    # This is what the Settings menu uses: switching keys without restarting the app.
    started = threading.Event()
    hk = _mk(started.set, lambda: None, guard=True)
    hk.reconfigure(toggle_key="f13", toggle_mode="hold", guard=False)
    hk._on_press(keyboard.Key.f13)
    assert started.wait(1.0), "la tecla nueva no arrancó"


def test_reconfigure_to_toggle_mode_rebuilds_combo():
    # In toggle mode the key is detected as a one-key combo, not as a hold.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None)
    hk.on_toggle = toggled.set
    hk.reconfigure(toggle_key="f13", toggle_mode="toggle", guard=False)
    hk._on_press(keyboard.Key.f13)
    assert toggled.wait(1.0), "el modo toggle no disparó con la tecla nueva"


# --- Fix 1 (Critical): the guard also protects the toggle ------------------
#
# Before this fix, _on_press only consulted self._guard inside the
# `toggle_mode == "hold"` branch. In toggle mode the dictation key went
# through _toggle_combo and fired on_toggle() instantly, never passing
# through the decision window — even though keys.needs_guard() still returned
# True and the menu still advertised "300 ms delay". With Dictation key =
# Left ⌘ and Dictation style = "Press to start / stop", any ⌘C/⌘V/⌘S started
# a recording that only stopped by tapping ⌘ alone again — two menu settings,
# each valid on its own, catastrophic together. These tests prove that the
# guard, once armed, fires on_toggle() instead of on_start() when
# toggle_mode != "hold", with the same cancellation rules as in hold.


def test_toggle_con_guarda_no_dispara_al_instante():
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    assert not toggled.is_set(), "el toggle disparó al instante: la guarda no se aplicó"


def test_toggle_with_guard_fires_after_holding_window():
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    assert toggled.wait(2.0), "la guarda nunca dejó pasar el toggle"


def test_toggle_with_guard_a_combo_does_not_fire_toggle():
    # The live-tested scenario from the report: Dictation key = Left ⌘ +
    # "Press to start / stop" style. Without the guard applied to the toggle,
    # a ⌘C fired on_toggle and started a recording that never stopped by itself.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_press(keyboard.KeyCode.from_char("c"))
    time.sleep(DELAY * 4)
    assert not toggled.is_set(), "un ⌘C disparó el toggle"


def test_toggle_with_guard_releasing_inside_window_does_not_fire():
    # Same as in hold: releasing before the window expires cancels the
    # attempt. Without this toggle-specific cancel, the already-armed timer
    # would stay alive and belatedly fire a phantom toggle after release.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    hk._on_release(keyboard.Key.cmd_l)
    time.sleep(DELAY * 4)
    assert not toggled.is_set(), "soltar dentro de la ventana disparó el toggle"


def test_toggle_sin_guarda_sigue_disparando_al_instante():
    # Zero regression for the guard-free catalog keys (cmd_r, alt_r,
    # ctrl_r, F6/F13-15): that path is already in production and must not change.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, guard=False, toggle_mode="toggle")
    hk.on_toggle = toggled.set
    hk._on_press(keyboard.Key.cmd_l)
    assert toggled.wait(1.0), "una tecla sin guarda ya no dispara el toggle al instante"


def test_reconfigure_to_toggle_with_guard_applies_window():
    # The real Settings path: changing key/style on the fly without
    # restarting the app. Before the fix, reconfigure() stored guard=True in
    # self._guard but nothing consulted it in toggle mode.
    toggled = threading.Event()
    hk = _mk(lambda: None, lambda: None, guard=False)  # starts in hold without a guard
    hk.on_toggle = toggled.set
    hk.reconfigure(toggle_key="cmd_l", toggle_mode="toggle", guard=True)
    hk._on_press(keyboard.Key.cmd_l)
    assert not toggled.is_set(), "reconfigure a toggle+guard no aplicó la ventana"
    assert toggled.wait(2.0), "tras aguantar la ventana completa, el toggle debía disparar"
