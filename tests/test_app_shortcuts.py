"""El pegamento entre la ventana y el hotkey, sin instanciar VoooxlyApp.

Instanciar VoooxlyApp construye menús de AppKit y no corre en un test (mismo
motivo por el que existen keys.py, shortcuts.py y ai_menu_labels a nivel de
módulo). Se prueba la función de aplicar un atajo contra un hotkey falso.
"""
from voooxly.app import apply_shortcut


class _HotkeyFalso:
    def __init__(self, ok=True):
        self._ok = ok
        self.reconfigurado = None
        self.rebindeado = []

    def reconfigure(self, toggle_key, toggle_mode, guard, guard_delay=None):
        self.reconfigurado = (toggle_key, toggle_mode, guard, guard_delay)
        return self._ok

    def rebind(self, sid, names):
        self.rebindeado.append((sid, names))
        return self._ok


def test_dictation_va_por_reconfigure_con_el_delay_en_segundos():
    hk = _HotkeyFalso()
    ok, msg = apply_shortcut(hk, "dictation", {"keys": ["cmd_l"], "style": "hold", "delay_ms": 400})
    assert ok, msg
    tecla, modo, guarda, delay = hk.reconfigurado
    assert tecla == "cmd_l"
    assert modo == "hold"
    assert guarda is True
    assert abs(delay - 0.4) < 1e-9, "el hotkey espera SEGUNDOS, la ventana da ms"


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
    # apply_shortcut lo llama código de AppKit: una excepción sin capturar
    # ahí se lleva la app entera por delante.
    class Explota:
        def reconfigure(self, **kw):
            raise RuntimeError("boom")

    ok, msg = apply_shortcut(Explota(), "dictation",
                             {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0})
    assert not ok
    assert msg
