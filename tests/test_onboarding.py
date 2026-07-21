"""Tests de la ventana de onboarding.

No se puede "mirar" una ventana desde un test, pero sí construirla de verdad e
inspeccionar su jerarquía y su lógica de estado, que es donde están los fallos
que importan: un botón apuntando a un selector inexistente (crash al pulsarlo),
una fila fuera de los límites, o dejar continuar sin un permiso imprescindible.

Requieren sesión gráfica de macOS (no corren por SSH sin ventana).
"""
from unittest.mock import patch

import pytest

pytest.importorskip("AppKit")

from AppKit import NSApplication  # noqa: E402

from voooxly import onboarding, setup_checks  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _app():
    NSApplication.sharedApplication()


@pytest.fixture
def controller():
    return onboarding.OnboardingController.alloc().initWithFinish_(None)


def _state(mic=True, acc=True, model=True, ai=True):
    from contextlib import ExitStack

    stack = ExitStack()
    for name, value in (("has_microphone", mic), ("has_accessibility", acc),
                        ("has_model", model), ("has_ai_engine", ai)):
        stack.enter_context(patch.object(setup_checks, name, return_value=value))
    return stack


def test_se_construye_con_las_cuatro_filas(controller):
    assert set(controller._rows) == {"mic", "accessibility", "model", "ai"}
    for row in controller._rows.values():
        assert set(row) == {"status", "button", "bar"}


def test_cada_boton_apunta_a_un_selector_que_existe(controller):
    """Un selector mal escrito no falla al construir: revienta al pulsar el botón."""
    for key, row in controller._rows.items():
        sel = row["button"].action()
        assert controller.respondsToSelector_(sel), f"'{key}' apunta a {sel}, que no existe"


def test_ninguna_subvista_se_sale_de_la_ventana(controller):
    for sub in controller._win.contentView().subviews():
        f = sub.frame()
        assert f.origin.x >= 0 and f.origin.y >= 0
        assert f.origin.x + f.size.width <= onboarding.W + 0.5
        assert f.origin.y + f.size.height <= onboarding.H + 0.5


def test_las_filas_no_se_solapan(controller):
    rows = [controller._row_views[k] for k in ("mic", "accessibility", "model", "ai")]
    boxes = sorted((r.frame().origin.y, r.frame().size.height) for r in rows)
    assert len(boxes) == 4
    assert all(boxes[i][0] + boxes[i][1] <= boxes[i + 1][0] + 0.5
               for i in range(len(boxes) - 1))


def test_todo_cumplido_permite_continuar(controller):
    with _state():
        controller._refresh()
        assert controller._done.isEnabled()
        assert controller._rows["mic"]["status"].stringValue() == "●"


def test_sin_accesibilidad_no_deja_continuar(controller):
    with _state(acc=False):
        controller._refresh()
        assert not controller._done.isEnabled()
        assert controller._rows["accessibility"]["button"].isEnabled()


def test_sin_ia_si_deja_continuar(controller):
    """El motor de IA es opcional: sin él se dicta igual en modo Verbatim."""
    with _state(ai=False):
        controller._refresh()
        assert controller._done.isEnabled()
        assert controller._rows["ai"]["button"].isEnabled()


def test_finish_invoca_el_callback():
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_(lambda: llamado.append(1))
    c.finish_(None)
    assert llamado == [1]


def test_continue_pasa_a_pagina_2(controller):
    """El botón Continuar (página 1) cambia a la página 2 sin invocar finish."""
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_(
        lambda: llamado.append(1))
    assert c._page == 1
    c.continue_(None)
    assert c._page == 2
    assert llamado == []  # Continuar NO termina el onboarding


def test_accessibility_esconde_la_ventana(controller):
    """Al pulsar 'Open Settings' la ventana se esconde para no tapar Ajustes."""
    assert controller._hidden_for_settings is False
    controller.accessibility_(None)
    assert controller._hidden_for_settings is True
    assert controller._win.isVisible() is False


def test_refresh_re_muestra_ventana_al_conceder_permiso():
    import time as _time

    c = onboarding.OnboardingController.alloc().initWithFinish_(None)
    c._hidden_for_settings = True
    c._hide_t = _time.monotonic() - 3.0  # ya pasó el grace de 1.5s
    with _state(acc=True):
        c._refresh()
    assert c._hidden_for_settings is False


def test_windowShouldClose_invoca_finish():
    """Cerrar con el botón rojo debe rearrancar el hotkey (on_finish)."""
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_(
        lambda: llamado.append(1))
    c.windowShouldClose_(None)
    assert llamado == [1]


def test_finish_no_revienta_si_el_callback_falla():
    def _explota():
        raise RuntimeError("boom")

    c = onboarding.OnboardingController.alloc().initWithFinish_(_explota)
    c.finish_(None)  # no debe propagar


def test_ventana_tiene_boton_minimizar(controller):
    """La ventana debe ofrecer el botón amarillo de minimizar."""
    from AppKit import NSWindowMiniaturizeButton, NSWindowStyleMaskMiniaturizable

    assert controller._win.styleMask() & NSWindowStyleMaskMiniaturizable
    assert controller._win.standardWindowButton_(NSWindowMiniaturizeButton) is not None


def test_show_activa_politica_regular(controller):
    """Al mostrar el asistente la app pasa a Regular: así la ventana se vuelve
    key/activa y los clics llegan a los botones (y minimizar tiene sentido)."""
    from AppKit import NSApplicationActivationPolicyRegular

    with patch.object(onboarding, "NSApplication") as NSApp:
        controller.show()
        controller._stop_timer()
    NSApp.sharedApplication.return_value.setActivationPolicy_.assert_any_call(
        NSApplicationActivationPolicyRegular)


def test_finish_restaura_politica_accessory(controller):
    """Al terminar volvemos a app de barra (Accessory): sin icono en el Dock."""
    from AppKit import NSApplicationActivationPolicyAccessory

    with patch.object(onboarding, "NSApplication") as NSApp:
        controller.finish_(None)
    NSApp.sharedApplication.return_value.setActivationPolicy_.assert_called_with(
        NSApplicationActivationPolicyAccessory)


# ---- micrófono: requestAccess solo pregunta si el permiso está "sin decidir";
#      si ya se denegó una vez, hay que mandar a Ajustes o el botón parece muerto ----
def test_mic_pide_permiso_si_no_decidido(controller):
    with patch.object(setup_checks, "microphone_status", return_value=0), \
         patch.object(setup_checks, "request_microphone") as req, \
         patch.object(setup_checks, "open_microphone_settings") as open_s:
        controller.mic_(None)
    req.assert_called_once()
    open_s.assert_not_called()


def test_mic_abre_ajustes_si_ya_denegado(controller):
    """denied(2): macOS no vuelve a preguntar; abrimos Ajustes y escondemos la
    ventana para no taparlo (igual que Accesibilidad)."""
    with patch.object(setup_checks, "microphone_status", return_value=2), \
         patch.object(setup_checks, "request_microphone") as req, \
         patch.object(setup_checks, "open_microphone_settings") as open_s:
        controller.mic_(None)
    open_s.assert_called_once()
    req.assert_not_called()
    assert controller._hidden_for_settings is True


# ---- IA opcional: "Connect AI" (nadie tiene IA en el primer arranque, así que
#      no es un "test" sino un "conectar") delega en el callback del app ----
def test_boton_ai_dice_connect_ai(controller):
    assert controller._rows["ai"]["button"].attributedTitle().string() == "Connect AI"


def test_ai_llama_al_callback_de_conexion():
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_connectAI_(
        None, lambda: llamado.append(1))
    c.ai_(None)
    assert llamado == [1]


def test_ai_sin_callback_no_revienta(controller):
    """Sin callback (standalone/tests) cae al re-detectar; no debe propagar."""
    controller.ai_(None)  # on_connect_ai es None → rama de fallback
