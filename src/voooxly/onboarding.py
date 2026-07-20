"""Asistente de primer arranque en DOS pasos: primero configurar (permisos,
modelo, IA) y luego cómo dictar. El estado se re-comprueba cada segundo con un
NSTimer: cuando el usuario concede Accesibilidad en Ajustes, la fila se marca
sola sin reiniciar Voooxly.

Dos bugs de macOS que esta versión arregla:
- Ajustes del Sistema bloqueado por la ventana: al pulsar "Open Settings"
  escondemos el onboarding (orderOut); el NSTimer lo vuelve a mostrar cuando
  se concede el permiso (o cuando el usuario vuelve a la app). Antes la ventana
  flotante se quedaba encima de Ajustes y no te dejaba tocarlo.
- Hotkey mudo la primera vez: pynput arranca sin Accesibilidad y no recibe
  eventos; conceder el permiso a mitad no reactiva el listener. Por eso el
  callback on_finish rearranca el hotkey (ver app.py _on_onboarding_done), y por
  eso cerrar la ventana con el botón rojo también dispara finish_.

RESTRICCIONES de macOS aprendidas a base de crashes:
- NSWindow solo puede instanciarse en el hilo principal (igual que overlay.py).
- La ventana va a NIVEL FLOTANTE: es una app de barra sin Dock, así no se pierde
  atrás mientras descarga el modelo. Al abrir Ajustes se esconde (ver arriba).
"""
from __future__ import annotations

import logging
import threading
import time

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSImageView,
    NSProgressIndicator,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject, NSTimer

from . import setup_checks, stt

log = logging.getLogger("voooxly.onboarding")

W, H = 560, 640
HEADER_H = 124
ROW_H = 78

# Color de marca (violeta cálido) y sus variantes para fondos tenues / keycaps.
ACCENT = NSColor.colorWithSRGBRed_green_blue_alpha_(0.42, 0.36, 0.90, 1.0)
ACCENT_TINT = NSColor.colorWithSRGBRed_green_blue_alpha_(0.42, 0.36, 0.90, 0.10)
CARD_BG = NSColor.colorWithSRGBRed_green_blue_alpha_(0.97, 0.97, 0.99, 1.0)
CARD_BORDER = NSColor.colorWithSRGBRed_green_blue_alpha_(0.80, 0.78, 0.88, 1.0)

# key, título, explicación, texto del botón. El orden es el de check_all().
STEPS = [
    ("mic", "Microphone",
     "So Voooxly can hear you. Your voice never leaves this Mac.", "Allow"),
    ("accessibility", "Accessibility",
     "Lets Voooxly type into any app and use the dictation hotkey.", "Open Settings"),
    ("model", "Speech model",
     "One-time 547 MB download. Runs fully offline after that.", "Download"),
    ("ai", "AI engine — optional",
     "Polish your dictation with Claude, ChatGPT, Gemini… Add it anytime from "
     "the menu bar (🎙 icon → AI engine). Works great without it.", "Check again"),
]


class OnboardingController(NSObject):
    """Controlador + ventana. Subclase de NSObject para ser target de los
    botones y delegate de la ventana (así cerrar con el botón rojo = finish_)."""

    def initWithFinish_(self, on_finish):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._on_finish = on_finish
        self._rows = {}
        self._downloading = False
        self._timer = None
        self._page = 1
        self._hidden_for_settings = False
        self._hide_t = 0.0
        self._page1 = []   # subviews de la página 1 (config)
        self._page2 = []   # subviews de la página 2 (cómo dictar)
        self._build()
        return self

    # ---------- construcción ----------
    def _build(self):
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._win.setTitle_("Welcome to Voooxly")
        self._win.setReleasedWhenClosed_(False)
        # Flotante: no se pierde atrás mientras descarga el modelo. Al abrir
        # Ajustes se esconde (accessibility_), así que no tapa Ajustes del Sistema.
        self._win.setLevel_(NSFloatingWindowLevel)
        # Cerrar con el botón rojo cuenta como finish: rearranca el hotkey.
        self._win.setDelegate_(self)
        content = self._win.contentView()

        self._build_header(content)
        self._build_page1(content)
        self._build_page2(content)
        self._show_page(1)
        self._refresh()

    def _build_header(self, content):
        header = NSView.alloc().initWithFrame_(NSMakeRect(0, H - HEADER_H, W, HEADER_H))
        header.setWantsLayer_(True)
        header.layer().setBackgroundColor_(ACCENT.CGColor())
        content.addSubview_(header)

        icon = NSImageView.alloc().initWithFrame_(NSMakeRect(28, H - 92, 60, 60))
        try:
            icon.setImage_(NSApplication.sharedApplication().applicationIconImage())
        except Exception:
            log.debug("No pude cargar el icono en el onboarding", exc_info=True)
        content.addSubview_(icon)

        self._header_title = _label(
            NSMakeRect(104, H - 60, W - 130, 30), "Welcome to Voooxly", 22,
            bold=True, color=NSColor.whiteColor())
        content.addSubview_(self._header_title)
        self._header_sub = _label(
            NSMakeRect(104, H - 92, W - 130, 22),
            "Dictate anywhere — Voooxly types what you say.", 13,
            color=NSColor.colorWithSRGBRed_green_blue_alpha_(1, 1, 1, 0.85))
        content.addSubview_(self._header_sub)

    # ---------------- página 1: configurar ----------------
    def _build_page1(self, content):
        top = H - HEADER_H  # 516
        sec = _label(NSMakeRect(24, top - 30, W - 48, 20),
                     "A couple of one-time steps:", 12, secondary=True)
        content.addSubview_(sec)
        self._page1.append(sec)

        y = top - 34
        for key, name, desc, action in STEPS:
            y -= ROW_H
            row = self._build_row(key, name, desc, action, y)
            content.addSubview_(row)
            self._page1.append(row)

        note = _label(
            NSMakeRect(24, 92, W - 48, 40),
            "Takes about 2 minutes. You can change any of this later from the "
            "menu bar (🎙 icon).", 11, secondary=True)
        _make_multiline(note)
        content.addSubview_(note)
        self._page1.append(note)

        self._done = NSButton.alloc().initWithFrame_(NSMakeRect(W - 172, 26, 148, 34))
        self._done.setTitle_("Continue →")
        self._done.setBezelStyle_(1)
        self._done.setKeyEquivalent_("\r")
        self._done.setTarget_(self)
        self._done.setAction_("continue:")
        content.addSubview_(self._done)
        self._page1.append(self._done)

    # ---------------- página 2: cómo dictar ----------------
    def _build_page2(self, content):
        top = H - HEADER_H  # 516

        h1 = _label(NSMakeRect(24, top - 34, W - 48, 30),
                    "You're all set 🎉", 24, bold=True)
        content.addSubview_(h1)
        self._page2.append(h1)

        sub = _label(NSMakeRect(24, top - 58, W - 48, 20),
                     "Here's how to dictate. It lives in your menu bar.", 13,
                     secondary=True)
        content.addSubview_(sub)
        self._page2.append(sub)

        # ---- hero: la tecla de dictado ----
        hero = NSView.alloc().initWithFrame_(NSMakeRect(40, top - 196, W - 80, 120))
        hero.setWantsLayer_(True)
        hero.layer().setBackgroundColor_(ACCENT_TINT.CGColor())
        hero.layer().setCornerRadius_(14.0)
        k = _label(NSMakeRect(0, 74, W - 80, 40), "⌘", 34, bold=True, color=ACCENT)
        k.setAlignment_(2)
        hero.addSubview_(k)
        h2 = _label(NSMakeRect(0, 48, W - 80, 22), "Hold the RIGHT ⌘ key", 13, bold=True)
        h2.setAlignment_(2)
        hero.addSubview_(h2)
        h3 = _label(NSMakeRect(0, 16, W - 80, 30),
                    "speak, then release — your words get typed "
                    "where the cursor is.", 11, secondary=True)
        _make_multiline(h3)
        h3.setAlignment_(2)
        hero.addSubview_(h3)
        content.addSubview_(hero)
        self._page2.append(hero)

        # ---- tres atajos ----
        y = top - 226
        for keys, title, desc in (
            ("⌘ + Shift", "Hands-free", "Toggle dictation on/off without holding."),
            ("⌃⇧M", "Change mode", "Cycle 8 modes (verbatim, email, code…)."),
            ("Esc", "Cancel", "Throw away the dictation in progress."),
        ):
            y -= 56
            row = self._shortcut_row(y, keys, title, desc)
            content.addSubview_(row)
            self._page2.append(row)

        self._start = NSButton.alloc().initWithFrame_(NSMakeRect(W - 172, 26, 148, 34))
        self._start.setTitle_("Start dictating")
        self._start.setBezelStyle_(1)
        self._start.setKeyEquivalent_("\r")
        self._start.setTarget_(self)
        self._start.setAction_("finish:")
        content.addSubview_(self._start)
        self._page2.append(self._start)

    def _shortcut_row(self, y, keys, title, desc):
        row = NSView.alloc().initWithFrame_(NSMakeRect(24, y, W - 48, 48))
        cap = _keycap(NSMakeRect(0, 4, 110, 40), keys)
        row.addSubview_(cap)
        row.addSubview_(_label(NSMakeRect(126, 24, W - 48 - 130, 18), title, 12, bold=True))
        d = _label(NSMakeRect(126, 4, W - 48 - 130, 20), desc, 11, secondary=True)
        _make_multiline(d)
        row.addSubview_(d)
        return row

    def _build_row(self, key, name, desc, action, y):
        row = NSView.alloc().initWithFrame_(NSMakeRect(24, y, W - 48, ROW_H - 10))
        rw = W - 48

        status = _label(NSMakeRect(0, 40, 22, 20), "○", 15)
        row.addSubview_(status)
        row.addSubview_(_label(NSMakeRect(24, 40, 260, 20), name, 13, bold=True))
        desc_lbl = _label(NSMakeRect(24, 4, rw - 150, 34), desc, 11, secondary=True)
        _make_multiline(desc_lbl)
        row.addSubview_(desc_lbl)

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(rw - 124, 38, 124, 26))
        btn.setTitle_(action)
        btn.setBezelStyle_(1)
        btn.setTarget_(self)
        btn.setAction_(f"{key}:")
        row.addSubview_(btn)

        bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(24, 2, rw - 150, 12))
        bar.setStyle_(0)              # NSProgressIndicatorStyleBar
        bar.setIndeterminate_(False)
        bar.setMinValue_(0.0)
        bar.setMaxValue_(100.0)
        bar.setHidden_(True)
        row.addSubview_(bar)

        self._rows[key] = {"status": status, "button": btn, "bar": bar}
        return row

    # ---------- acciones de los botones (selectores mic:, accessibility:, ...) ----------
    def mic_(self, _sender):
        setup_checks.request_microphone()

    def accessibility_(self, _sender):
        setup_checks.open_accessibility_settings()
        # Escondemos el onboarding para que Ajustes del Sistema sea visible y
        # manejable: antes la ventana flotante se quedaba encima y bloqueaba.
        # El NSTimer (_refresh) lo vuelve a mostrar cuando se concede el permiso
        # o cuando el usuario vuelve a Voooxly.
        self._win.orderOut_(None)
        self._hidden_for_settings = True
        self._hide_t = time.monotonic()

    def model_(self, _sender):
        if self._downloading:
            return
        self._downloading = True
        row = self._rows["model"]
        row["button"].setEnabled_(False)
        row["button"].setTitle_("Downloading…")
        row["bar"].setHidden_(False)
        threading.Thread(target=self._download_model, daemon=True).start()

    def ai_(self, _sender):
        from . import refine

        refine.detect_backend(force=True)
        self._refresh()

    def continue_(self, _sender):
        """Página 1 → 2. Solo se habilita cuando los checks bloqueantes pasan."""
        self._show_page(2)

    def finish_(self, _sender):
        self._stop_timer()
        self._win.orderOut_(None)
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                log.debug("callback on_finish falló", exc_info=True)

    def windowShouldClose_(self, _sender):
        # Cerrar con el botón rojo cuenta como finish: rearranca el hotkey.
        self.finish_(None)
        return True

    # ---------- descarga del modelo ----------
    def _download_model(self):
        """Corre en hilo secundario; todo toque de UI se reenvía al principal."""
        try:
            stt.ensure_model(progress_cb=lambda pct:
                             self.performSelectorOnMainThread_withObject_waitUntilDone_(
                                 "updateProgress:", pct, False))
        except Exception as e:
            log.error("Descarga del modelo falló: %s", e)
        finally:
            self._downloading = False
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "downloadFinished:", None, False)

    def updateProgress_(self, pct):
        try:
            self._rows["model"]["bar"].setDoubleValue_(float(pct))
        except Exception:
            pass

    def downloadFinished_(self, _arg):
        row = self._rows["model"]
        row["button"].setTitle_("Download")
        self._refresh()

    # ---------- refresco periódico ----------
    def tick_(self, _timer):
        self._refresh()

    def _start_timer(self):
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True)

    def _stop_timer(self):
        if self._timer is not None:
            try:
                self._timer.invalidate()
            except Exception:
                pass
            self._timer = None

    def _refresh(self):
        ready = True
        for check in setup_checks.check_all():
            row = self._rows.get(check.key)
            if row is None:
                continue
            row["status"].setStringValue_("●" if check.ok else "○")
            row["status"].setTextColor_(
                NSColor.systemGreenColor() if check.ok else NSColor.tertiaryLabelColor())
            # El paso de IA se puede re-comprobar siempre; los demás solo si faltan.
            if not (check.key == "model" and self._downloading):
                row["button"].setEnabled_(not check.ok or check.key == "ai")
            if check.key == "model" and check.ok:
                row["bar"].setHidden_(True)
            if check.blocking and not check.ok:
                ready = False
        self._done.setEnabled_(ready)

        # Re-mostrar la ventana si la escondimos para ir a Ajustes del Sistema.
        if self._hidden_for_settings:
            granted = setup_checks.has_accessibility()
            back = NSApplication.sharedApplication().isActive()
            elapsed = time.monotonic() - self._hide_t
            # El ">1.5s" evita re-mostrar en el mismo tick antes de que Ajustes
            # robe el foco. Se re-muestra al conceder el permiso o al volver a
            # la app.
            if granted or (back and elapsed > 1.5):
                self._hidden_for_settings = False
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                self._win.makeKeyAndOrderFront_(None)

    # ---------- páginas ----------
    def _show_page(self, n):
        self._page = n
        for v in self._page1:
            v.setHidden_(n != 1)
        for v in self._page2:
            v.setHidden_(n != 2)
        if n == 1:
            self._header_title.setStringValue_("Welcome to Voooxly")
            self._header_sub.setStringValue_(
                "Dictate anywhere — Voooxly types what you say.")
            # Enter = Continuar; el de la página 2 sin equivalente para que no
            # disparen ambos a la vez.
            self._done.setKeyEquivalent_("\r")
            self._start.setKeyEquivalent_("")
        else:
            self._header_title.setStringValue_("You're ready to dictate")
            self._header_sub.setStringValue_("Two keys are all you need.")
            self._done.setKeyEquivalent_("")
            self._start.setKeyEquivalent_("\r")

    def show(self):
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._win.center()
        self._win.makeKeyAndOrderFront_(None)
        self._start_timer()


def _label(rect, text, size, bold=False, secondary=False, color=None):
    f = NSTextField.alloc().initWithFrame_(rect)
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if color is not None:
        f.setTextColor_(color)
    elif secondary:
        f.setTextColor_(NSColor.secondaryLabelColor())
    return f


def _keycap(rect, text, size=13):
    """Tecla estilizada: rectángulo redondeado con borde y el texto centrado."""
    w = rect.size.width
    h = rect.size.height
    v = NSView.alloc().initWithFrame_(rect)
    v.setWantsLayer_(True)
    v.layer().setBackgroundColor_(CARD_BG.CGColor())
    v.layer().setCornerRadius_(8.0)
    v.layer().setBorderWidth_(1.0)
    v.layer().setBorderColor_(CARD_BORDER.CGColor())
    lbl = _label(NSMakeRect(0, (h - (size + 4)) // 2, w, size + 4), text, size, bold=True)
    lbl.setAlignment_(2)  # centered
    v.addSubview_(lbl)
    return v


def _make_multiline(field):
    """Deja que un NSTextField ocupe varias líneas (para descripciones largas)."""
    try:
        field.setUsesSingleLineMode_(False)
        field.cell().setWraps_(True)
        field.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping
    except Exception:
        pass


# Referencia global: sin ella el recolector se lleva la ventana y desaparece sola.
_controller = None


def show_onboarding(on_finish=None) -> None:
    """Muestra el asistente. DEBE llamarse desde el hilo principal."""
    global _controller
    try:
        _controller = OnboardingController.alloc().initWithFinish_(on_finish)
        _controller.show()
    except Exception as e:
        log.error("No pude mostrar el onboarding: %s", e)