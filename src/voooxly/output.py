"""Output: copy to the clipboard and/or paste into the active app with Cmd+V.

Pasting simulates Cmd+V by posting CGEvent events via pynput.Controller. That is
covered by the Accessibility permission (which the app already needs for the hotkey).
We do NOT use osascript/System Events: it requires the Automation permission
(NSAppleEventsUsageDescription + separate prompt) and without it it hangs until timeout.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("voooxly.output")


def html_flavor(html: str | None) -> str | None:
    """The HTML as it must go onto the pasteboard: with a declared charset.

    NSPasteboard stores the string, but the receiving app reads BYTES of the
    public.html flavor: without `<meta charset>` the HTML standard mandates
    decoding as Windows-1252 and every UTF-8 accent breaks ("ó" → "Ã³"). It
    really happened with a notes-mode dictation pasted into a web editor.
    markdown_to_html stays a pure fragment generator; the declaration is the
    clipboard's business.
    """
    if not html or html.startswith('<meta charset="utf-8">'):
        return html
    return '<meta charset="utf-8">' + html


def copy_to_clipboard(text: str, html: str | None = None) -> None:
    if not text:
        return
    # Direct NSPasteboard: pbcopy interprets stdin per LANG/LC_CTYPE, and when
    # launching the .app from Finder there's no locale -> it assumes Mac Roman
    # and breaks accents (í -> √≠). Writing the NSString avoids the encoding
    # entirely. If `html` arrives, it's added as a second flavor (public.html):
    # rich-text apps (Mail, Gmail, Notion) paste rendered headings/lists and
    # plain-text ones (Terminal, Obsidian, IDEs) keep taking the plain one.
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, NSPasteboardTypeString)
        if html:
            pb.setString_forType_(html_flavor(html), "public.html")
    except Exception as e:
        log.error("NSPasteboard failed (%s); falling back to pbcopy", e)
        try:
            env = {**os.environ, "LC_CTYPE": "UTF-8"}
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=env, check=True)
        except Exception as e2:
            log.error("pbcopy failed: %s", e2)


_kb = None
_kb_lock = threading.Lock()


def _controller():
    """pynput's Controller, built ONE single time.

    Its __init__ queries the keyboard layout via TIS/TSM. Building it on
    every paste (from _process's worker thread) made it coincide sooner or
    later with another thread touching TSM —the hotkey listener— and then
    HIToolbox kills the process: SIGTRAP in dispatch_assert_queue, which is
    NOT a Python exception and no try/except can catch.

    press()/release() only use the already-cached mapping and CGEventPost, so
    with a single construction pasting stops touching TSM. See warmup().
    """
    global _kb
    with _kb_lock:
        if _kb is None:
            from pynput.keyboard import Controller

            _kb = Controller()
        return _kb


def warmup() -> bool:
    """Pays the TSM cost at startup, from the main thread with no threads alive yet."""
    try:
        _controller()
        return True
    except Exception as e:
        log.warning("Couldn't prep the keyboard for pasting: %s", e)
        return False


def paste_frontmost() -> bool:
    """Simulates Cmd+V in the active app by posting keyboard events (Accessibility)."""
    try:
        from pynput.keyboard import Key

        kb = _controller()
        kb.press(Key.cmd)
        kb.press("v")
        time.sleep(0.02)
        kb.release("v")
        kb.release(Key.cmd)
        return True
    except Exception as e:
        log.error("Paste failed (Accessibility granted?): %s", e)
        return False


def deliver(text: str, auto_paste: bool, copy: bool, html: str | None = None) -> str:
    """Delivers the text and returns how it went, so the UI can report:

    - "pasted": pasted into the active app (the usual).
    - "copied": not pasted, but it's on the clipboard (manual ⌘V).
    - "failed": neither pasted nor copied.
    """
    if not text:
        return "failed"
    if copy:
        copy_to_clipboard(text, html)
    if auto_paste:
        # small delay so the clipboard settles
        time.sleep(0.08)
        ok = paste_frontmost()
        if ok:
            return "pasted"
        if copy:
            log.info("Texto dejado en portapapeles (pega manual Cmd+V).")
            return "copied"
        return "failed"
    return "copied" if copy else "failed"
