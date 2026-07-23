"""La tecla fn (🌐), estilo Wispr Flow: pynput SÍ entrega su flagsChanged
(vk 63) pero, al no estar en su tabla _MODIFIER_FLAGS, `is_press` sale siempre
0 y las DOS transiciones — pulsar y soltar — llegan como on_release. El manager
la endereza preguntando al sistema si el bit fn sigue bajado (_fn_down) y
enrutando esa "release" disfrazada al press. Aquí _fn_down se dobla: en un
test no hay tecla física que pulsar.
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


def test_norm_reconoce_el_keycode_de_fn():
    assert hotkey._norm(FN) == "fn"


def test_mantener_fn_dicta_y_soltarla_para(monkeypatch):
    started, stopped = threading.Event(), threading.Event()
    hk = _mk(started.set, stopped.set)
    monkeypatch.setattr(hotkey, "_fn_down", lambda: True)
    hk._on_release(FN)                    # el press llega disfrazado de release
    assert started.wait(2.0), "pulsar fn no arrancó el dictado"
    assert not stopped.is_set()
    monkeypatch.setattr(hotkey, "_fn_down", lambda: False)
    hk._on_release(FN)                    # la release de verdad
    assert stopped.wait(2.0), "soltar fn no paró el dictado"


def test_la_captura_ve_fn_como_pulsacion(monkeypatch):
    # La ventana de Shortcuts captura por el MISMO listener: fn tiene que
    # llegarle como tecla pulsada o no se podría asignar nunca.
    capturas = []
    hk = _mk(lambda: None, lambda: None)
    hk.begin_capture(capturas.append)
    monkeypatch.setattr(hotkey, "_fn_down", lambda: True)
    hk._on_release(FN)
    assert capturas and capturas[-1] == ["fn"]


def test_una_release_de_fn_sin_bit_no_arranca_nada(monkeypatch):
    # Release huérfana (el press se perdió, p.ej. arrancando la app con fn ya
    # pulsada): sin el bit fn bajado sigue el camino normal de release y no
    # dispara ningún arranque fantasma.
    started = threading.Event()
    hk = _mk(started.set, lambda: None)
    monkeypatch.setattr(hotkey, "_fn_down", lambda: False)
    hk._on_release(FN)
    assert not started.wait(0.15)
