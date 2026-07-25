"""Overlay HUD: floating window with a status title + body, Wispr-style.

macOS 26 GOTCHA: an NSPanel (borderless OR titled) NEVER reaches the window
server — isVisible=True but CGWindowList doesn't list it and not a single
pixel gets painted (verified with captures). A borderless NSWindow does get
composed, with a dark rounded CALayer (the NSVisualEffectView blur was part
of the ghost recipe). Do not go back to NSPanel.

Design: short title with a color-accented glyph (● red recording, ✦ amber
processing, ✓ teal pasted, ❯ teal on mode change) + dimmed body. The
window grows/shrinks with the content, anchored bottom-right.

Must be built on the main thread (rumps runloop); show/update/hide can
be called from any thread (AppHelper.callAfter does the dispatch).
"""
from __future__ import annotations

import logging

log = logging.getLogger("voooxly.overlay")

try:
    from AppKit import (
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSMutableParagraphStyle,
        NSParagraphStyleAttributeName,
        NSScreen,
        NSTextField,
        NSView,
        NSWindow,
        NSBackingStoreBuffered,
        NSBorderlessWindowMask,
    )
    from Foundation import NSMutableAttributedString, NSRect
    from PyObjCTools import AppHelper
    _HAVE_PYOBJC = True
except Exception as e:  # pragma: no cover
    log.warning("pyobjc no disponible: overlay desactivado (%s)", e)
    _HAVE_PYOBJC = False

W = 520
PAD_X = 18
PAD_Y = 14
MIN_H = 52
MAX_H = 300
MARGIN = 24

# Color of the title's leading glyph according to what it announces
_ACCENTS = {
    "●": (0.91, 0.26, 0.24),   # recording — red
    "✦": (0.82, 0.54, 0.13),   # processing — amber (the brand's --signal)
    "✓": (0.18, 0.64, 0.55),   # done — teal (the brand's --resolved)
    "❯": (0.18, 0.64, 0.55),   # mode change — teal
}


class Overlay:
    def __init__(self, position: str = "bottom-right"):
        self.position = position
        self._win = None
        self._label = None
        self._built = False
        self._visible = False
        self._title = ""
        self._body = ""

    # --- lifecycle (main thread) ---
    def build(self):
        """Builds the NSWindow. MUST be called from the main thread, once."""
        self._build()

    def _build(self):
        if not _HAVE_PYOBJC or self._built:
            return
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSRect((0, 0), (W, MIN_H)),
            NSBorderlessWindowMask,
            NSBackingStoreBuffered,
            False,
        )
        win.setReleasedWhenClosed_(False)
        win.setLevel_(19)  # NSFloatingWindowLevel
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setHasShadow_(True)
        win.setCollectionBehavior_(1 << 4)  # CanJoinAllSpaces

        container = NSView.alloc().initWithFrame_(NSRect((0, 0), (W, MIN_H)))
        container.setWantsLayer_(True)
        layer = container.layer()
        layer.setBackgroundColor_(
            NSColor.colorWithCalibratedWhite_alpha_(0.07, 0.90).CGColor()
        )
        layer.setCornerRadius_(14.0)
        layer.setBorderWidth_(1.0)
        layer.setBorderColor_(
            NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.09).CGColor()
        )
        win.setContentView_(container)

        label = NSTextField.alloc().initWithFrame_(
            NSRect((PAD_X, PAD_Y), (W - 2 * PAD_X, MIN_H - 2 * PAD_Y))
        )
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setStringValue_("")
        container.addSubview_(label)

        self._win = win
        self._label = label
        self._built = True

    # --- public API (any thread) ---
    def show(self, text: str = "", title: str | None = None) -> None:
        """Shows the HUD. `title` sets the status line; None removes it."""
        if not _HAVE_PYOBJC or not self._built:
            return
        self._title = title or ""
        self._body = text or ""
        self._visible = True
        AppHelper.callAfter(self._render, True)

    def update(self, text: str) -> None:
        """Updates the body keeping the title (e.g. live partials)."""
        if not _HAVE_PYOBJC or not self._visible:
            return
        self._body = text or ""
        AppHelper.callAfter(self._render, False)

    def hide(self) -> None:
        if not _HAVE_PYOBJC or self._win is None or not self._visible:
            return
        self._visible = False
        AppHelper.callAfter(self._do_hide)

    # --- render (always on the main thread) ---
    def _do_hide(self):
        try:
            self._win.orderOut_(None)
        except Exception:
            log.debug("hide failed", exc_info=True)

    def _attributed(self):
        text = NSMutableAttributedString.alloc().init()
        if self._title:
            para = NSMutableParagraphStyle.alloc().init()
            para.setParagraphSpacing_(5.0)
            t = NSMutableAttributedString.alloc().initWithString_attributes_(
                self._title + ("\n" if self._body else ""),
                {
                    NSFontAttributeName: NSFont.systemFontOfSize_weight_(15.0, 0.3),
                    NSForegroundColorAttributeName: NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.96),
                    NSParagraphStyleAttributeName: para,
                },
            )
            accent = _ACCENTS.get(self._title[:1])
            if accent:
                t.addAttribute_value_range_(
                    NSForegroundColorAttributeName,
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(*accent, 1.0),
                    (0, 1),
                )
            text.appendAttributedString_(t)
        if self._body:
            body_alpha = 0.70 if self._title else 0.92
            b = NSMutableAttributedString.alloc().initWithString_attributes_(
                self._body,
                {
                    NSFontAttributeName: NSFont.systemFontOfSize_weight_(13.5, 0.0),
                    NSForegroundColorAttributeName: NSColor.colorWithCalibratedWhite_alpha_(1.0, body_alpha),
                },
            )
            text.appendAttributedString_(b)
        return text

    def _render(self, reorder: bool):
        if self._win is None or self._label is None:
            return
        try:
            attr = self._attributed()
            # text height at fixed width → the window fits the content
            bounds = attr.boundingRectWithSize_options_(
                (W - 2 * PAD_X, 100000), 1  # NSStringDrawingUsesLineFragmentOrigin
            )
            text_h = min(max(int(bounds.size.height) + 2, MIN_H - 2 * PAD_Y), MAX_H)
            win_h = text_h + 2 * PAD_Y

            frame = NSScreen.mainScreen().visibleFrame()
            if self.position == "top-right":
                x = frame.origin.x + frame.size.width - W - MARGIN
                y = frame.origin.y + frame.size.height - win_h - MARGIN
            elif self.position == "center":
                x = frame.origin.x + (frame.size.width - W) / 2
                y = frame.origin.y + (frame.size.height - win_h) / 2
            else:  # bottom-right (anchored at the bottom: grows upward)
                x = frame.origin.x + frame.size.width - W - MARGIN
                y = frame.origin.y + MARGIN

            self._win.setFrame_display_(NSRect((x, y), (W, win_h)), True)
            self._label.setFrame_(NSRect((PAD_X, PAD_Y), (W - 2 * PAD_X, text_h)))
            self._label.setAttributedStringValue_(attr)
            if reorder:
                self._win.orderFrontRegardless()
        except Exception:
            log.debug("overlay render failed", exc_info=True)
