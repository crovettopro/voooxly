"""Brand palette and base widgets, shared by the AppKit windows.

They lived in onboarding.py until there was a second window (Shortcuts).
Duplicating the palette guarantees it desyncs at the first branding
touch-up, and ending up with two differently colored windows in the same app.

The colors are those of voooxly.com and make-icon.py: teal + paper.
"""
from __future__ import annotations

from AppKit import (
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSTextAlignmentCenter,
    NSTextAlignmentLeft,
    NSTextField,
    NSView,
)
from Foundation import NSMakeRect, NSMakeSize, NSString


def hex_(s, a=1.0):
    s = s.lstrip("#")
    return NSColor.colorWithSRGBRed_green_blue_alpha_(
        int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0, a)


# ---- brand palette: teal + paper (voooxly.com / make-icon.py) ----
TEAL = hex_("#107A69")
TEAL_DARK = hex_("#085448")
INK = hex_("#1B241F")
INK_SOFT = hex_("#5F6B65")
INK_MUTED = hex_("#93A099")
INK_KEYCAP = hex_("#3F4A46")
PAGE_BG = hex_("#FCFDFC")
HAIRLINE = hex_("#EEF2F0")
DIVIDER = hex_("#E9EEEB")
BTN_BORDER = hex_("#DDE4E1")
BTN_GHOST_TEXT = hex_("#7C8A84")
MODEL_BTN_BG = hex_("#EDF5F3")
MODEL_BTN_BORDER = hex_("#BFDBD3")
PROGRESS_TRACK = hex_("#E4EEEB")
PENDING_RING = hex_("#CBD6D1")
CTA_DISABLED_BG = hex_("#EDF1EF")
CTA_DISABLED_TEXT = hex_("#AAB5B0")
KEYCAP_BG = hex_("#FFFFFF")
KEYCAP_BG2 = hex_("#EEF4F1")
KEYCAP_EDGE = hex_("#DEE9E4")


# ---------------- fonts ----------------
def sf(size, weight=0.0):
    return NSFont.systemFontOfSize_weight_(float(size), float(weight))


def mono(size, weight=0.0):
    try:
        return NSFont.monospacedSystemFontOfSize_weight_(float(size), float(weight))
    except Exception:
        return NSFont.systemFontOfSize_(float(size))


def text_width(text, font):
    """Width in points that `text` occupies drawn with `font`.

    For sizing a field by real AppKit measurement instead of by eye:
    a fixed number of points falls short as soon as the text changes (it
    happened to settings_window.py's side label, designed for "right" and
    blown up by "either side"), but the width measured with the real font
    never desyncs from what AppKit is going to paint.
    """
    return NSString.stringWithString_(text or "").sizeWithAttributes_(
        {NSFontAttributeName: font}).width


def serif(size, semibold=False):
    for name in (("Iowan Old Style Bold",) if semibold else ()) + ("Iowan Old Style",):
        f = NSFont.fontWithName_size_(name, float(size))
        if f is not None:
            return f
    try:  # system serif design (New York) as backup
        d = NSFont.systemFontOfSize_(float(size)).fontDescriptor()
        d = d.fontDescriptorWithDesign_("NSCTFontUIFontDesignSerif")
        f = NSFont.fontWithDescriptor_size_(d, float(size))
        if f is not None:
            return f
    except Exception:
        pass
    return NSFont.boldSystemFontOfSize_(float(size)) if semibold else NSFont.systemFontOfSize_(float(size))


# ---------------- view helpers ----------------
def label(rect, text, font, color=None, align=NSTextAlignmentLeft, multiline=False):
    f = NSTextField.alloc().initWithFrame_(rect)
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(font)
    if color is not None:
        f.setTextColor_(color)
    if align != NSTextAlignmentLeft:
        f.setAlignment_(align)
    if multiline:
        _make_multiline(f)
    return f


def rule(rect, color):
    """Hairline line (divider / row separator)."""
    v = NSView.alloc().initWithFrame_(rect)
    v.setWantsLayer_(True)
    v.layer().setBackgroundColor_(color.CGColor())
    return v


# Air between a glyph's measured width (text_width) and the field that
# paints it inside keycap(): the same 6pt slack that _LADO_HOLGURA and
# _NOTA_HUERFANA_HOLGURA already use in settings_window.py, here it is
# also needed -even in LEFT alignment- so the NSTextField itself
# doesn't clip its last character (see the "CAREFUL" in keycap()'s
# docstring).
_KEYCAP_LABEL_HOLGURA = 6


def keycap(rect, text, glyph_font, radius, gradient=False):
    """Stylized keycap: rounded paper/white with a border and an embossed
    bottom edge (depth). The glyph centered.

    The centering does NOT use NSTextAlignmentCenter (Task 10, Defect 2
    -fix2-): a centered NSTextField computes its own "natural" width to paint
    the text, wider than what text_width() really measures, and if the field
    doesn't have that margin to spare it clips the last glyph silently -same
    defect, exactly the same family of bug that already burned the delay
    value in settings_window.py (see _build_row's long comment there: "200"
    was painted as "20" with align=Center even though the field measured
    the text's REAL width with text_width() with room to spare). Here the
    centering is done by hand: the glyph's real width comes from text_width()
    with the font that will actually be painted, and the field is placed
    already centered inside the keycap, in LEFT alignment -the one that
    truly doesn't clip-, instead of trusting NSTextAlignmentCenter to
    reserve the margin that internal calculation demands.

    CAREFUL, this really bit during the visual check of this very fix: the
    first version sized the field EXACTLY to text_width(), with no slack,
    and "esc" was painted as "es" -verified with screencapture, not an
    illusion of the capture-, even though text_width() already measured
    right and stringValue() kept returning the full "esc". Not even left
    alignment is exempt from needing spare air (the same lesson, again,
    that already burned the delay fields in settings_window.py): the field
    is widened by an extra _KEYCAP_LABEL_HOLGURA and the origin keeps being
    centered over the width WITHOUT the slack, so the surplus stays on the
    right, where it goes unnoticed."""
    w, h = rect.size.width, rect.size.height
    v = NSView.alloc().initWithFrame_(rect)
    v.setWantsLayer_(True)
    layer = v.layer()
    layer.setCornerRadius_(float(radius))
    layer.setBorderWidth_(1.0)
    layer.setBorderColor_(KEYCAP_EDGE.CGColor())
    if gradient:
        try:
            from Quartz import CAGradientLayer
            g = CAGradientLayer.layer()
            g.setFrame_(NSMakeRect(0, 0, w, h))
            g.setCornerRadius_(float(radius))
            g.setColors_([KEYCAP_BG.CGColor(), KEYCAP_BG2.CGColor()])
            layer.addSublayer_(g)
        except Exception:
            layer.setBackgroundColor_(KEYCAP_BG.CGColor())
    else:
        layer.setBackgroundColor_(KEYCAP_BG.CGColor())
    try:
        layer.setShadowOpacity_(0.22 if gradient else 0.10)
        layer.setShadowRadius_(12.0 if gradient else 3.0)
        layer.setShadowOffset_(NSMakeSize(0, -3 if gradient else -1))
        layer.setShadowColor_(TEAL_DARK.CGColor())
    except Exception:
        pass
    ancho_glifo = text_width(text, glyph_font)
    lbl = label(NSMakeRect((w - ancho_glifo) / 2, (h - (glyph_font.pointSize() + 8)) / 2,
                           ancho_glifo + _KEYCAP_LABEL_HOLGURA, glyph_font.pointSize() + 8),
                text, glyph_font, TEAL_DARK if gradient else INK_KEYCAP)
    v.addSubview_(lbl)
    return v


def _make_multiline(field):
    """Lets an NSTextField span several lines (for long descriptions)."""
    try:
        field.setUsesSingleLineMode_(False)
        field.cell().setWraps_(True)
        field.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping
    except Exception:
        pass
