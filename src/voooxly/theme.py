"""Paleta de marca y widgets base, compartidos por las ventanas de AppKit.

Vivían en onboarding.py hasta que hubo una segunda ventana (Shortcuts).
Duplicar la paleta garantiza que se desincronice en el primer retoque de
marca, y acabar con dos ventanas de colores distintos en la misma app.

Los colores son los de voooxly.com y make-icon.py: teal + papel.
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


# ---- paleta de marca: teal + papel (voooxly.com / make-icon.py) ----
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


# ---------------- fuentes ----------------
def sf(size, weight=0.0):
    return NSFont.systemFontOfSize_weight_(float(size), float(weight))


def mono(size, weight=0.0):
    try:
        return NSFont.monospacedSystemFontOfSize_weight_(float(size), float(weight))
    except Exception:
        return NSFont.systemFontOfSize_(float(size))


def text_width(text, font):
    """Ancho en puntos que ocupa `text` dibujado con `font`.

    Para dimensionar un campo por medición real de AppKit en vez de a ojo:
    un número de puntos fijo se queda corto en cuanto el texto cambia (le
    pasó a la etiqueta de lado de settings_window.py, pensada para "right" y
    reventada por "either side"), pero el ancho medido con el font real
    nunca se desincroniza de lo que AppKit va a pintar.
    """
    return NSString.stringWithString_(text or "").sizeWithAttributes_(
        {NSFontAttributeName: font}).width


def serif(size, semibold=False):
    for name in (("Iowan Old Style Bold",) if semibold else ()) + ("Iowan Old Style",):
        f = NSFont.fontWithName_size_(name, float(size))
        if f is not None:
            return f
    try:  # diseño serif del sistema (New York) como respaldo
        d = NSFont.systemFontOfSize_(float(size)).fontDescriptor()
        d = d.fontDescriptorWithDesign_("NSCTFontUIFontDesignSerif")
        f = NSFont.fontWithDescriptor_size_(d, float(size))
        if f is not None:
            return f
    except Exception:
        pass
    return NSFont.boldSystemFontOfSize_(float(size)) if semibold else NSFont.systemFontOfSize_(float(size))


# ---------------- helpers de vistas ----------------
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
    """Línea hairline (divisor / separador de filas)."""
    v = NSView.alloc().initWithFrame_(rect)
    v.setWantsLayer_(True)
    v.layer().setBackgroundColor_(color.CGColor())
    return v


# Aire entre el ancho medido de un glifo (text_width) y el campo que lo
# pinta dentro de keycap(): la misma holgura de 6pt que ya usan
# _LADO_HOLGURA y _NOTA_HUERFANA_HOLGURA en settings_window.py, aquí
# también hace falta -incluso en alineación IZQUIERDA- para que el propio
# NSTextField no recorte su último carácter (ver el "OJO" en la docstring
# de keycap()).
_KEYCAP_LABEL_HOLGURA = 6


def keycap(rect, text, glyph_font, radius, gradient=False):
    """Tecla estilizada: papel/blanco redondeado con borde y borde-inferior en
    relieve (profundidad). El glifo centrado.

    El centrado NO usa NSTextAlignmentCenter (Task 10, Defecto 2 -fix2-): un
    NSTextField centrado calcula su propio ancho "natural" para pintar el
    texto, más ancho que lo que text_width() mide de verdad, y si el campo no
    le sobra ese margen recorta el último glifo en silencio -mismo defecto,
    exactamente la misma familia de bug que ya escarmentó al valor del delay
    en settings_window.py (ver el comentario largo de _build_row ahí: "200"
    se pintaba "20" con align=Center aunque el campo midiera de sobra el
    ancho REAL del texto con text_width()). Aquí se centra a mano: el ancho
    real del glifo sale de text_width() con el font que de verdad se va a
    pintar, y el campo se coloca ya centrado dentro del keycap, en alineación
    IZQUIERDA -la que de verdad no recorta-, en vez de fiarse de que
    NSTextAlignmentCenter reserve el margen que ese cálculo interno pide.

    OJO, esto mordió de verdad en la propia comprobación visual de este
    arreglo: la primera versión medía el campo EXACTO a text_width(), sin
    holgura, y "esc" se pintaba "es" -comprobado con screencapture, no una
    ilusión de la captura-, aunque text_width() ya midiera bien y
    stringValue() siguiera devolviendo "esc" completo. Ni siquiera la
    alineación izquierda se libra de necesitar aire de sobra (la misma
    lección, otra vez, que ya escarmentó a los campos del delay en
    settings_window.py): el campo se ensancha con _KEYCAP_LABEL_HOLGURA de
    más y el origen se sigue centrando sobre el ancho SIN holgura, así que
    el sobrante queda a la derecha, donde no se nota."""
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
    """Deja que un NSTextField ocupe varias líneas (para descripciones largas)."""
    try:
        field.setUsesSingleLineMode_(False)
        field.cell().setWraps_(True)
        field.cell().setLineBreakMode_(0)  # NSLineBreakByWordWrapping
    except Exception:
        pass
