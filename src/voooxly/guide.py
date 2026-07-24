"""Ventana "How to use Voooxly": la guía de uso dentro de la app.

Feedback v1.6 de Jeff: "hay muchas funciones pero ninguna guía". Una sola
ventana scrollable que cuenta todo lo que la app sabe hacer, con los atajos
REALES del usuario (via shortcuts.key_label, la tabla única): si alguien cambió
la tecla de dictado a fn, la guía dice fn, no ⌘. El contenido lo decide
sections(), que es pura y está probada; la ventana solo la pinta.

Mismas restricciones que onboarding.py y settings_window.py: NSWindow (nunca
NSPanel — macOS 26 no lo compone), solo instanciable en el hilo principal, a
nivel flotante para que una app de barra sin Dock no la pierda detrás de todo.
"""
from __future__ import annotations

import logging

from . import modes, shortcuts
from .i18n import t

log = logging.getLogger("voooxly.guide")

W, H = 560, 640


def _binding(state: dict, sid: str) -> str:
    """Leyenda del binding real de `sid`: '⌘ (right)', 'fn', '⌃⇧M'…"""
    sc = shortcuts.SHORTCUTS[sid]
    fila = state.get(sid) if isinstance(state, dict) else None
    if not isinstance(fila, dict):
        fila = {}
    names = list(fila.get("keys") or sc.default)
    lado = shortcuts.side_hint(sid, names)
    etiqueta = shortcuts.key_label(names)
    return f"{etiqueta} ({lado})" if lado else etiqueta


def sections(state: dict | None = None) -> list[tuple[str, str]]:
    """(título, cuerpo) de cada sección de la guía, en orden.

    Pura (sin AppKit) para poder testearla. `state` es shortcuts.resolve();
    con None (o un dict a medias) cada atajo cae a su valor de fábrica, igual
    que hace resolve().
    """
    state = state if isinstance(state, dict) else {}
    dic = _binding(state, "dictation")
    fila_dic = state.get("dictation") or {}
    estilo = fila_dic.get("style", shortcuts.DEFAULT_STYLE) if isinstance(fila_dic, dict) else shortcuts.DEFAULT_STYLE
    if estilo == "hold":
        dictar = t("Hold {key}, speak, then release — your words get typed "
                   "right where the cursor is, in any app.").format(key=dic)
    else:
        dictar = t("Press {key} to start, speak, then press it again — your "
                   "words get typed right where the cursor is, in any app."
                   ).format(key=dic)

    # Nombres y descripciones de modos están congelados (registro/ids): no
    # pasan por t(), igual que en el menú.
    lista_modos = "\n".join(
        f"    {info['label']} — {info['hint']}"
        for info in modes.modes_by_key().values()
    )
    n_modos = len(modes.modes_by_key())

    return [
        (t("Dictate anywhere"), dictar),
        (t("Hands-free"),
         t("While dictating, tap {latch} to lock the recording and let go. "
           "Talk as long as you like; tap {dic} to finish.").format(
               latch=_binding(state, 'latch'), dic=dic)),
        (t("Cancel"),
         t("Press {key} while dictating to throw it away — nothing gets "
           "pasted.").format(key=_binding(state, 'cancel'))),
        (t("{n} modes").format(n=n_modos),
         t("A mode decides how your speech is rewritten before it's typed. "
           "Press {key} to cycle modes, or pick one at the top of the "
           "menu:").format(key=_binding(state, 'cycle_mode'))
         + "\n" + lista_modos),
        (t("AI engine"),
         t("Connect Claude, ChatGPT, Gemini or a local Ollama (menu › AI "
           "engine) and Voooxly cleans up, formats and rewrites what you "
           "say. Without AI you still get accurate word-for-word "
           "dictation.")),
        (t("History"),
         t("Recent keeps your last dictations — click one to copy it "
           "again. Search history… finds anything you ever dictated.")),
        (t("Personal dictionary"),
         t("Add names, brands or jargon (menu › Settings › Add to "
           "dictionary…) and Voooxly learns to spell them your way.")),
        (t("Make it yours"),
         t("Every shortcut above can be changed: menu › Shortcuts › "
           "Customize…. Start at login, sounds and the rest live under "
           "Settings.")),
        (t("Updates"),
         t("Voooxly checks for updates daily and installs them itself — "
           "after each one, a What's new note tells you what changed.")),
    ]


# ---------------- ventana (solo pintado) ----------------

# Referencia global: sin ella el recolector se lleva la ventana y desaparece.
_controller = None


def show_guide(state: dict | None = None) -> None:
    """Muestra la guía. DEBE llamarse desde el hilo principal (callback de
    menú de rumps, que ya lo es). El texto se reconstruye en cada apertura:
    los atajos pueden haber cambiado desde la última vez."""
    global _controller
    try:
        if _controller is None:
            _controller = GuideController.alloc().init()
        _controller.showWithState_(state or {})
    except Exception as e:
        log.error("No pude mostrar la guía: %s", e)


def _attributed(state: dict):
    """El documento entero como NSAttributedString con la tipografía de la
    marca (serif para títulos, SF para cuerpo — mismas fuentes que el
    onboarding)."""
    from AppKit import (
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSMutableParagraphStyle,
        NSParagraphStyleAttributeName,
    )
    from Foundation import NSMutableAttributedString

    from . import theme

    doc = NSMutableAttributedString.alloc().init()

    def add(texto, font, color, antes=0.0, despues=8.0, interlinea=2.0):
        p = NSMutableParagraphStyle.alloc().init()
        p.setParagraphSpacingBefore_(antes)
        p.setParagraphSpacing_(despues)
        p.setLineSpacing_(interlinea)
        doc.appendAttributedString_(
            NSMutableAttributedString.alloc().initWithString_attributes_(
                texto + "\n", {
                    NSFontAttributeName: font,
                    NSForegroundColorAttributeName: color,
                    NSParagraphStyleAttributeName: p,
                }))

    add(t("How to use Voooxly"), theme.serif(24, semibold=True), theme.INK,
        despues=2.0)
    add(t("Everything the menu bar mic can do."), theme.sf(13), theme.INK_MUTED,
        despues=6.0)
    for titulo, cuerpo in sections(state):
        add(titulo, theme.serif(16, semibold=True), theme.INK, antes=16.0,
            despues=4.0)
        add(cuerpo, theme.sf(13), theme.INK_SOFT)
    return doc


try:
    import objc
    from Foundation import NSObject

    class GuideController(NSObject):
        def init(self):
            self = objc.super(GuideController, self).init()
            if self is None:
                return None
            self._build()
            return self

        def _build(self):
            from AppKit import (
                NSBackingStoreBuffered,
                NSFloatingWindowLevel,
                NSScrollView,
                NSTextView,
                NSViewHeightSizable,
                NSViewWidthSizable,
                NSWindow,
                NSWindowStyleMaskClosable,
                NSWindowStyleMaskMiniaturizable,
                NSWindowStyleMaskResizable,
                NSWindowStyleMaskTitled,
            )
            from Foundation import NSMakeRect, NSMakeSize

            from . import theme

            self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, W, H),
                NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable,
                NSBackingStoreBuffered,
                False,
            )
            self._win.setTitle_(t("How to use Voooxly"))
            self._win.setReleasedWhenClosed_(False)
            self._win.setLevel_(NSFloatingWindowLevel)
            self._win.setBackgroundColor_(theme.PAGE_BG)
            self._win.setMinSize_(NSMakeSize(420, 360))

            scroll = NSScrollView.alloc().initWithFrame_(
                self._win.contentView().bounds())
            scroll.setHasVerticalScroller_(True)
            scroll.setDrawsBackground_(False)
            scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

            self._text = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
            self._text.setEditable_(False)
            self._text.setSelectable_(True)
            self._text.setDrawsBackground_(True)
            self._text.setBackgroundColor_(theme.PAGE_BG)
            self._text.setTextContainerInset_(NSMakeSize(28, 24))
            self._text.setAutoresizingMask_(NSViewWidthSizable)

            scroll.setDocumentView_(self._text)
            self._win.contentView().addSubview_(scroll)

        def showWithState_(self, state):
            from AppKit import NSApplication

            self._text.textStorage().setAttributedString_(_attributed(state))
            self._text.scrollRangeToVisible_((0, 0))
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            if not self._win.isVisible():
                self._win.center()
            self._win.makeKeyAndOrderFront_(None)

except Exception:  # sin pyobjc (tests de sections() en CI sin AppKit)
    GuideController = None  # type: ignore[assignment]
