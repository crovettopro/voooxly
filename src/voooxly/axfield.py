"""Lectura puntual del campo con foco vía Accessibility. Único punto AX del auto-learn.

Alcance deliberadamente mínimo (es la promesa de privacidad del feature):
una lectura, solo el elemento con foco, campos seguros excluidos, el texto
jamás se persiste ni se loguea. Imports guardados al estilo guide.py para
que pytest importe el módulo sin sesión gráfica.
"""
from __future__ import annotations

try:
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateSystemWide,
    )

    _AX_OK = True
except Exception:  # pyobjc ausente o sin framework: el feature simplemente no actúa
    _AX_OK = False

# Un documento gigante no aporta: lo pegado está cerca del cursor y locate_pasted
# trabaja por palabras. Cota dura para no pasear megabytes entre hilos.
_MAX_FIELD_CHARS = 20000


def read_focused_text() -> str | None:
    """Texto del elemento con foco, o None. Nunca lanza."""
    if not _AX_OK:
        return None
    try:
        err, el = AXUIElementCopyAttributeValue(
            AXUIElementCreateSystemWide(), "AXFocusedUIElement", None
        )
        if err or el is None:
            return None
        err, role = AXUIElementCopyAttributeValue(el, "AXRole", None)
        if not err and role == "AXSecureTextField":
            return None
        err, val = AXUIElementCopyAttributeValue(el, "AXValue", None)
        if err or not isinstance(val, str) or not val.strip():
            return None
        return val[:_MAX_FIELD_CHARS]
    except Exception:
        return None
