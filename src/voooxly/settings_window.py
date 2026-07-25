"""Shortcuts window: reassign the four shortcuts by capturing keys.

NSWindow, NEVER NSPanel: on macOS 26 (Darwin 25) the window server does not
composite an NSPanel — isVisible returns True and not a single pixel shows. The
HUD was silently broken for weeks because of this. ALWAYS verify with screencapture.

NSWindow can only be instantiated on the main thread, just like overlay.py and
onboarding.py. Capture arrives on the pynput listener thread, so any repaint
coming out of it goes through AppHelper.callAfter.

This module only paints and collects: who may hold which key is decided by
shortcuts.py, which is pure and tested.
"""
from __future__ import annotations

import logging
import math

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSSlider,
    NSTextAlignmentCenter,
    NSTextAlignmentRight,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeRect, NSObject

from . import keys, shortcuts, theme

log = logging.getLogger("voooxly.settings_window")

W, H = 560, 620
PAD = 28
ROW_H = 46

def y_(top, h):
    """'y from the top' (as in the design) → bottom-left origin."""
    return H - top - h


# The symbol table and key_label now live in shortcuts.py (shared with the
# menu bar's Shortcuts submenu, v1.6 feedback). There is still ONE single
# table — just in the pure module; this alias keeps the keycaps, the chips
# and the filler cells (⇪, fn, "arrows") going through it.
key_label = shortcuts.key_label


# The four values shortcuts.side_hint can return (see its docstring):
# the side label is sized against the widest of these with AppKit, not
# against an eyeballed number. That was exactly the bug: 58pt was enough
# for "right" but "either side" no longer fit, and the (correct) text got
# clipped on screen without any test seeing it, because stringValue()
# still returns the full text even when the glyph gets cut off as it is
# drawn.
_LADOS_POSIBLES = ("right", "left", "either side", "")
_LADO_HOLGURA = 6   # air between the measured text and the field's edge
_LADO_ALTO = 15
_LADO_GAP = 4       # gap between the chips field and the side label
_LADO_MARGEN_D = 4  # gap between the field and the row's edge

# Wispr Flow-style chips field (Eduardo's feedback, with screenshots):
# each key of the shortcut is its OWN chip (⌃ ⇧ M, three chips) inside a
# white field with a pencil ✎ at the end. The pencil IS the edit affordance
# — "Change" as loose text was not recognized as an action. The real click
# is still received by the invisible button covering the whole row.
_CHIP_FONT_PT = 12.5
_CHIP_PESO = 0.3
_CHIP_H = 22
_CHIP_PAD = 7        # horizontal air inside each chip
_CHIP_GAP = 4        # gap between chips
_FIELD_PAD = 8       # inner air of the field, on both sides
_FIELD_H = 32
_PENCIL_TXT = "✎"
_PENCIL_W = 16
_FIELD_MIN_W = 110
# Placeholder for the field during capture, until the first key lands
# (the analogue of Wispr's "Click to add a shortcut"). Fits with room to
# spare: the field is at least _FIELD_MIN_W and the phrase ~62pt at 11pt.
_FIELD_HINT = "Press keys…"

# Wispr's "Reset to default" (appears in all three feedback screenshots):
# returns the four shortcuts to factory defaults in one click.
_RESET_TXT = "Reset to defaults"


def chip_texts(names: list[str]) -> list[str]:
    """['ctrl','shift','m'] → ['⌃','⇧','M']: one chip per key, Wispr style.

    Goes through key_label key by key so the chip and the visual keyboard's
    legend cannot spell the same key in two different ways."""
    return [key_label([n]) for n in (names or [])]


def _chip_ancho(texto: str, font) -> float:
    """Width of a chip: its text truly measured (theme.text_width, the
    lesson from _lado_ancho) with air on both sides, and never narrower than
    it is tall — a one-letter chip draws as a square, not as a sliver."""
    return max(math.ceil(theme.text_width(texto, font)) + 2 * _CHIP_PAD, _CHIP_H)


def _chips_ancho(textos: list[str], font) -> float:
    if not textos:
        return 0.0
    return sum(_chip_ancho(t, font) for t in textos) + _CHIP_GAP * (len(textos) - 1)


def field_width(estado: dict, font) -> float:
    """SINGLE width for the chips field, shared by the four rows (the same
    decision as lado_w): the maximum any current binding asks for plus the
    pencil, with _FIELD_MIN_W as the floor. Sharing it keeps the column
    aligned — four fields of different widths would read as staggered."""
    necesita = max(
        (_chips_ancho(chip_texts(list((fila or {}).get("keys") or [])), font)
         for fila in estado.values()),
        default=0.0,
    )
    return max(_FIELD_MIN_W, necesita + 2 * _FIELD_PAD + _PENCIL_W + _CHIP_GAP)

# Extra height the Dictation row gains for the delay slider (see
# _build_row): the usual content (title, subtitle, keycap, side) shifts up
# by this same height, so it occupies exactly the same rectangle it would
# occupy in a normal ROW_H row, and the slider lives in the new band left
# free below, INSIDE the row's frame -not outside it-, so it does not
# invade the row below (see the long comment in
# _build_row).
#
# Raised from 24 to 36 in Finding 1 of the review: with 24 the slider
# (height 20) sat flush against the row's bottom edge and there was no room
# for the new tick marks below the track. The extra 12pt are exactly what
# _DELAY_MARCA_H + the gap separating them from the slider ask for (see
# below); raising this constant automatically pushes every following row
# (Cycle mode included) downward -_build() just repeats alto_fila+1-, so
# nothing else needs touching to keep them from eating into each other.
_DELAY_ROW_EXTRA_H = 36

# Geometry of the slider and its marks inside the [0, _DELAY_ROW_EXTRA_H)
# band left free below the normal content of the Dictation row (see the
# comment above and the one in _build_row). The slider moves up from its old
# y=2 to _DELAY_SLIDER_Y=14 to leave, below it, the [0, 14) strip for the
# marks -before, that strip did not exist and the marks had nowhere to go
# without invading something-, keeping the same ~8pt margin between the
# slider and the subtitle above that the original design already had.
_DELAY_SLIDER_Y = 14
_DELAY_MARCA_Y = 0
_DELAY_MARCA_H = 11
_DELAY_MARCA_PT = 9.0        # small and in secondary gray, as the brief asks
# 2pt of slack clipped the last digit of "200"/"400"/"600" on screen
# (verified with screencapture: "200" read as "20"), even though
# theme.text_width() measured "correctly" -sizeWithAttributes_ gives the pure
# glyph advance, not the space an NSTextField's cell wants around it.
# 6pt is the same slack _LADO_HOLGURA and _NOTA_HUERFANA_HOLGURA already use
# higher up in this module, and there it does not clip.
_DELAY_MARCA_HOLGURA = 6.0   # air between each mark's measured text and its field
_DELAY_VALOR_PT = 13.5
_DELAY_VALOR_PESO = 0.5      # actually bold (NSFontWeightBold is 0.40)
_DELAY_VALOR_GAP = 14.0      # gap between the slider's right edge and the value
_DELAY_VALOR_HOLGURA = 6.0   # air between the value's measured text and its field


def _marcas_delay() -> list[int]:
    """The five values the delay slider spreads out (Finding 1 of the
    review): 0, MAX/4, MAX/2, 3·MAX/4 and MAX -not a hand-hardcoded
    0/200/400/600/800-, so that if shortcuts.MAX_DELAY_MS changes tomorrow
    the marks follow it on their own, with no need to remember to also touch
    this number here (the same lesson _lado_ancho() already applies with
    shortcuts.side_hint higher up in this module)."""
    paso = shortcuts.MAX_DELAY_MS / 4
    return [round(paso * i) for i in range(5)]


def _fmt_delay(ms) -> str:
    """'400 ms': the exact format the brief asks for the chosen value."""
    return f"{int(ms)} ms"


def _valor_ancho(font) -> float:
    """Width the delay value text ('N ms') needs for ANY N between 0 and
    shortcuts.MAX_DELAY_MS, truly measured with AppKit over the entire
    range: a proportional font does not measure the same for every
    three-digit number, so the worst case is computed over the full range
    instead of assuming the maximum value is the widest one (the same
    reason _lado_ancho() measures the four side_hint possibilities
    instead of hardcoding a number)."""
    return math.ceil(max(
        theme.text_width(_fmt_delay(ms), font)
        for ms in range(0, shortcuts.MAX_DELAY_MS + 1)
    )) + _DELAY_VALOR_HOLGURA


def _alto_multilinea(font, lineas=2) -> float:
    """Height in points that `lineas` lines of `font` need, measured with
    AppKit's real metrics (ascender/descender/leading) instead of eyeball-
    doubling one line's height: the same principle theme.text_width()
    already applies to width, now applied to height (Finding 3 of the
    review: the error field lived on the edge with one fixed 17pt line)."""
    alto_linea = math.ceil(font.ascender() - font.descender() + font.leading())
    return alto_linea * lineas

# Size of the legend on each cell of the visual keyboard. 9pt leaves spare
# room even for the widest text ("F13") in the narrowest cell of the keyboard
# (~30pt of real width, measured with theme.text_width): no need to gain
# window size for it to be readable.
_LEYENDA_TECLADO_PT = 9.0

# Text for the orphan row (Task 9, third round, Defect 2): without it, a
# lone key at the end of the keyboard looks randomly placed. In English,
# like the rest of the interface.
NOTA_HUERFANA = "not on this keyboard"
_NOTA_HUERFANA_PT = 10.0
_NOTA_HUERFANA_HOLGURA = 6.0   # air between the measured text and its field
_NOTA_HUERFANA_MARGEN_D = 8.0  # air between the text and the keyboard's right edge


def _nota_huerfana_ancho(font) -> float:
    """Points the orphan row's text needs with `font`, truly measured with
    AppKit (theme.text_width) instead of eyeballed and hardcoded: the
    same lesson _lado_ancho() already applies below -in Task 8 a 58pt
    field silently clipped "either side" and the test that read
    stringValue() passed anyway."""
    return math.ceil(theme.text_width(NOTA_HUERFANA, font)) + _NOTA_HUERFANA_HOLGURA


def _lado_ancho(font) -> float:
    """Points the side field needs so it never cuts off any value of
    shortcuts.side_hint with `font`, truly measured with AppKit.

    Self-defensive on purpose: if side_hint gains a fifth value longer
    than "either side" tomorrow, adding it to _LADOS_POSIBLES is enough —
    the width recomputes itself, there is no point count to also readjust
    by hand that could be forgotten.
    """
    return math.ceil(max(theme.text_width(t, font) for t in _LADOS_POSIBLES)) + _LADO_HOLGURA


def side_label(sid: str, names: list[str]) -> str:
    """'right' / 'left' / 'either side' / '' — the nuance a lone ⌘ symbol
    cannot convey.

    Presentation wrapper: deciding which side(s) actually match at
    runtime is shortcut semantics, not painting, and lives in
    shortcuts.side_hint (tested there without AppKit). It needs `sid` and
    not just the key name because the same name means different things
    per shortcut — "shift" in latch matches both hands (hotkey.py:421),
    but a combo or a side-less key in any other shortcut does not match it.
    """
    return shortcuts.side_hint(sid, names)


# A MacBook keyboard, by rows. (pynput name, synthetic filler name such as
# "arrows", or "" if a purely mute cell were ever needed; today no row uses
# one, see below), relative width). Assigned keys this portrait does not
# contain are added by keyboard_rows() in a separate row:
# _build_keyboard() never draws KEYBOARD_ROWS directly, it draws what
# that function returns.
#
# Letters and digits are named (with the lowercase char that hotkey._norm
# reports) and not just "m": shortcuts.py does not restrict which key may
# enter a multi-key combo (it only validates the single key), so
# cycle_mode can be reassigned to any ctrl+alt+<letter> — if the keyboard
# only knew how to light up "m", that reassignment would show in the row but
# never in the drawing, breaking the rule that both views are the same truth.
#
# The punctuation (`, -, =, [, ], \, ;, ', ,, ., /) and the two special keys
# on the bottom row (⇪ caps lock, fn) ARE named, even though none is
# assignable today (Task 9, Defect 2): unnamed, they were painted as blank
# rectangles and in the screenshot they read as broken keys, not as
# "this cannot be assigned". Naming them gives them a legend via key_label()
# without ever lighting them (lit_keys() never includes them because no
# shortcut can point at them — see keys.validate_custom). The arrow block at
# the end of the bottom row carries the synthetic name "arrows" for the same
# reason (Task 9 fix2, Defect 4): it is several keys and not a single one, so
# it cannot be assignable, but an unlabeled rectangle there reads just as
# broken as the rest. No cell is left unnamed: the gap the number row
# had (Defect 3) was a portrait error -on a real ANSI Mac that row starts
# with the backtick and has no gap between
# "=" and ⌫-, not a legitimate filler cell.
KEYBOARD_ROWS: list[list[tuple[str, float]]] = [
    [("esc", 1.4)] + [(f"f{i}", 1.0) for i in range(1, 13)] + [("f13", 1.0)],
    [("`", 1.0)] + [(d, 1.0) for d in "1234567890"] + [("-", 1.0), ("=", 1.0)] + [("backspace", 1.5)],
    [("tab", 1.5)] + [(c, 1.0) for c in "qwertyuiop"] + [("[", 1.0), ("]", 1.0)] + [("\\", 1.2)],
    [("caps_lock", 1.7)] + [(c, 1.0) for c in "asdfghjkl"] + [(";", 1.0), ("'", 1.0)] + [("enter", 1.6)],
    [("shift", 2.2)] + [(c, 1.0) for c in "zxcvbnm"] + [(",", 1.0), (".", 1.0), ("/", 1.0)] + [("shift_r", 2.2)],
    # The bottom row carries the four modifiers on BOTH sides so that left
    # and right are symmetric: ctrl_r used to be missing and whoever
    # assigned it saw it fall into the "not on this keyboard" row, while
    # cmd_r and alt_r did have a cell. The weight was trimmed off the
    # space bar (5.6 → 4.5) so the row total does not change.
    [("fn", 1.1), ("ctrl", 1.1), ("alt", 1.1), ("cmd", 1.4), ("space", 4.5),
     ("cmd_r", 1.4), ("alt_r", 1.1), ("ctrl_r", 1.1), ("arrows", 2.2)],
]

# Who wins when two shortcuts share a physical key. Dictation first: it is
# the one the user looks for at a glance, and without an explicit rule the
# color would depend on the dict's iteration order.
_PRIORIDAD = ("dictation", "cancel", "latch", "cycle_mode")


def delay_for(names: list[str], anterior_ms: int) -> int:
    """Delay a freshly captured key gets.

    Bumps to the default ONLY if the key needs a guard and the current delay
    does not protect it: with left ⌘ at 0 ms, every ⌘C starts a recording.
    If the key needs no guard, whatever was there is kept — raising to 400
    for someone who chose right ⌘ would change the app's feel unasked, and
    lowering a hand-set 600 would stomp on their choice.
    """
    if names and keys.needs_guard(names[0]) and anterior_ms <= 0:
        return shortcuts.DEFAULT_DELAY_MS
    return anterior_ms


def lit_keys(estado: dict) -> dict[str, str]:
    """{canonical name: sid} of the keys that must light up.

    Derives from shortcuts.matched_keys(), not from canonicalizing each
    name by hand: matched_keys() knows that latch widens to the right-hand
    variant (hotkey.py:421 matches by prefix) and side_label() tells
    exactly the same story (shortcuts.side_hint() uses the same function).
    Before this fix the two views were computed separately and drifted apart
    -the real Task 9 bug: "shift" lit, "shift_r" off, the row
    saying "either side".
    """
    fuera: dict[str, str] = {}
    for sid in _PRIORIDAD:
        nombres = list((estado.get(sid, {}) or {}).get("keys") or [])
        if not nombres:
            continue
        for canon in shortcuts.matched_keys(sid, nombres):
            if canon not in fuera:
                fuera[canon] = sid
    return fuera


# "Normal modifier key" reference for the width of an orphan cell
# (Task 9, third round, Defect 1): the portrait's bottom row is the one
# with the most modifiers together, and "cmd" is exactly the example the
# brief asks for. They are read from KEYBOARD_ROWS instead of hardcoded so
# that if "cmd"'s weight in the portrait changes tomorrow, the orphan
# follows it without having to remember to touch two places.
_FILA_MODIFICADORAS = KEYBOARD_ROWS[-1]
_PESO_MODIFICADOR = next(w for n, w in _FILA_MODIFICADORAS if n == "cmd")
_PESO_FILA_MODIFICADORAS = sum(w for _, w in _FILA_MODIFICADORAS)


def keyboard_rows(estado: dict) -> list[list[tuple[str | None, float]]]:
    """KEYBOARD_ROWS plus, if needed, an extra row with the assigned keys
    that this MacBook portrait does not draw.

    Defect 1 of Task 9 (second round): KEYBOARD_ROWS portrays a specific
    MacBook, but there are assignable keys that portrait does not contain
    -ctrl_r is the first, keys.DICTATION_KEYS:114 already offers it in the
    menu today and a real prefs.json can carry it after shortcuts.migrate()-.
    Without this extra row the list said "⌃ right" and the keyboard lit
    nothing: exactly the contradiction this component exists to prevent.

    It is built on lit_keys(), not on a hand-written list of names, so
    that ANY future assignable key lands here on its own -f14, a numeric
    keypad key, home...- as soon as some shortcut actually uses it,
    without having to remember to touch this module again.

    With no orphans it returns KEYBOARD_ROWS as-is (not one extra row nor
    a different list to compare), so the usual geometry does not change
    for the common case.

    Defect 1 of the third round: each orphan carries the same weight as
    "cmd" in the bottom row (_PESO_MODIFICADOR), not a 1.0 weight that only
    means something compared to the other cells of THAT row -with a single
    cell in the row, weight 1.0 is 100% of the width and the cell draws
    like a space bar, the defect this fix corrects. The rest of the
    reference weight (_PESO_FILA_MODIFICADORAS) is reserved under a
    `None` name: a cell _build_keyboard() counts for width but never
    draws, so the rest of the row stays empty -background, no cell-
    instead of an unlabeled gap that looks like a broken key.
    """
    en_retrato = {n for fila in KEYBOARD_ROWS for n, _ in fila if n}
    huerfanas = sorted(n for n in lit_keys(estado) if n not in en_retrato)
    if not huerfanas:
        return KEYBOARD_ROWS
    fila_huerfana: list[tuple[str | None, float]] = [
        (n, _PESO_MODIFICADOR) for n in huerfanas]
    resto = _PESO_FILA_MODIFICADORAS - _PESO_MODIFICADOR * len(huerfanas)
    if resto > 0:
        fila_huerfana.append((None, resto))
    return [*KEYBOARD_ROWS, fila_huerfana]


def _apagar(casilla):
    """Returns a keyboard cell to its base (unassigned) color.

    Module function, not a method: a name with a single leading underscore
    and no other ("_apagar") is, to PyObjC's selector transformer,
    indistinguishable from a ZERO-argument Objective-C selector
    (`default_selector` only treats the method as pure Python when it has
    ANOTHER underscore besides the leading one, or ends in one). As a
    ShortcutsController method with one argument (`casilla`) it blows up at
    class definition with `objc.BadPrototypeError: '_apagar' expects 0
    arguments`. Outside the class no selector transformation confuses it.
    """
    casilla.layer().setBackgroundColor_(theme.KEYCAP_BG2.CGColor())
    casilla.layer().setBorderWidth_(1.0)
    casilla.layer().setBorderColor_(theme.HAIRLINE.CGColor())


class ShortcutsController(NSObject):
    """Controller + window. NSObject subclass so it can be the buttons'
    target and the window's delegate."""

    def initWithState_onChange_(self, estado, on_change):
        self = objc.super(ShortcutsController, self).init()
        if self is None:
            return None
        self._estado = {sid: dict(fila) for sid, fila in estado.items()}
        self._on_change = on_change
        self._rows = {}          # sid → NSView of the row
        self._fields = {}        # sid → NSView of the chips field (Wispr style)
        self._chips = {}         # sid → [NSView]: one chip per key of the binding
        self._pencils = {}       # sid → NSTextField of the field's pencil ✎
        self._hints = {}         # sid → NSTextField placeholder ("Press keys…")
        self._sides = {}         # sid → NSTextField of the side label
        self._fila_boton = {}    # sid → invisible NSButton that arms the capture
        self._teclado_marco = None  # NSView of the keyboard background (geometry tests)
        self._nota_huerfana = None  # NSTextField of the orphan row, if any
        self._capturing = None    # sid being captured, or None
        self._capture_pressed = []  # keys already pressed in the ongoing capture
        self._chip_font = theme.sf(_CHIP_FONT_PT, _CHIP_PESO)
        self._field_w = 0.0       # shared width of the field (field_width)
        self._reset_boton = None  # NSButton "Reset to defaults"
        self._error_text = ""
        self._error = None        # NSTextField of the row's error message
        self._slider = None       # NSSlider for the Dictation delay
        self._delay_ticks = []    # NSTextField × 5: the 0/200/400/600/800 ms marks
        self._delay_valor = None  # NSTextField of the chosen value ('400 ms')
        # Real HotkeyManager, if any: whoever wires this window into the app
        # menu (Task 11) connects it with attachHotkey_(). None in the tests
        # (and in verificar-ventana.py) — without it, begin_capture_/cancel_capture_
        # only move the window's state, without touching pynput.
        self._hotkey = None
        self._build()
        return self

    # ---------- real hotkey (pynput) ----------
    def attachHotkey_(self, hotkey):
        """Connects the real HotkeyManager that is already running.

        Never instantiates or starts a HotkeyManager: it uses the one it is
        given. There can only be one keyboard.Listener in the process (two
        make pynput call TIS/TSM from two threads and HIToolbox aborts with
        SIGABRT) — begin_capture()/end_capture() on the one already running
        only change which callback keystrokes go to, they do not create or
        restart the listener.
        """
        self._hotkey = hotkey

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
        lado_w = _lado_ancho(lado_font)   # once only: same width in all 4 rows
        # Width of the chips field, also shared by the four rows.
        self._field_w = field_width(self._estado, self._chip_font)

        self._keys = {}          # name → NSView of the cell
        self._legends = {}       # name → NSTextField with the cell's legend
        self._build_keyboard(content, top=84, height=228)
        self._paint_keyboard()

        top = 330   # the Task 9 keyboard spans 84 to 312
        for sid, sc in shortcuts.SHORTCUTS.items():
            # Dictation is the only row with a slider (sc.has_delay) and needs
            # _DELAY_ROW_EXTRA_H extra so that it fits INSIDE its own
            # frame (see _build_row); the rest stay at ROW_H. Adding the
            # same height that was actually used when advancing `top` is what
            # keeps the next row from invading that extra space.
            alto_fila = ROW_H + _DELAY_ROW_EXTRA_H if sc.has_delay else ROW_H
            fila = self._build_row(
                sid, NSMakeRect(PAD, y_(top, alto_fila), W - PAD * 2, alto_fila),
                lado_font, lado_w)
            content.addSubview_(fila)
            self._rows[sid] = fila
            content.addSubview_(theme.rule(
                NSMakeRect(PAD, y_(top + alto_fila, 1), W - PAD * 2, 1), theme.HAIRLINE))
            top += alto_fila + 1

        # Error/notice message for the row in capture (shortcuts.validate()
        # or the caller's rejection via on_change). A single one for the
        # whole window: since only one row can be in capture at a time, the
        # message always belongs to that row even though the field lives
        # outside its rectangle.
        #
        # Finding 3 of the review: the report measured "the three real
        # messages of shortcuts.validate", but _error_text also carries the
        # keys.validate_custom() ones -exactly the ones that appear when
        # capturing a single key, see apply_capture_-, and the real worst
        # case of BOTH validators together sat less than 9pt from the edge
        # on a single line. Two lines (multiline=True, _make_multiline
        # already exists in theme.py) give it real air instead of living on
        # the edge; the height comes from _alto_multilinea(), measured with
        # the font's real metrics, not by eyeball-doubling the old 17. The
        # "top" (H-46) is untouched: as the height grows, the field gains
        # space DOWNWARD -toward the window's edge, where nothing else is-,
        # never upward, where the last shortcut row lives.
        # The Reset button occupies the bottom-right corner; the error
        # field yields exactly that width (it still fits on two lines and
        # the worst-case test watches that the longest text still fits).
        reset_font = theme.sf(11.5)
        reset_w = math.ceil(theme.text_width(_RESET_TXT, reset_font)) + 26
        error_font = theme.sf(11.5)
        error_h = _alto_multilinea(error_font, 2)
        self._error = theme.label(
            NSMakeRect(PAD, y_(H - 46, error_h), W - PAD * 2 - reset_w - 12, error_h),
            "", error_font, theme.TEAL_DARK, multiline=True)
        content.addSubview_(self._error)

        # Hand-drawn pill + invisible button on top, the same pattern as
        # the rows: on this macOS the native NSButton bezel does not
        # composite (verified with screencapture: the title floated boxless,
        # unreadable over the paper — the same failure family as the
        # NSSlider track further up).
        pill = NSView.alloc().initWithFrame_(
            NSMakeRect(W - PAD - reset_w, y_(H - 42, 26), reset_w, 26))
        pill.setWantsLayer_(True)
        pill.layer().setBackgroundColor_(theme.KEYCAP_BG.CGColor())
        pill.layer().setCornerRadius_(13.0)
        pill.layer().setBorderWidth_(1.0)
        pill.layer().setBorderColor_(theme.BTN_BORDER.CGColor())
        pill.addSubview_(theme.label(
            NSMakeRect(0, (26 - 15) / 2, reset_w, 15), _RESET_TXT, reset_font,
            theme.INK_SOFT, align=NSTextAlignmentCenter))
        boton_reset = NSButton.alloc().initWithFrame_(
            NSMakeRect(0, 0, reset_w, 26))
        boton_reset.setBordered_(False)
        boton_reset.setBezelStyle_(0)
        boton_reset.setTitle_("")
        boton_reset.setTarget_(self)
        boton_reset.setAction_("resetDefaults:")
        pill.addSubview_(boton_reset)
        content.addSubview_(pill)
        self._reset_boton = boton_reset

    def _build_row(self, sid, frame, lado_font, lado_w):
        sc = shortcuts.SHORTCUTS[sid]
        row = NSView.alloc().initWithFrame_(frame)
        # Its own layer so the ENTIRE row can be highlighted during capture
        # (feedback: you couldn't see which row you were on). At rest it
        # paints the same paper as the window, so it goes unnoticed.
        row.setWantsLayer_(True)
        row.layer().setCornerRadius_(8.0)
        row.layer().setBackgroundColor_(theme.PAGE_BG.CGColor())
        rw = frame.size.width

        # Only Dictation shifts its content: the other rows measure
        # ROW_H (dy=0, unchanged). With dy=_DELAY_ROW_EXTRA_H, the title/
        # subtitle/keycap/side end up EXACTLY where they would be in a
        # normal ROW_H row (the frame grew at the bottom, not the top: see
        # _build), and the [0, dy) band left free below is where the
        # slider lives — inside the row's frame, not outside it.
        dy = _DELAY_ROW_EXTRA_H if sc.has_delay else 0

        nombres = list(self._estado.get(sid, {}).get("keys") or [])

        # Right-hand zone of the row, from RIGHT to LEFT: [chips field]
        # [side]. The field (single width self._field_w, see field_width)
        # holds one chip per key plus the pencil ✎ — the edit affordance,
        # Wispr style. The real click is received by the whole row's
        # invisible button, further down.
        field_x = rw - _LADO_MARGEN_D - self._field_w
        lado_x = field_x - _LADO_GAP - lado_w
        # Title/subtitle: up to the side label with slack. Dynamic =
        # they never overlap even if the field grows with a long combo.
        titulo_w = max(80, lado_x - 8)

        row.addSubview_(theme.label(
            NSMakeRect(0, 24 + dy, titulo_w, 17), sc.label, theme.sf(13.5, 0.3), theme.INK))
        row.addSubview_(theme.label(
            NSMakeRect(0, 6 + dy, titulo_w, 16), sc.subtitle, theme.sf(11.5), theme.INK_MUTED))

        campo = NSView.alloc().initWithFrame_(
            NSMakeRect(field_x, (ROW_H - _FIELD_H) / 2 + dy, self._field_w, _FIELD_H))
        campo.setWantsLayer_(True)
        campo.layer().setBackgroundColor_(theme.KEYCAP_BG.CGColor())
        campo.layer().setCornerRadius_(8.0)
        campo.layer().setBorderWidth_(1.0)
        campo.layer().setBorderColor_(theme.BTN_BORDER.CGColor())
        # A capture with many keys must not overflow the field and step on
        # the window's edge: it is clipped inside.
        campo.layer().setMasksToBounds_(True)
        row.addSubview_(campo)
        self._fields[sid] = campo

        lapiz = theme.label(
            NSMakeRect(self._field_w - _FIELD_PAD - _PENCIL_W, (_FIELD_H - 16) / 2,
                       _PENCIL_W, 16),
            _PENCIL_TXT, theme.sf(12), theme.INK_MUTED)
        campo.addSubview_(lapiz)
        self._pencils[sid] = lapiz

        hint = theme.label(
            NSMakeRect(_FIELD_PAD, (_FIELD_H - 15) / 2,
                       self._field_w - 2 * _FIELD_PAD - _PENCIL_W, 15),
            _FIELD_HINT, theme.sf(11), theme.INK_MUTED)
        hint.setHidden_(True)
        campo.addSubview_(hint)
        self._hints[sid] = hint

        self._rebuild_chips(sid)

        lado = theme.label(NSMakeRect(lado_x, 17 + dy, lado_w, _LADO_ALTO),
                           side_label(sid, nombres),
                           lado_font, theme.INK_MUTED)
        row.addSubview_(lado)
        self._sides[sid] = lado

        # The whole row arms the capture when clicked (Task 10: "clicking a row
        # starts key capture"), not just the keycap — an invisible button the
        # size of the content band (0..ROW_H, never the slider band)
        # placed ON TOP of the labels to receive the click. It is
        # added before the slider (below) so the latter stays in front
        # within that band if they ever overlapped; today they don't
        # -they live in disjoint bands [0,dy) and [dy,dy+ROW_H)- so the order
        # is just belt and suspenders.
        boton = NSButton.alloc().initWithFrame_(NSMakeRect(0, dy, rw, ROW_H))
        boton.setBordered_(False)
        boton.setBezelStyle_(0)
        boton.setTitle_("")
        boton.setTarget_(self)
        boton.setAction_("filaClicked:")
        row.addSubview_(boton)
        self._fila_boton[sid] = boton

        if sc.has_delay:
            # macOS 26 (Darwin 25, the same one that forced NSWindow instead
            # of NSPanel) draws a freshly created NSSlider as the knob alone,
            # WITHOUT the groove: verified with screencapture, a white circle
            # floating under "Hold to talk" and no trace of a track even
            # looking pixel by pixel. stringValue()/doubleValue() do work
            # -the control responds-, only its native drawing is unseen. A
            # track of our own, hand-drawn and BELOW the real NSSlider
            # (which remains the one receiving the drag), keeps this legible
            # without depending on AppKit painting what it promises.
            pista_y = _DELAY_SLIDER_Y + 9   # vertical center of the slider
            pista = theme.rule(NSMakeRect(6, pista_y, 168, 2), theme.BTN_BORDER)
            row.addSubview_(pista)

            sl = NSSlider.alloc().initWithFrame_(
                NSMakeRect(0, _DELAY_SLIDER_Y, 180, 20))
            sl.setMinValue_(0.0)
            sl.setMaxValue_(float(shortcuts.MAX_DELAY_MS))
            sl.setNumberOfTickMarks_(5)          # 0 / 200 / 400 / 600 / 800
            sl.setAllowsTickMarkValuesOnly_(True)
            ms_inicial = int(self._estado.get(sid, {}).get("delay_ms") or 0)
            sl.setDoubleValue_(float(ms_inicial))
            sl.setTarget_(self)
            sl.setAction_("sliderMoved:")
            row.addSubview_(sl)
            self._slider = sl

            # Finding 1 (CRITICAL) of the review: the slider showed no
            # number at all -neither marks (setNumberOfTickMarks_ paints
            # nothing on this macOS either, same as the track) nor the chosen
            # value-. Picking a delay was guessing, not choosing. What was missing:
            #
            # 1. The marks, below the track, at the knob's REAL
            #    positions: _marca_x() reads knobRectFlipped_ from the
            #    slider itself instead of splitting the control's width
            #    into equal parts (rectOfTickMarkAtIndex_ exists but does
            #    not subtract the knob's width and gives a numbering that
            #    no longer matches where it is -or would be- really seen).
            # 2. The value as text, on the right, in teal and bold.
            #
            # Both widths are measured with theme.text_width(), not by eye:
            # the same lesson as _lado_ancho() and _nota_huerfana_ancho()
            # higher up in this module -an undersized field clips the
            # text silently and stringValue() keeps returning the full
            # text.
            #
            # CAREFUL, this really bit: with align=NSTextAlignmentCenter and
            # a field fitted to the measured width + slack, "200" painted as
            # "20" -verified with screencapture at pixel level, it was not
            # an illusion of the screenshot-, even though theme.text_width()
            # measured correctly and stringValue() kept returning "200". The
            # centered cell computes its own "natural" width in order to
            # center, wider than the measured one, and if the field lacks
            # that spare margin it clips a character even when the field is
            # plenty wide for the REAL width of the text (isolated in a
            # test window: the same text with LEFT align in the same 24pt
            # field clipped nothing). That is why align=Center is NOT used
            # here: centering is done by hand -the x origin subtracts half
            # the measured text width (without slack), not half the field's
            # width- and the label is left with left alignment, which is
            # the one that truly does not clip.
            marca_font = theme.sf(_DELAY_MARCA_PT)
            self._delay_ticks = []
            marcas = _marcas_delay()
            for i, ms in enumerate(marcas):
                texto = _fmt_delay(ms) if i == len(marcas) - 1 else str(ms)
                ancho_texto = theme.text_width(texto, marca_font)
                ancho_campo = math.ceil(ancho_texto) + _DELAY_MARCA_HOLGURA
                cx = self._marca_x(sl, ms)
                marca = theme.label(
                    NSMakeRect(cx - ancho_texto / 2, _DELAY_MARCA_Y, ancho_campo, _DELAY_MARCA_H),
                    texto, marca_font, theme.INK_MUTED)
                row.addSubview_(marca)
                self._delay_ticks.append(marca)

            valor_font = theme.sf(_DELAY_VALOR_PT, _DELAY_VALOR_PESO)
            valor_w = _valor_ancho(valor_font)
            self._delay_valor = theme.label(
                NSMakeRect(180 + _DELAY_VALOR_GAP, _DELAY_SLIDER_Y, valor_w, 20),
                _fmt_delay(ms_inicial), valor_font, theme.TEAL)
            row.addSubview_(self._delay_valor)

        return row

    def _marca_x(self, sl, ms):
        """Center (x axis) of `sl`'s real knob at value `ms`.

        NSSlider paints neither track nor marks on this macOS (see the
        big comment in _build_row), but the knob DOES truly respond
        to the value -stringValue()/doubleValue() work-, so its
        rectangle (knobRectFlipped_) is the real position the mark must
        align to, not an equal split of the control's width:
        rectOfTickMarkAtIndex_ exists but measures the full track
        without subtracting the knob's width, and gives a numbering that
        no longer matches where the real knob is seen -or would be, if
        this macOS painted anything- (checked by hand with both: for a
        180pt slider with a 20pt knob, rectOfTickMarkAtIndex_ spreads
        0/45/90/135/180 but the real knob travels from 10 to 170).

        Raises and lowers doubleValue_ to read it and leaves it as it was:
        it is a query, not a state change, and it does not fire sliderMoved_
        because setDoubleValue_ never sends the action (only a real drag
        does, or an explicit sendAction_to_).
        """
        anterior = sl.doubleValue()
        sl.setDoubleValue_(float(ms))
        rect = sl.cell().knobRectFlipped_(True)
        sl.setDoubleValue_(anterior)
        return rect.origin.x + rect.size.width / 2.0

    def _build_keyboard(self, content, top, height):
        """Draws the keyboard. The cells (and their legends) are created ONCE
        and then only recolored: adding and removing subviews on every repaint
        is what makes a window flicker.

        The rows come from keyboard_rows(self._estado), not from KEYBOARD_ROWS
        directly (Task 9 fix2, Defect 1): that way, if the state carries an
        assigned key the MacBook portrait does not draw, it appears in an
        extra row instead of staying lit in the list and absent here.
        alto_fila is computed from len(filas), not from a constant, so that
        the extra row shares the available height with the others without
        having to enlarge the window.

        A cell without a legend does not say which key it is — lit or not,
        you have to count positions in the row to know, which is exactly
        what a drawn keyboard exists to avoid. Every NAMED cell
        carries its legend, built with key_label([nombre]): the same
        function the keycaps of the four rows already paint with, so the
        keyboard and the list cannot hold two different ideas of how a
        key is spelled. FILLER cells ("") stay without a
        legend: today KEYBOARD_ROWS no longer has any (Defects 3 and 4 of
        this round), but the branch is kept as a safety net in case some
        future portrait needs a purely decorative gap again.

        A `None` name (Task 9, third round, Defect 1) is different from
        "": it counts toward the row's width split -so that the orphan
        cells do not inherit the width reserved for it- but it draws
        NOTHING, not even an unlit cell; if it drew an empty cell it
        would be the same "unlabeled hole that looks like a broken key"
        the `""` case avoids. That is why the loop skips it before
        creating the NSView.
        """
        filas = keyboard_rows(self._estado)
        marco = NSView.alloc().initWithFrame_(
            NSMakeRect(PAD, y_(top, height), W - PAD * 2, height))
        marco.setWantsLayer_(True)
        marco.layer().setBackgroundColor_(theme.KEYCAP_BG.CGColor())
        marco.layer().setCornerRadius_(10.0)
        marco.layer().setBorderWidth_(1.0)
        marco.layer().setBorderColor_(theme.DIVIDER.CGColor())
        content.addSubview_(marco)
        self._teclado_marco = marco

        leyenda_font = theme.sf(_LEYENDA_TECLADO_PT, 0.2)
        leyenda_h = leyenda_font.pointSize() + 8
        nota_font = theme.sf(_NOTA_HUERFANA_PT)
        nota_w = _nota_huerfana_ancho(nota_font)

        # The orphan row is always the last one from keyboard_rows() when
        # there is one (see its docstring): comparing against KEYBOARD_ROWS,
        # not against a hardcoded index, is what keeps this loop correct both
        # if there is an orphan row today and if KEYBOARD_ROWS someday gains
        # a real row and their lengths stop matching.
        indice_huerfana = len(filas) - 1 if len(filas) > len(KEYBOARD_ROWS) else -1

        ancho = marco.frame().size.width - 16
        alto_fila = (height - 16) / len(filas)
        for i, fila in enumerate(filas):
            total = sum(w for _, w in fila)
            x = 8.0
            fy = height - 8 - (i + 1) * alto_fila
            cy = alto_fila - 4
            for nombre, w in fila:
                kw = (ancho * w / total) - 3
                kw = max(kw, 4)
                if nombre is None:
                    x += kw + 3
                    continue
                casilla = NSView.alloc().initWithFrame_(
                    NSMakeRect(x, fy + 2, kw, cy))
                casilla.setWantsLayer_(True)
                casilla.layer().setCornerRadius_(4.0)
                marco.addSubview_(casilla)
                if nombre:
                    self._keys[nombre] = casilla
                    leyenda = theme.label(
                        NSMakeRect(0, (cy - leyenda_h) / 2, kw, leyenda_h),
                        key_label([nombre]), leyenda_font, theme.INK_KEYCAP,
                        align=NSTextAlignmentCenter)
                    casilla.addSubview_(leyenda)
                    self._legends[nombre] = leyenda
                else:
                    _apagar(casilla)
                x += kw + 3

            if i == indice_huerfana:
                # Defect 2 of the third round: say why that key sits alone
                # there. The gap reserved by the `None` above is
                # just the spot for the text -on the right, in the same
                # secondary gray already used by the side label (side_label)
                # of the four rows below.
                nota = theme.label(
                    NSMakeRect(8 + ancho - _NOTA_HUERFANA_MARGEN_D - nota_w,
                               fy + 2 + (cy - (nota_font.pointSize() + 8)) / 2,
                               nota_w, nota_font.pointSize() + 8),
                    NOTA_HUERFANA, nota_font, theme.INK_MUTED,
                    align=NSTextAlignmentRight)
                marco.addSubview_(nota)
                self._nota_huerfana = nota

    def _paint_keyboard(self):
        """Recolors the cells according to self._estado. MUST run on the main
        thread: it is also called by capture, which arrives on the pynput
        listener thread.

        The legend is recolored in the same branch as its cell's fill,
        never in a separate step: dictation lights up in SOLID teal
        (theme.TEAL) and there the dark gray of an unlit legend
        (theme.INK_KEYCAP) would be unreadable, so it switches to theme.PAGE_BG
        (the brand's near-white "paper"). The other shortcuts light up
        in a very light teal (theme.MODEL_BTN_BG) — there the usual dark
        gray already reads fine, so their legend stays the same
        as an unlit one. Keeping it in the same branch as
        setBackgroundColor_ is what prevents fill and legend from
        desyncing if one of the two colors changes tomorrow.

        With a capture armed, the keyboard changes its question: it stops
        telling "what is assigned" and starts telling "what you can pick" —
        see _paint_keyboard_captura. apply/cancel repaint on leaving capture
        and this method returns to the by-assignment view.
        """
        if self._capturing:
            self._paint_keyboard_captura(self._capturing)
            return
        encendidas = lit_keys(self._estado)
        for nombre, casilla in self._keys.items():
            sid = encendidas.get(nombre)
            leyenda = self._legends.get(nombre)
            if sid == "dictation":
                casilla.layer().setBackgroundColor_(theme.TEAL.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.TEAL_DARK.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.PAGE_BG)
            elif sid:
                casilla.layer().setBackgroundColor_(theme.MODEL_BTN_BG.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.MODEL_BTN_BORDER.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.INK_KEYCAP)
            else:
                _apagar(casilla)
                if leyenda is not None:
                    leyenda.setTextColor_(theme.INK_KEYCAP)

    def _paint_keyboard_captura(self, sid):
        """ACTUAL green = usable for this shortcut; gray = not.

        The truth comes from shortcuts.validate — the same validator that
        later accepts or rejects the capture, so the color and the result
        cannot tell different stories. The first attempt painted the usable
        keys with MODEL_BTN_BG (#EDF5F3), which on screen cannot be told
        apart from an unlit gray — Eduardo described it as "the keyboard
        looks complete and the ones you can use are not marked". Contrast IS
        the fix: usable keys light up in the brand's SOLID teal with the
        legend in paper color; the keys already PRESSED in this capture step
        up to TEAL_DARK (live feedback: what you press is reflected here);
        and the rest goes dark with the legend in faint gray — letters,
        reserved keys (esc/shift), other shortcuts' keys and the decorative
        ones (⇪, arrows). Combos (ctrl+shift+m) are still captured even
        though their letters appear gray: the color speaks of the key ALONE.
        MUST run on the main thread, like _paint_keyboard.
        """
        pulsadas = {keys.canon(n) or n for n in self._capture_pressed}
        for nombre, casilla in self._keys.items():
            leyenda = self._legends.get(nombre)
            if nombre in pulsadas:
                casilla.layer().setBackgroundColor_(theme.TEAL_DARK.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.TEAL_DARK.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.PAGE_BG)
            elif shortcuts.validate(sid, [nombre], self._estado)[0]:
                casilla.layer().setBackgroundColor_(theme.TEAL.CGColor())
                casilla.layer().setBorderWidth_(1.0)
                casilla.layer().setBorderColor_(theme.TEAL_DARK.CGColor())
                if leyenda is not None:
                    leyenda.setTextColor_(theme.PAGE_BG)
            else:
                _apagar(casilla)
                if leyenda is not None:
                    leyenda.setTextColor_(theme.INK_MUTED)

    # ---------- capture ----------
    def filaClicked_(self, sender):
        """Action of each row's invisible button: clicking anywhere
        on the row (not just the keycap) arms its capture."""
        for sid, boton in self._fila_boton.items():
            if boton is sender:
                self.begin_capture_(sid)
                return

    @objc.python_method
    def begin_capture_(self, sid):
        """Arms row `sid` to receive the next combination.

        @objc.python_method: without it, PyObjC reads the name as the
        Objective-C selector "begin:capture:" (EVERY underscore -not just
        the trailing one- opens a new keyword; see default_selector in
        objc/_transform.py) and `objc.BadPrototypeError` blows up at class
        definition, because that selector takes 2 arguments and the method
        only receives one (`sid`). Nothing in this window invokes these four
        methods via a Cocoa target/action -only Python calls them (the
        tests, filaClicked_, _on_captured_)-, so they need not be real selectors.

        If a real HotkeyManager is attached (attachHotkey_), it also
        diverts global keystrokes toward _on_captured_: it is the only
        capture path, reusing the begin_capture() of the listener that is
        already running instead of creating its own (see attachHotkey_).
        """
        anterior = self._capturing
        self._capturing = sid
        self._capture_pressed = []
        # Clear guidance while capturing (point 5 of the feedback): the keycap
        # showed "…" and little else guided you; now the status field says what
        # to do and that Esc keeps the shortcut as it was. Cleared when capture ends.
        self._error_text = (
            f"Press the keys for {shortcuts.SHORTCUTS[sid].label}… "
            f"(Esc to keep the current one)"
        )
        if anterior and anterior != sid:
            # Switching rows mid-capture must not leave the previous keycap
            # stranded on "…": that row is no longer the one being
            # captured and has to show its real key again.
            self._refresh_row(anterior)
        self._refresh_row(sid)
        # The keyboard switches to the capture view: usable keys in green,
        # the rest in gray (see _paint_keyboard_captura). Switching rows mid-
        # capture also repaints — each shortcut has its own usable keys.
        self._paint_keyboard()
        if self._hotkey is not None:
            self._hotkey.begin_capture(self._on_captured_)

    @objc.python_method
    def cancel_capture_(self):
        """Esc during capture: leaves the shortcut as it was (macOS
        convention). Also called by the window's close path."""
        sid, self._capturing = self._capturing, None
        self._capture_pressed = []
        self._error_text = ""
        if self._hotkey is not None:
            self._hotkey.end_capture()
        if sid:
            self._refresh_row(sid)
            self._paint_keyboard()  # back to the by-assignment view

    @objc.python_method
    def _on_captured_(self, names):
        """The real `cb` that hotkey.begin_capture() invokes. Arrives on the
        pynput listener thread, never the main one — touching AppKit here
        directly is the usual SIGTRAP/EXC_BREAKPOINT, so everything that
        follows goes through AppHelper.callAfter.

        Esc aborts the capture instead of offering itself as the new key
        (the same convention cancel_capture_ documents): without this cut,
        "cancel" -which is already esc from the factory- would be the only
        shortcut reassignable with Esc, and in any other row a panic Esc
        would read as an assignment attempt instead of as "forget it".
        """
        from PyObjCTools import AppHelper

        if names and names[-1] == "esc":
            AppHelper.callAfter(self.cancel_capture_)
            return
        AppHelper.callAfter(self.apply_capture_, list(names))

    @objc.python_method
    def apply_capture_(self, names):
        """Validates and applies what was captured. Applies nothing that
        does not pass shortcuts.validate() or that the caller rejects."""
        sid = self._capturing
        if not sid:
            return
        # What has been pressed so far is reflected live: chips in the row's
        # field and TEAL_DARK cells on the keyboard, whether validation passes or not.
        self._capture_pressed = list(names)
        ok, msg = shortcuts.validate(sid, list(names), self._estado)
        if not ok:
            self._error_text = msg
            self._refresh_row(sid)
            self._paint_keyboard()
            return

        fila = dict(self._estado.get(sid, {}))
        fila["keys"] = list(names)
        if shortcuts.SHORTCUTS[sid].has_delay:
            fila["delay_ms"] = delay_for(list(names), int(fila.get("delay_ms") or 0))

        aplicado, aviso = self._on_change(sid, fila)
        if not aplicado:
            # The hotkey rejected the change: the window's state reflects
            # what is actually live, never what was requested.
            self._error_text = aviso
            self._refresh_row(sid)
            return

        self._estado[sid] = fila
        self._capturing = None
        self._capture_pressed = []
        self._error_text = aviso or msg    # msg may carry the F5 or fn notice
        if self._hotkey is not None:
            self._hotkey.end_capture()
        self._refresh_row(sid)
        self._layout_fields()   # a longer (or shorter) combo repositions the column
        self._paint_keyboard()
        if fila.get("delay_ms") is not None and self._slider is not None and sid == "dictation":
            self._slider.setDoubleValue_(float(fila["delay_ms"]))
            self._actualizar_valor_delay(int(fila["delay_ms"]))

    @objc.python_method
    def set_delay_(self, ms):
        """The slider. Only Dictation has one (shortcuts.SHORTCUTS[…].has_delay)."""
        ms = max(0, min(shortcuts.MAX_DELAY_MS, int(ms)))
        fila = dict(self._estado.get("dictation", {}))
        fila["delay_ms"] = ms
        aplicado, aviso = self._on_change("dictation", fila)
        if not aplicado:
            self._error_text = aviso
            return
        self._estado["dictation"] = fila
        self._actualizar_valor_delay(ms)
        self._refresh_row("dictation")

    def sliderMoved_(self, sender):
        self.set_delay_(int(round(sender.doubleValue())))

    def _actualizar_valor_delay(self, ms):
        """Syncs the value text ('400 ms') with the real delay.

        Called both from set_delay_ (dragging the slider) and from
        apply_capture_ (the automatic jump to shortcuts.DEFAULT_DELAY_MS
        when choosing a guarded key, see delay_for): both paths change
        delay_ms, and both must leave the visible number in agreement
        with the state, or Finding 1 of the review would repeat itself
        through another path.
        """
        if self._delay_valor is not None:
            self._delay_valor.setStringValue_(_fmt_delay(ms))

    def _rebuild_chips(self, sid, nombres=None):
        """Rebuilds the chips in `sid`'s field: with `nombres` None it paints
        the state's binding; with a list (the live capture) it paints that.

        Unlike the keyboard cells, the chips ARE recreated on every
        repaint: their NUMBER changes with the binding. Only those of the
        affected row are touched, so there is no flicker to fear.
        """
        campo = self._fields.get(sid)
        if campo is None:
            return
        for chip in self._chips.get(sid, ()):
            chip.removeFromSuperview()
        if nombres is None:
            nombres = list(self._estado.get(sid, {}).get("keys") or [])
        textos = chip_texts(nombres)
        chips = []
        x = _FIELD_PAD
        cy = (_FIELD_H - _CHIP_H) / 2
        for t in textos:
            chip = theme.keycap(
                NSMakeRect(x, cy, _chip_ancho(t, self._chip_font), _CHIP_H),
                t, self._chip_font, 5)
            campo.addSubview_(chip)
            chips.append(chip)
            x += _chip_ancho(t, self._chip_font) + _CHIP_GAP
        self._chips[sid] = chips
        hint = self._hints.get(sid)
        if hint is not None:
            # The placeholder only during capture and until the first key.
            hint.setHidden_(bool(textos) or self._capturing != sid)

    def _layout_fields(self):
        """Repositions the four fields when the shared width changes (a new
        longer combo, or a reset that shrinks it). The side label moves
        with them: the whole column travels together, as in _build_row.
        """
        nuevo = field_width(self._estado, self._chip_font)
        if nuevo == self._field_w:
            return
        self._field_w = nuevo
        for sid, campo in self._fields.items():
            rw = self._rows[sid].frame().size.width
            fr = campo.frame()
            campo.setFrame_(NSMakeRect(
                rw - _LADO_MARGEN_D - nuevo, fr.origin.y, nuevo, fr.size.height))
            lapiz = self._pencils.get(sid)
            if lapiz is not None:
                lf = lapiz.frame()
                lapiz.setFrame_(NSMakeRect(
                    nuevo - _FIELD_PAD - _PENCIL_W, lf.origin.y,
                    lf.size.width, lf.size.height))
            hint = self._hints.get(sid)
            if hint is not None:
                hf = hint.frame()
                hint.setFrame_(NSMakeRect(
                    hf.origin.x, hf.origin.y,
                    nuevo - 2 * _FIELD_PAD - _PENCIL_W, hf.size.height))
            lado = self._sides.get(sid)
            if lado is not None:
                sfr = lado.frame()
                lado.setFrame_(NSMakeRect(
                    rw - _LADO_MARGEN_D - nuevo - _LADO_GAP - sfr.size.width,
                    sfr.origin.y, sfr.size.width, sfr.size.height))
            self._rebuild_chips(sid)

    def resetDefaults_(self, _sender):
        """Returns the four shortcuts to factory defaults (Wispr's "Reset
        to default", Eduardo's express request). Each return goes through
        _on_change just like a capture: if the real hotkey rejects one
        (a transient collision with an odd binding), that row stays as it
        is and the error field tells it — a second click usually resolves
        it, with the rest already at factory."""
        if self._capturing:
            self.cancel_capture_()
        avisos = []
        for sid, sc in shortcuts.SHORTCUTS.items():
            fila = dict(self._estado.get(sid, {}))
            fila["keys"] = list(sc.default)
            if sc.has_delay:
                fila["delay_ms"] = delay_for(list(sc.default), 0)
                if fila.get("style") not in keys.MODES:
                    fila["style"] = shortcuts.DEFAULT_STYLE
            aplicado, aviso = self._on_change(sid, fila)
            if not aplicado:
                avisos.append(aviso)
                continue
            self._estado[sid] = fila
        self._error_text = avisos[0] if avisos else ""
        for sid in shortcuts.SHORTCUTS:
            self._refresh_row(sid)
        self._layout_fields()
        self._paint_keyboard()
        if self._slider is not None:
            ms = int(self._estado.get("dictation", {}).get("delay_ms") or 0)
            self._slider.setDoubleValue_(float(ms))
            self._actualizar_valor_delay(ms)

    def _refresh_row(self, sid):
        """Repaints an entire row: highlight, chips field, side and message.

        MUST run on the main thread: apply_capture_ calls it from the
        capture callback, which arrives on the pynput listener thread.
        Writing to AppKit from there is the usual SIGTRAP.
        """
        nombres = list(self._estado.get(sid, {}).get("keys") or [])
        capturando = self._capturing == sid
        fila = self._rows.get(sid)
        if fila is not None and fila.layer() is not None:
            # The row in capture is highlighted as a WHOLE — before, only the
            # keycap border changed and you couldn't see where you were.
            fila.layer().setBackgroundColor_(
                (theme.MODEL_BTN_BG if capturando else theme.PAGE_BG).CGColor())
        campo = self._fields.get(sid)
        if campo is not None:
            campo.layer().setBorderColor_(
                (theme.TEAL if capturando else theme.BTN_BORDER).CGColor())
            campo.layer().setBorderWidth_(2.0 if capturando else 1.0)
        self._rebuild_chips(sid, self._capture_pressed if capturando else None)
        lado = self._sides.get(sid)
        if lado is not None:
            lado.setStringValue_(side_label(sid, nombres))
        if self._error is not None:
            self._error.setStringValue_(self._error_text)

    # ---------- lifecycle ----------
    def show(self):
        # Voooxly is a menu-bar app: makeKeyAndOrderFront() alone does not
        # steal focus from the app that was in front and the window opens
        # BEHIND it (the user loses sight of it). Activating the app brings
        # it forward; orderFrontRegardless is the belt for the case where
        # activate is not enough (workspaces, full-screen apps).
        from AppKit import NSApp

        self._win.center()
        NSApp.activateIgnoringOtherApps_(True)
        self._win.makeKeyAndOrderFront_(None)
        self._win.orderFrontRegardless()

    def close(self):
        try:
            self._win.close()
        except Exception:
            log.debug("Shortcuts window close() failed", exc_info=True)

    def windowShouldClose_(self, _sender):
        # Closing the window mid-capture must not leave the pynput listener
        # diverted forever toward a window that no longer exists.
        if self._capturing:
            self.cancel_capture_()
        return True
