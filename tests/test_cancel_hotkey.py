"""Esc debe disparar on_cancel una sola vez por pulsación (sin autorepeat)
y sin interferir con la tecla de dictado en modo hold."""
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
    hk._on_press(keyboard.Key.esc)   # pulsación real
    assert done.wait(2.0)
    hk._on_press(keyboard.Key.esc)   # autorepeat: la tecla sigue en _pressed
    hk._on_press(keyboard.Key.esc)
    # dar margen a hilos espurios antes de contar
    import time

    time.sleep(0.15)
    assert count == 1, f"autorepeat re-disparó el cancel ({count} veces)"


def test_esc_while_holding_dictation_key():
    """Cancelar mientras se mantiene cmd_r: cancel se dispara y la tecla
    de dictado sigue funcionando en la siguiente pulsación."""
    started = threading.Event()
    canceled = threading.Event()
    hk = _mk(on_cancel=canceled.set, on_start=started.set)

    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.esc)
    assert canceled.wait(2.0)
    # soltar ambas y verificar que una nueva pulsación vuelve a arrancar
    hk._on_release(keyboard.Key.esc)
    hk._on_release(keyboard.Key.cmd_r)
    started.clear()
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0), "la tecla de dictado quedó rota tras cancelar"


def test_no_cancel_key_configured():
    """Sin cancel_keys el listener no debe romperse con Esc."""
    hk = HotkeyManager(
        toggle_mode="hold",
        toggle_keys=["cmd_r"],
        cycle_keys=["ctrl", "shift", "m"],
        on_toggle=lambda: None,
        on_start=lambda: None,
        on_stop=lambda: None,
        on_cycle=lambda: None,
    )
    hk._on_press(keyboard.Key.esc)  # no debe lanzar


def _mk_combo(on_cancel, on_start=None):
    """Cancel como COMBO (ctrl+shift+x), no tecla suelta: el bug original era
    que solo se casaba la primera tecla y el combo no cancelaba nunca."""
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
    # Ctrl+X llega como control char (\x18), como Ctrl+M llega como \r.
    hk._on_press(keyboard.KeyCode(char="\x18", vk=7))
    assert fired.wait(2.0), "ctrl+shift+x no disparó on_cancel"


def test_combo_de_cancel_no_dispara_con_solo_la_primera_tecla():
    """La primera tecla del combo (ctrl) sola NO cancela: antes sí lo hacía
    porque el cancel solo miraba la primera tecla, disparándose en cualquier
    ctrl suelto. Ahora exige el conjunto completo."""
    fired = threading.Event()
    hk = _mk_combo(on_cancel=fired.set)
    hk._on_press(keyboard.Key.ctrl)
    assert not fired.wait(0.3), "ctrl solo no debería cancelar"


def test_combo_de_cancel_se_reconfigura_desde_rebind():
    """rebind("cancel", combo) deja _cancel_combo y quita _cancel_key, así un
    combo reasignado en runtime cancela con el conjunto completo y no con la
    primera tecla suelta."""
    fired = threading.Event()
    hk = _mk_combo(on_cancel=fired.set)
    # Reasignar a otro combo y comprobar que el nuevo (no el viejo) dispara.
    assert hk.rebind("cancel", ["ctrl", "shift", "c"])
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)
    hk._on_press(keyboard.KeyCode(char="\x03", vk=8))  # Ctrl+C = \x03
    assert fired.wait(2.0), "el combo reasignado no canceló"


def _mk_combo_hold(on_cancel, on_start=None, on_latch=None):
    """Cancel como COMBO mientras se MANTIENE pulsada la tecla de dictado
    (modo hold). Reproduce la configuración real del usuario: dictation=cmd_r
    en hold, cancel=ctrl+shift, latch=shift. El bug: en hold la tecla de
    dictado sigue pulsada al cancelar, así que el snapshot del combo incluía
    cmd_r y el cancel jamás casaba — el texto se pegaba igual."""
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


def test_combo_cancel_mientras_se_mantiene_la_tecla_de_dictado():
    """El caso del bug: dictando con cmd_r pulsada, presionas ctrl+shift para
    cancelar y el dictado se cancela (no se pega nada). Antes el snapshot
    {cmd_r,ctrl,shift} != {ctrl,shift} y el cancel nunca disparaba."""
    started = threading.Event()
    canceled = threading.Event()
    hk = _mk_combo_hold(on_cancel=canceled.set, on_start=started.set)
    hk._on_press(keyboard.Key.cmd_r)   # mantener: empieza a grabar
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.ctrl)
    hk._on_press(keyboard.Key.shift)   # cancel SIN soltar cmd_r
    assert canceled.wait(2.0), "ctrl+shift no canceló mientras se mantenía cmd_r"


def test_combo_cancel_no_lo_dispara_un_modificador_del_combo_solo():
    """Presionar ctrl (una tecla del combo) solo, manteniendo cmd_r, NO cancela:
    exige el conjunto completo."""
    started = threading.Event()
    canceled = threading.Event()
    hk = _mk_combo_hold(on_cancel=canceled.set, on_start=started.set)
    hk._on_press(keyboard.Key.cmd_r)
    assert started.wait(2.0)
    hk._on_press(keyboard.Key.ctrl)
    assert not canceled.wait(0.3), "ctrl solo canceló sin formar el combo"


def test_latch_no_se_dispara_si_hay_un_modificador_de_combo_pulsado():
    """Latch (shift) solo debe fijar si shift va solo con la tecla de dictado.
    Si ctrl también está pulsado (estás armando ctrl+shift para cancelar), shift
    NO fija — el combo va a cancel, no a latch. Sin este guardia, el latch se
    comía la segunda tecla del combo y el cancel nunca llegaba a casar."""
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
