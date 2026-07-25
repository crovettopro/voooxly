"""Tests for the onboarding window.

You cannot "look at" a window from a test, but you can build it for real and
inspect its hierarchy and state logic, which is where the failures that matter
are: a button pointing at a nonexistent selector (crash when pressed), a row
out of bounds, or letting the user continue without an essential permission.

They require a macOS graphical session (they do not run over windowless SSH).
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
    """A misspelled selector does not fail at build time: it blows up when the button is pressed."""
    for key, row in controller._rows.items():
        sel = row["button"].action()
        assert controller.respondsToSelector_(sel), f"'{key}' apunta a {sel}, que no existe"


def test_no_subview_goes_outside_window(controller):
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


def test_all_satisfied_allows_continuing(controller):
    with _state():
        controller._refresh()
        assert controller._done.isEnabled()
        assert controller._rows["mic"]["status"].stringValue() == "●"


def test_without_accessibility_cannot_continue(controller):
    with _state(acc=False):
        controller._refresh()
        assert not controller._done.isEnabled()
        assert controller._rows["accessibility"]["button"].isEnabled()


def test_without_ai_can_continue(controller):
    """The AI engine is optional: without it you still dictate in Verbatim mode."""
    with _state(ai=False):
        controller._refresh()
        assert controller._done.isEnabled()
        assert controller._rows["ai"]["button"].isEnabled()


def test_cta_label_respects_language():
    """The 'Continuar →' CTA must not fall back to English when the NSTimer
    calls _refresh every second (review finding #1): _build_page1 and _refresh
    both render cta_label(), a single source, so they cannot drift apart.
    Pure: instantiates nothing from AppKit."""
    from voooxly import i18n

    i18n.set_lang("es")
    try:
        assert onboarding.cta_label() == "Continuar →"
    finally:
        i18n.set_lang("en")


def test_finish_invoca_el_callback():
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_(lambda: llamado.append(1))
    c.finish_(None)
    assert llamado == [1]


def test_continue_pasa_a_pagina_2(controller):
    """The Continue button (page 1) switches to page 2 without invoking finish."""
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_(
        lambda: llamado.append(1))
    assert c._page == 1
    c.continue_(None)
    assert c._page == 2
    assert llamado == []  # Continue does NOT finish the onboarding


def test_accessibility_hides_window(controller):
    """Pressing 'Open Settings' hides the window so it does not cover System Settings."""
    assert controller._hidden_for_settings is False
    controller.accessibility_(None)
    assert controller._hidden_for_settings is True
    assert controller._win.isVisible() is False


def test_refresh_shows_window_again_when_permission_granted():
    import time as _time

    c = onboarding.OnboardingController.alloc().initWithFinish_(None)
    c._hidden_for_settings = True
    c._hide_t = _time.monotonic() - 3.0  # the 1.5s grace period already elapsed
    with _state(acc=True):
        c._refresh()
    assert c._hidden_for_settings is False


def test_windowShouldClose_invoca_finish():
    """Closing with the red button must restart the hotkey (on_finish)."""
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_(
        lambda: llamado.append(1))
    c.windowShouldClose_(None)
    assert llamado == [1]


def test_finish_does_not_crash_if_callback_fails():
    def _explota():
        raise RuntimeError("boom")

    c = onboarding.OnboardingController.alloc().initWithFinish_(_explota)
    c.finish_(None)  # must not propagate


def test_ventana_tiene_boton_minimizar(controller):
    """The window must offer the yellow minimize button."""
    from AppKit import NSWindowMiniaturizeButton, NSWindowStyleMaskMiniaturizable

    assert controller._win.styleMask() & NSWindowStyleMaskMiniaturizable
    assert controller._win.standardWindowButton_(NSWindowMiniaturizeButton) is not None


def test_show_activa_politica_regular(controller):
    """When showing the assistant the app switches to Regular: this makes the
    window key/active so clicks reach the buttons (and minimize makes sense)."""
    from AppKit import NSApplicationActivationPolicyRegular

    with patch.object(onboarding, "NSApplication") as NSApp:
        controller.show()
        controller._stop_timer()
    NSApp.sharedApplication.return_value.setActivationPolicy_.assert_any_call(
        NSApplicationActivationPolicyRegular)


def test_finish_restaura_politica_accessory(controller):
    """On finish we go back to a menu-bar app (Accessory): no Dock icon."""
    from AppKit import NSApplicationActivationPolicyAccessory

    with patch.object(onboarding, "NSApplication") as NSApp:
        controller.finish_(None)
    NSApp.sharedApplication.return_value.setActivationPolicy_.assert_called_with(
        NSApplicationActivationPolicyAccessory)


# ---- microphone: requestAccess only asks while the permission is "not determined";
#      once it was denied, we must send the user to Settings or the button seems dead ----
def test_mic_pide_permiso_si_no_decidido(controller):
    with patch.object(setup_checks, "microphone_status", return_value=0), \
         patch.object(setup_checks, "request_microphone") as req, \
         patch.object(setup_checks, "open_microphone_settings") as open_s:
        controller.mic_(None)
    req.assert_called_once()
    open_s.assert_not_called()


def test_mic_abre_ajustes_si_ya_denegado(controller):
    """denied(2): macOS will not ask again; we open Settings and hide the
    window so it is not covered (same as Accessibility)."""
    with patch.object(setup_checks, "microphone_status", return_value=2), \
         patch.object(setup_checks, "request_microphone") as req, \
         patch.object(setup_checks, "open_microphone_settings") as open_s:
        controller.mic_(None)
    open_s.assert_called_once()
    req.assert_not_called()
    assert controller._hidden_for_settings is True


# ---- optional AI: "Connect AI" (nobody has AI on first launch, so it is
#      not a "test" but a "connect") delegates to the app's callback ----
def test_boton_ai_dice_connect_ai(controller):
    assert controller._rows["ai"]["button"].attributedTitle().string() == "Connect AI"


def test_ai_llama_al_callback_de_conexion():
    llamado = []
    c = onboarding.OnboardingController.alloc().initWithFinish_connectAI_(
        None, lambda: llamado.append(1))
    c.ai_(None)
    assert llamado == [1]


def test_ai_without_callback_does_not_crash(controller):
    """Without a callback (standalone/tests) it falls back to re-detecting; must not propagate."""
    controller.ai_(None)  # on_connect_ai is None → fallback branch


# --- Page 2: the user must leave knowing the key can be changed ---


def _textos_pagina2(controller):
    return [s.stringValue() for s in controller._page2
            if hasattr(s, "stringValue")]


def test_la_pagina_2_avisa_de_que_la_tecla_se_puede_cambiar(controller):
    # Without this line, whoever cannot use the right ⌘ (external keyboard
    # without it, busy hand) closes the onboarding believing the app is not for
    # them, instead of opening Shortcuts and changing the key. It is the only
    # screen they are guaranteed to see. The destination is the top-level
    # "Shortcuts › Customize…" submenu (v1.6 feedback): shortcuts moved out of
    # Settings into plain sight, and this notice points to where they are NOW.
    todo = " ".join(_textos_pagina2(controller)).lower()
    assert "shortcuts" in todo
    assert "customize" in todo


def test_key_notice_does_not_cover_start_button(controller):
    # It slipped in between the last shortcut row and the CTA. If someone adds
    # another shortcut without repositioning, the text piles on top of the
    # button: it reads badly and the click lands in the wrong place.
    cta = controller._start.frame()
    techo = cta.origin.y + cta.size.height
    for s in controller._page2:
        if s is controller._start:
            continue
        f = s.frame()
        assert f.origin.y >= techo - 0.5, (
            f"una vista de la página 2 baja hasta y={f.origin.y}, "
            f"por debajo del techo del botón Start dictating (y={techo})"
        )
