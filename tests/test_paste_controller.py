"""The pynput Controller is built ONCE, and from the main thread.

Context: Controller.__init__ queries the keyboard layout via TIS/TSM.
paste_frontmost used to build it on every paste, from the _process worker thread.
If that coincides with another thread touching TSM (the hotkey listener), HIToolbox
kills the process: SIGTRAP in dispatch_assert_queue, with no Python exception
left to catch. Real crash on 2026-07-20 17:09:08, right after a dictation.

press()/release() only use the already-cached mapping, so building it once
at startup (main thread) takes TSM out of the paste path.
"""

import pytest

from voooxly import output


class FakeController:
    """Counts constructions: each one would be a TSM query."""

    construcciones = 0

    def __init__(self):
        type(self).construcciones += 1

    def press(self, _k):
        pass

    def release(self, _k):
        pass


@pytest.fixture(autouse=True)
def controller_limpio(monkeypatch):
    import pynput.keyboard

    FakeController.construcciones = 0
    monkeypatch.setattr(pynput.keyboard, "Controller", FakeController)
    monkeypatch.setattr(output, "_kb", None)
    yield
    monkeypatch.setattr(output, "_kb", None)


def test_pasting_multiple_times_builds_controller_once():
    for _ in range(5):
        assert output.paste_frontmost() is True
    assert FakeController.construcciones == 1


def test_warmup_readies_controller_so_paste_does_not_touch_tsm():
    assert output.warmup() is True
    assert FakeController.construcciones == 1

    output.paste_frontmost()
    assert FakeController.construcciones == 1, "el pegado reconstruyó el Controller"


def test_warmup_twice_does_not_rebuild():
    output.warmup()
    output.warmup()
    assert FakeController.construcciones == 1


def test_warmup_does_not_raise_if_pynput_fails(monkeypatch):
    """A failure while warming up must not take down the app's startup."""
    import pynput.keyboard

    class Explota:
        def __init__(self):
            raise RuntimeError("sin Accesibilidad")

    monkeypatch.setattr(pynput.keyboard, "Controller", Explota)
    assert output.warmup() is False
