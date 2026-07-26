"""Capturing keys for the Shortcuts window, without a second listener.

Two listeners make pynput call TIS/TSM from two threads and HIToolbox aborts
the process with SIGABRT, so capture is served by the listener that is
already running: while capturing, _on_press diverts everything to the
callback and fires NO action at all. If it kept dictating while the user
picks a key, choosing the right ⌘ would start a recording mid-setup.

The captured name is the same one _norm() will report at runtime. That is
what makes the chosen key actually match: configuring "cmd_l" by hand never
matched, because pynput reports "cmd" (see the header of hotkey.py).
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


def test_while_capturing_key_name_arrives():
    visto = []
    hk = _mk()
    hk.begin_capture(visto.append)
    hk._on_press(keyboard.Key.f13)
    assert visto == [["f13"]]


def test_while_capturing_combo_arrives_whole_and_in_order():
    visto = []
    hk = _mk()
    hk.begin_capture(visto.append)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("p"))
    assert visto[-1] == ["ctrl", "shift", "p"]


def test_capturing_dictation_key_does_not_start_recording():
    # The case that makes capture mandatory: choosing the right ⌘ cannot
    # start recording mid-setup.
    started = threading.Event()
    hk = _mk(on_start=started.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.cmd_r)
    time.sleep(DELAY * 3)
    assert not started.is_set(), "capturando arrancó una grabación"


def test_capturing_esc_does_not_cancel_dictation():
    fired = threading.Event()
    hk = _mk(on_cancel=fired.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.esc)
    time.sleep(DELAY * 3)
    assert not fired.is_set()


def test_capturing_cycle_combo_does_not_cycle():
    fired = threading.Event()
    hk = _mk(on_cycle=fired.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode.from_char("m"))
    time.sleep(DELAY * 3)
    assert not fired.is_set(), "el combo disparó durante la captura"


def test_end_capture_restores_normal_behavior():
    started = threading.Event()
    hk = _mk(on_start=started.set)
    hk.begin_capture(lambda names: None)
    hk.end_capture()
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0), "tras end_capture la tecla de dictado no arrancó"


def test_end_capture_is_idempotent():
    # Closing the window mid-capture calls end_capture(); calling it again
    # must neither blow up nor leave the listener mute.
    hk = _mk()
    hk.begin_capture(lambda names: None)
    hk.end_capture()
    hk.end_capture()
    assert hk.capturing is False


def test_capturing_reflects_state():
    hk = _mk()
    assert hk.capturing is False
    hk.begin_capture(lambda names: None)
    assert hk.capturing is True
    hk.end_capture()
    assert hk.capturing is False


def test_a_crashing_callback_does_not_leave_listener_dead():
    # The callback is AppKit code. If it raises, the app cannot be left
    # without hotkeys forever.
    hk = _mk()

    def explota(names):
        raise RuntimeError("boom")

    hk.begin_capture(explota)
    hk._on_press(keyboard.Key.f13)     # must not propagate
    hk.end_capture()
    assert hk.capturing is False


def test_releasing_keys_during_capture_fires_nothing():
    stopped = threading.Event()
    hk = _mk(on_stop=stopped.set)
    hk.begin_capture(lambda names: None)
    hk._on_press(keyboard.Key.cmd_r)
    hk._on_release(keyboard.Key.cmd_r)
    time.sleep(DELAY * 3)
    assert not stopped.is_set()


def test_begin_capture_for_an_ongoing_recording():
    # begin_capture() arms the Shortcuts window capture by simply clearing
    # _started to False. If a real recording is running (on_start was
    # already called), _on_press/_on_release will be swallowing every event
    # while capturing, so neither Esc nor the dictation key itself will
    # ever be able to close it: the mic stays open forever. begin_capture()
    # has to release it with on_stop() before sweeping the flags, just like
    # releasing the key under normal circumstances.
    started = threading.Event()
    stopped = threading.Event()
    hk = _mk(on_start=started.set, on_stop=stopped.set, toggle_guard=False)
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0), "el dictado no arrancó de verdad"
    hk.begin_capture(lambda names: None)
    assert stopped.wait(1.0), "begin_capture() dejó la grabación huérfana"


def test_begin_capture_for_a_latched_recording():
    # The latch exists precisely for this: releasing the dictation key and
    # doing something else -like opening the Shortcuts window- while still
    # recording. If begin_capture() merely sets _latched to False, that
    # latched recording is orphaned exactly like the one in the test above,
    # except no one even sees it "running" because the key was already
    # released.
    started = threading.Event()
    latched = threading.Event()
    stopped = threading.Event()
    hk = _mk(on_start=started.set, on_latch=latched.set, on_stop=stopped.set, toggle_guard=False)
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(1.0), "el dictado no arrancó de verdad"
    hk._on_press(keyboard.Key.shift)
    assert latched.wait(1.0), "el latch no se fijó"
    hk.begin_capture(lambda names: None)
    assert stopped.wait(1.0), "begin_capture() dejó la grabación fijada huérfana"


def test_begin_capture_without_recording_does_not_fire_stop():
    # Negative case: with no dictation in progress, begin_capture() must not
    # call on_stop(). Without this test, a lazy fix that blindly fired
    # on_stop() on every begin_capture() would still pass the two tests
    # above while stopping dictations that never started.
    stopped = threading.Event()
    hk = _mk(on_stop=stopped.set)
    hk.begin_capture(lambda names: None)
    assert not stopped.wait(DELAY * 3), "begin_capture() disparó on_stop() sin grabación en curso"
