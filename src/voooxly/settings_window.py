"""Ventana de Shortcuts: reasignar los cuatro atajos capturando teclas.

NSWindow, NUNCA NSPanel: en macOS 26 (Darwin 25) el window server no compone
un NSPanel — isVisible devuelve True y no hay un solo píxel. El HUD estuvo
roto en silencio por eso durante semanas. Verificar SIEMPRE con screencapture.

NSWindow solo se puede instanciar en el hilo principal, igual que overlay.py y
onboarding.py. La captura llega por el hilo del listener de pynput, así que
todo repintado que salga de ella va por AppHelper.callAfter.

Este módulo solo pinta y recoge: quién puede tener qué tecla lo decide
shortcuts.py, que es puro y está probado.
"""
from __future__ import annotations

import logging
import math

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSTextAlignmentCenter,
    NSTextAlignmentRight,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject

from . import shortcuts, theme

log = logging.getLogger("voooxly.settings_window")

W, H = 560, 620
PAD = 28
ROW_H = 46

# Nombre pynput → símbolo de macOS. Lo que el usuario ve en un teclado.
_SIMBOLO = {
    "cmd": "⌘", "cmd_l": "⌘", "cmd_r": "⌘",
    "alt": "⌥", "alt_l": "⌥", "alt_r": "⌥", "alt_gr": "⌥",
    "ctrl": "⌃", "ctrl_l": "⌃", "ctrl_r": "⌃",
    "shift": "⇧", "shift_l": "⇧", "shift_r": "⇧",
    "space": "␣", "enter": "⏎", "tab": "⇥", "backspace": "⌫",
}

def y_(top, h):
    """'y desde arriba' (como en el diseño) → origen abajo-izquierda."""
    return H - top - h


def key_label(names: list[str]) -> str:
    """['ctrl','shift','m'] → '⌃⇧M'. Lo que se pinta en el keycap."""
    fuera = []
    for n in names or []:
        low = n.lower()
        if low in _SIMBOLO:
            fuera.append(_SIMBOLO[low])
        elif low == "esc":
            fuera.append("esc")
        else:
            fuera.append(low.upper())
    return "".join(fuera)


# Los cuatro valores que shortcuts.side_hint puede devolver (ver su
# docstring): la etiqueta de lado se dimensiona sobre el más ancho de
# estos con AppKit, no sobre un número puesto a ojo. Ese fue justo el bug:
# 58pt alcanzaban para "right" pero "either side" ya no cabía, y el texto
# (correcto) se recortaba en pantalla sin que ningún test lo viera, porque
# stringValue() sigue devolviendo el texto completo aunque el glifo se
# corte al dibujarse.
_LADOS_POSIBLES = ("right", "left", "either side", "")
_LADO_HOLGURA = 6   # aire entre el texto medido y el borde del campo
_LADO_ALTO = 15
_LADO_GAP = 4       # hueco entre el keycap y la etiqueta de lado
_LADO_MARGEN_D = 4  # hueco entre la etiqueta de lado y el borde de la fila
_KEYCAP_W = 62
_KEYCAP_H = 26


def _lado_ancho(font) -> float:
    """Puntos que necesita el campo del lado para no cortar ningún valor de
    shortcuts.side_hint con `font`, medido de verdad con AppKit.

    Autodefensivo a propósito: si mañana side_hint gana un quinto valor más
    largo que "either side", basta con añadirlo a _LADOS_POSIBLES — el
    ancho se recalcula solo, no hay un número de puntos que reajustar
    también a mano y que se pueda olvidar.
    """
    return math.ceil(max(theme.text_width(t, font) for t in _LADOS_POSIBLES)) + _LADO_HOLGURA


def side_label(sid: str, names: list[str]) -> str:
    """'right' / 'left' / 'either side' / '' — el matiz que un símbolo ⌘ solo
    no puede dar.

    Envoltorio de presentación: la decisión de qué lado(s) casan de verdad en
    runtime es semántica de atajos, no de pintado, y vive en
    shortcuts.side_hint (probada ahí sin AppKit). Hace falta `sid` y no solo
    el nombre de la tecla porque el mismo nombre significa cosas distintas
    según el atajo — "shift" en latch casa las dos manos (hotkey.py:421),
    pero un combo o una tecla sin lado en cualquier otro atajo no la casan.
    """
    return shortcuts.side_hint(sid, names)


class ShortcutsController(NSObject):
    """Controlador + ventana. Subclase de NSObject para ser target de los
    botones y delegate de la ventana."""

    def initWithState_onChange_(self, estado, on_change):
        self = objc.super(ShortcutsController, self).init()
        if self is None:
            return None
        self._estado = {sid: dict(fila) for sid, fila in estado.items()}
        self._on_change = on_change
        self._rows = {}          # sid → NSView de la fila
        self._keycaps = {}       # sid → NSTextField del keycap
        self._sides = {}         # sid → NSTextField del lado
        self._build()
        return self

    def _build(self):
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._win.setTitle_("Shortcuts")
        self._win.setReleasedWhenClosed_(False)
        self._win.setDelegate_(self)
        self._win.setBackgroundColor_(theme.PAGE_BG)
        content = self._win.contentView()

        content.addSubview_(theme.label(
            NSMakeRect(PAD, y_(28, 24), W - PAD * 2, 24),
            "Shortcuts", theme.sf(19, 0.35), theme.INK))
        content.addSubview_(theme.label(
            NSMakeRect(PAD, y_(54, 17), W - PAD * 2, 17),
            "Click a shortcut, then press the keys you want to use.",
            theme.sf(12.5), theme.INK_SOFT))

        lado_font = theme.mono(9.5)
        lado_w = _lado_ancho(lado_font)   # una sola vez: mismo ancho en las 4 filas

        top = 330   # el teclado de la Task 9 ocupa de 84 a 320
        for sid in shortcuts.SHORTCUTS:
            fila = self._build_row(
                sid, NSMakeRect(PAD, y_(top, ROW_H), W - PAD * 2, ROW_H), lado_font, lado_w)
            content.addSubview_(fila)
            self._rows[sid] = fila
            content.addSubview_(theme.rule(
                NSMakeRect(PAD, y_(top + ROW_H, 1), W - PAD * 2, 1), theme.HAIRLINE))
            top += ROW_H + 1

    def _build_row(self, sid, frame, lado_font, lado_w):
        sc = shortcuts.SHORTCUTS[sid]
        row = NSView.alloc().initWithFrame_(frame)
        rw = frame.size.width

        row.addSubview_(theme.label(
            NSMakeRect(0, 24, rw - 150, 17), sc.label, theme.sf(13.5, 0.3), theme.INK))
        row.addSubview_(theme.label(
            NSMakeRect(0, 6, rw - 150, 16), sc.subtitle, theme.sf(11.5), theme.INK_MUTED))

        nombres = list(self._estado.get(sid, {}).get("keys") or [])

        # La columna del lado se reserva primero, con el ancho ya calculado
        # para caber cualquiera de sus cuatro valores posibles, y el keycap
        # se cuelga a su izquierda con el mismo hueco de siempre. lado_w es
        # igual en las cuatro filas, así que cap_x también lo es — la
        # columna de keycaps queda alineada pase lo que pase el texto de
        # cada fila.
        lado_x = rw - _LADO_MARGEN_D - lado_w
        cap_x = lado_x - _LADO_GAP - _KEYCAP_W

        cap = theme.keycap(NSMakeRect(cap_x, 12, _KEYCAP_W, _KEYCAP_H),
                           key_label(nombres), theme.sf(14, 0.3), 7)
        row.addSubview_(cap)
        self._keycaps[sid] = cap

        lado = theme.label(NSMakeRect(lado_x, 17, lado_w, _LADO_ALTO),
                           side_label(sid, nombres),
                           lado_font, theme.INK_MUTED)
        row.addSubview_(lado)
        self._sides[sid] = lado
        return row

    # ---------- ciclo de vida ----------
    def show(self):
        self._win.makeKeyAndOrderFront_(None)
        self._win.center()

    def close(self):
        try:
            self._win.close()
        except Exception:
            log.debug("close() de la ventana de Shortcuts falló", exc_info=True)

    def windowShouldClose_(self, _sender):
        return True
