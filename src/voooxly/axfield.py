"""Point-in-time read of the focused field via Accessibility. The only AX point of auto-learn.

Deliberately minimal scope (it's the feature's privacy promise): one read,
only the focused element, secure fields excluded, the text is never persisted
nor logged. Imports guarded guide.py-style so pytest imports the module
without a graphical session.
"""
from __future__ import annotations

try:
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateSystemWide,
    )

    _AX_OK = True
except Exception:  # pyobjc missing or no framework: the feature just doesn't act
    _AX_OK = False

# A giant document adds nothing: what's pasted is near the cursor and
# locate_pasted works word by word. Hard cap to avoid moving megabytes between threads.
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
