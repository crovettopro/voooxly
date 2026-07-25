"""Reads of the focused field via Accessibility. The only AX point of auto-learn.

Scope is the feature's privacy promise, and it is worth stating exactly:
only the focused element, never a secure field, and the text is neither
persisted nor logged — only the pairs the user corrected reach the
dictionary. What is NOT true is "a single read": since v1.9 the post-paste
window reads the field a handful of times over a few seconds (learn.watch_field),
because a correction made in a message the user then sends was lost otherwise.

That widens the promise in one honest way: this follows FOCUS, so a later read
can land on a field the paste never touched. app_locked_reader() narrows it
back by refusing to read once the user has left the app that received the
paste. Imports guarded guide.py-style so pytest imports the module without a
graphical session.
"""
from __future__ import annotations

import re

try:
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateSystemWide,
    )

    _AX_OK = True
except Exception:  # pyobjc missing or no framework: the feature just doesn't act
    _AX_OK = False

try:  # separate: an older pyobjc without it must not disable the read itself
    from ApplicationServices import AXUIElementGetPid
except Exception:
    AXUIElementGetPid = None

# A giant document adds nothing: what's pasted is near the cursor and
# locate_pasted works word by word. Hard cap to avoid moving megabytes between threads.
_MAX_FIELD_CHARS = 20000


def clip(text: str) -> str:
    """Caps the field, cutting on a word boundary.

    The cap is a character count, so it lands anywhere — including inside the
    last word of what we just pasted. A halved word looks exactly like a 1→1
    correction to the learner ("mañana" → "maña") and would be persisted as a
    global replacement. Dropping the stump turns it into a deletion, which
    learn.corrections() ignores on purpose.
    """
    if len(text) <= _MAX_FIELD_CHARS:
        return text
    cut = text[:_MAX_FIELD_CHARS]
    if not text[_MAX_FIELD_CHARS].isspace():
        cut = re.sub(r"\S+$", "", cut)  # the cut fell inside a word: drop it whole
    return cut


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
        return clip(val) or None
    except Exception:
        return None


def focused_pid() -> int | None:
    """PID of the app that owns the focused element, or None. Never raises."""
    if not _AX_OK or AXUIElementGetPid is None:
        return None
    try:
        err, el = AXUIElementCopyAttributeValue(
            AXUIElementCreateSystemWide(), "AXFocusedUIElement", None
        )
        if err or el is None:
            return None
        err, pid = AXUIElementGetPid(el, None)
        return None if err else int(pid)
    except Exception:
        return None


def app_locked_reader(read=None, pid=None):
    """A read() that goes blind once focus leaves the app it first saw.

    The post-paste window reads repeatedly and matches by text, so a field in
    ANOTHER app holding nearly the same words looks exactly like the one we
    pasted into. Locking onto the pid closes that for the common case (⌘Tab,
    clicking another window). It cannot tell two fields of the SAME app apart
    — that limitation is inherited from the single-read path and stands.

    The lock is taken on the first pid seen, not the first successful read:
    at t=0 the ⌘V is usually still in flight, but the app is already the right one.
    """
    read = read or read_focused_text
    pid = pid or focused_pid
    origen: list[int] = []

    def _read() -> str | None:
        try:
            actual = pid()
        except Exception:
            actual = None
        if actual is not None:
            if not origen:
                origen.append(actual)
            elif actual != origen[0]:
                return None  # otra app: dejamos de mirar
        return read()

    return _read
