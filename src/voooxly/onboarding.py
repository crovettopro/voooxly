"""Asistente de primer arranque: guía permisos, modelo de voz y motor de IA.

Una sola ventana con cabecera de marca (logo + color), una fila por requisito
con su botón de acción, y una tarjeta fija que explica CÓMO dictar (la duda
número uno de quien abre la app por primera vez). El estado se re-comprueba cada
segundo con un NSTimer: cuando el usuario concede Accesibilidad en Ajustes, la
fila se marca sola sin reiniciar Voooxly.

RESTRICCIONES de macOS aprendidas a base de crashes:
- NSWindow solo puede instanciarse en el hilo principal (igual que overlay.py).
- La ventana va a NIVEL FLOTANTE: es una app de barra sin Dock, así que cuando
  el diálogo de permiso o Ajustes del Sistema roban el foco, una ventana normal
  cae al fondo y el usuario la pierde. Flotante la mantiene visible; el diálogo
  modal del sistema va por encima igual, así que no lo tapa.
"""
from __future__ import annotations

import logging
import threading

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

# Color de marca de la cabecera: violeta cálido, para que no parezca un cuadro
# de diálogo del sistema. Blanco encima.
ACCENT = NSColor.colorWithSRGBRed_green_blue_alpha_(0.42, 0.36, 0.90, 1.0)

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
    """Controlador + ventana. Subclase de NSObject para poder ser target de botones."""

    def initWithFinish_(self, on_finish):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._on_finish = on_finish
        self._rows = {}
        self._downloading = False
        self._timer = None
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
        # Flotante: no se pierde detrás de Ajustes del Sistema al conceder permisos.
        self._win.setLevel_(NSFloatingWindowLevel)
        content = self._win.contentView()

        # ---- cabecera de marca (logo + color) ----
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

        content.addSubview_(_label(
            NSMakeRect(104, H - 60, W - 130, 30), "Welcome to Voooxly", 22,
            bold=True, color=NSColor.whiteColor()))
        content.addSubview_(_label(
            NSMakeRect(104, H - 92, W - 130, 22),
            "Dictate anywhere — Voooxly types what you say.", 13,
            color=NSColor.colorWithSRGBRed_green_blue_alpha_(1, 1, 1, 0.85)))

        # ---- sección de requisitos ----
        content.addSubview_(_label(
            NSMakeRect(24, H - HEADER_H - 30, W - 48, 20),
            "A couple of one-time steps:", 12, secondary=True))

        y = H - HEADER_H - 34
        for key, name, desc, action in STEPS:
            y -= ROW_H
            content.addSubview_(self._build_row(key, name, desc, action, y))

        # ---- tarjeta fija: CÓMO dictar ----
        card = NSView.alloc().initWithFrame_(NSMakeRect(24, 74, W - 48, 74))
        card.setWantsLayer_(True)
        card.layer().setBackgroundColor_(
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.42, 0.36, 0.90, 0.10).CGColor())
        card.layer().setCornerRadius_(10.0)
        card.addSubview_(_label(
            NSMakeRect(14, 48, W - 76, 18), "How to dictate", 12, bold=True))
        howto = _label(
            NSMakeRect(14, 8, W - 76, 38),
            "Hold the right ⌘ key, speak, then let go — your words get typed "
            "where the cursor is.\nRight ⌘ + Shift = hands-free · Ctrl+Shift+M = "
            "change mode · Esc = cancel.", 11, secondary=True)
        _make_multiline(howto)
        card.addSubview_(howto)
        content.addSubview_(card)

        self._done = NSButton.alloc().initWithFrame_(NSMakeRect(W - 172, 26, 148, 34))
        self._done.setTitle_("Start dictating")
        self._done.setBezelStyle_(1)
        self._done.setKeyEquivalent_("\r")
        self._done.setTarget_(self)
        self._done.setAction_("finish:")
        content.addSubview_(self._done)

        self._refresh()

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

    def finish_(self, _sender):
        self._stop_timer()
        self._win.orderOut_(None)
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                log.debug("callback on_finish falló", exc_info=True)

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
