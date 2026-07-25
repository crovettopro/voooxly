"""The glue between the window and the hotkey, without instantiating VoooxlyApp.

Instantiating VoooxlyApp builds AppKit menus and does not run in a test (the
same reason keys.py, shortcuts.py and ai_menu_labels exist at module level).
We test the function that applies a shortcut against a fake hotkey, and the
function that migrates + persists prefs.json in __init__.
"""
from voooxly import app as app_mod
from voooxly.app import apply_shortcut


class _HotkeyFalso:
    def __init__(self, ok=True):
        self._ok = ok
        self.reconfigurado = None
        self.rebindeado = []
        # These watch the system rule (see test_aplicar_un_atajo_no_reinicia_el_listener
        # below): reconfigure()/rebind() may only mutate attributes, never
        # touch the running keyboard.Listener.
        self.parada = False
        self.arrancada = False

    def reconfigure(self, toggle_key, toggle_mode, guard, guard_delay=None):
        self.reconfigurado = (toggle_key, toggle_mode, guard, guard_delay)
        return self._ok

    def rebind(self, sid, names):
        self.rebindeado.append((sid, names))
        return self._ok

    def stop(self):
        self.parada = True

    def start(self):
        self.arrancada = True


def test_dictation_va_por_reconfigure_con_el_delay_en_segundos():
    hk = _HotkeyFalso()
    ok, msg = apply_shortcut(hk, "dictation", {"keys": ["cmd_l"], "style": "hold", "delay_ms": 400})
    assert ok, msg
    tecla, modo, guarda, delay = hk.reconfigurado
    assert tecla == "cmd_l"
    assert modo == "hold"
    assert guarda is True
    assert abs(delay - 0.4) < 1e-9, "el hotkey espera SEGUNDOS, la ventana da ms"


def test_delay_del_usuario_se_honra_incluso_en_tecla_sin_guarda_por_defecto():
    """Feedback point 2: with the right ⌘, needs_guard is False, so the guard
    used to be switched off and the slider's delay was IGNORED. Now a
    delay>0 enables it on any key — the delay is the user's choice."""
    hk = _HotkeyFalso()
    ok, _ = apply_shortcut(hk, "dictation", {"keys": ["cmd_r"], "style": "hold", "delay_ms": 400})
    assert ok
    tecla, modo, guarda, delay = hk.reconfigurado
    assert tecla == "cmd_r"
    assert guarda is True, "un delay>0 debe activar el guard aunque la tecla no lo necesite por diseño"
    assert abs(delay - 0.4) < 1e-9


def test_delay_cero_en_tecla_sin_guarda_deja_el_guard_apagado():
    """The right key's default is still guard-free (instant): the user keeps
    the familiar feel unless they raise the slider by hand."""
    hk = _HotkeyFalso()
    ok, _ = apply_shortcut(hk, "dictation", {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0})
    assert ok
    _, _, guarda, _ = hk.reconfigurado
    assert guarda is False


def test_tecla_con_guarda_no_pierde_el_guard_aun_con_delay_cero():
    """A left key (needs_guard True) keeps its guard even with a delay of 0:
    it cannot be left unprotected and fire on every ⌘C."""
    hk = _HotkeyFalso()
    ok, _ = apply_shortcut(hk, "dictation", {"keys": ["cmd_l"], "style": "hold", "delay_ms": 0})
    assert ok
    _, _, guarda, _ = hk.reconfigurado
    assert guarda is True


def test_los_otros_atajos_van_por_rebind():
    hk = _HotkeyFalso()
    ok, _ = apply_shortcut(hk, "cancel", {"keys": ["f13"]})
    assert ok
    assert hk.rebindeado == [("cancel", ["f13"])]


def test_si_el_hotkey_rechaza_se_devuelve_el_motivo():
    hk = _HotkeyFalso(ok=False)
    ok, msg = apply_shortcut(hk, "cancel", {"keys": ["f13"]})
    assert not ok
    assert msg, "un rechazo sin motivo deja al usuario sin saber qué pasó"


def test_una_excepcion_del_hotkey_no_propaga():
    # apply_shortcut is called by AppKit code: an uncaught exception
    # there takes the whole app down with it.
    class Explota:
        def reconfigure(self, **kw):
            raise RuntimeError("boom")

    ok, msg = apply_shortcut(Explota(), "dictation",
                             {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0})
    assert not ok
    assert msg


def test_aplicar_un_atajo_no_reinicia_el_listener():
    """A system rule, not a reconfigure()/rebind() detail: changing
    ANY of the four shortcuts never calls .stop() or .start()
    on the HotkeyManager.

    Restarting pynput's keyboard.Listener genuinely crashed the app with
    SIGTRAP in dispatch_assert_queue (it starts with `with keycode_context()`,
    which touches TIS/TSM from the listener's own thread, and HIToolbox
    demands that this happen on the main thread). And even if the thread
    were the right one, having two listeners alive at once — the old one
    not yet joined and the new one — aborts the process with SIGABRT: both
    would call TIS/TSM from different threads. reconfigure() and rebind()
    avoid this at the root: they only mutate normal attributes that
    _on_press/_on_release re-read on every event, so the listener never
    needs to be recreated (see their docstrings in hotkey.py). This test
    keeps that rule watched: if apply_shortcut() ever starts calling
    hk.stop()/hk.start(), it has to fail pointing at the crash it prevents,
    not with an AttributeError that apply_shortcut's `except Exception`
    swallows and disguises as a generic ok=False.
    """
    hk = _HotkeyFalso()
    filas = {
        "dictation": {"keys": ["cmd_l"], "style": "hold", "delay_ms": 400},
        "cycle_mode": {"keys": ["f13"]},
        "latch": {"keys": ["f14"]},
        "cancel": {"keys": ["f15"]},
    }
    for sid, fila in filas.items():
        ok, msg = apply_shortcut(hk, sid, fila)
        assert ok, msg

    assert not hk.parada, (
        "apply_shortcut() paró el listener: reiniciarlo revienta la app con "
        "SIGTRAP en dispatch_assert_queue. Cambiar un atajo nunca debe tocar "
        "stop()."
    )
    assert not hk.arrancada, (
        "apply_shortcut() arrancó un listener nuevo: con el anterior aún "
        "vivo, dos keyboard.Listener a la vez abortan el proceso con "
        "SIGABRT (HIToolbox: la Text Input Sources API llamada desde dos "
        "hilos a la vez). Cambiar un atajo nunca debe tocar start()."
    )


def test_una_migracion_vieja_acaba_persistida(monkeypatch):
    """Whoever updates from v1.3.0 and never opens the Shortcuts window
    must still end up with the "shortcuts" key in their prefs.json —
    otherwise, the day a future version stops reading the old keys, they
    lose their configuration without having done anything wrong."""
    guardado = {}
    monkeypatch.setattr(app_mod, "_save_prefs", lambda prefs: guardado.update(prefs))

    prefs = {"dictation_key": "alt_r", "dictation_mode": "toggle"}
    assert app_mod._migrate_shortcuts_prefs(prefs) is True
    assert guardado.get("shortcuts", {}).get("dictation", {}).get("keys") == ["alt_r"]


def test_un_prefs_ya_migrado_no_provoca_escritura(monkeypatch):
    """Without this cutoff, __init__ would rewrite prefs.json on every launch
    for no reason — shortcuts.migrate() has nothing left to change here."""
    llamadas = []
    monkeypatch.setattr(app_mod, "_save_prefs", lambda prefs: llamadas.append(prefs))

    prefs = {
        "dictation_key": "alt_r",
        "shortcuts": {"dictation": {"keys": ["f13"], "delay_ms": 0, "style": "hold"}},
    }
    assert app_mod._migrate_shortcuts_prefs(prefs) is False
    assert llamadas == []
