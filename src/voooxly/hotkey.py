"""Global hotkeys with pynput. Requires the Accessibility permission on macOS.

IMPORTANT: we use ONE SINGLE keyboard.Listener for everything. If several
listeners are started (e.g. GlobalHotKeys + Listener), each one calls TIS/TSM
from its own thread and HIToolbox aborts the process with SIGABRT ("Text Input
Sources API is being called in two threads concurrently"). A single listener
avoids the race.

Dictation button modes:
- "hold"  (push-to-talk, Wispr-style): you hold the key down to speak,
  release it to finish.
- "toggle": press to start, press again/go quiet to finish.

cycle_mode (Ctrl+Shift+M) is detected as a combo inside the same listener.
paste_last has no keyboard shortcut or method of its own: ⌘V covers the
common case and the Recent menu (app.py) covers re-pasting an earlier dictation.

cancel (Esc) discards the in-flight dictation: the app decides whether it applies
(only while recording or processing), so firing it on every system Esc is cheap.

latch (Shift, hold mode only): if the dictation is running long, press latch
WITHOUT releasing the dictation key and the recording gets pinned — you can let
go. A tap of the dictation key ends it. Esc also undoes the latch.

guard (toggle_guard): the LEFT modifiers are used in combos constantly
(⌘C, ⌘V, ⌘Tab), so firing the dictation on key-down would make them useless
as a dictation key — whatever toggle_mode is. With the guard, neither
on_start() (hold mode) nor on_toggle() (toggle mode) is called on the press:
a guard_delay timer is armed and only fires if the key is still alone when it
expires; which callback fires depends on toggle_mode at that instant, not on
which mode was active when the timer was armed. Any other key inside the
window cancels it. Keys without the guard keep the usual instant trigger,
in any mode.

FIX: before, self._guard was only consulted inside `toggle_mode == "hold"`
— in toggle mode the dictation key went through _toggle_combo and fired
on_toggle() instantly, without ever passing through the window. With Dictation
key = Left ⌘ and Dictation style = "Press to start / stop" (two menu settings
each valid on their own), any ⌘C/⌘V/⌘S started a recording that only stopped
by tapping ⌘ alone again. See tests/test_guard_hotkey.py.
"""
from __future__ import annotations

import logging
import threading

from pynput import keyboard

from . import keys

log = logging.getLogger("voooxly.hotkey")


# macOS ANSI virtual keycodes (kVK_ANSI_*) → letter. Fallback for when
# pynput brings no char (e.g. with Cmd held on some layouts).
_VK_DARWIN = {
    0: "a", 11: "b", 8: "c", 2: "d", 14: "e", 3: "f", 5: "g", 4: "h",
    34: "i", 38: "j", 40: "k", 37: "l", 46: "m", 45: "n", 31: "o", 35: "p",
    12: "q", 15: "r", 1: "s", 17: "t", 32: "u", 9: "v", 13: "w", 7: "x",
    16: "y", 6: "z",
}

# kVK_Function: the fn/🌐 key. pynput does receive its flagsChanged (which is
# why the usual single listener is enough) but doesn't have it in
# _MODIFIER_FLAGS, so its `is_press = flags & 0` comes out 0 and it delivers
# BOTH transitions as on_release. _norm names it and _on_release straightens
# it out with _fn_down().
_VK_FN = 0x3F


def _fn_down() -> bool:
    """Is the fn key physically pressed RIGHT NOW, according to the system?

    CGEventSourceFlagsState reads the live HID state, not the event: that is
    what makes it possible to tell the press from the release when pynput
    delivers both the same. Tests stub it (there's no physical key in a test);
    if Quartz isn't there (or changes API), False leaves fn unsupported
    instead of taking down the whole listener.
    """
    try:
        from Quartz import (
            CGEventSourceFlagsState,
            kCGEventFlagMaskSecondaryFn,
            kCGEventSourceStateHIDSystemState,
        )

        return bool(
            CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState)
            & kCGEventFlagMaskSecondaryFn
        )
    except Exception:
        return False


def _norm(key) -> str:
    """Normalizes a pynput key to a stable lowercase name.

    macOS GOTCHA: with Ctrl held, a letter does NOT arrive as its char but as
    its control character (Ctrl+M = '\\r', Ctrl+V = '\\x16'…), so the combo
    ctrl+shift+m would never match comparing raw chars. The mapping is undone
    (\\x01-\\x1a → a-z) and, if there is no char, we fall back to the ANSI
    virtual keycode.
    """
    if isinstance(key, keyboard.KeyCode):
        ch = key.char
        if ch and len(ch) == 1 and 1 <= ord(ch) <= 26:
            return chr(ord(ch) + 96)  # control char → letter
        if ch:
            return ch.lower()
        vk = getattr(key, "vk", None)
        if vk == _VK_FN:
            return "fn"
        return _VK_DARWIN.get(vk, "")
    name = getattr(key, "name", "").lower()
    # unify cmd/cmd_l/cmd_r for combos but keep cmd_r for hold
    return name


# Canonicalization lives in keys.py: it's dictionary arithmetic, doesn't touch
# pynput, and shortcuts.py also needs it to detect conflicts. The private name
# _canon is kept here because _combo_names, __init__ and reconfigure use it,
# and renaming them adds nothing.
_canon = keys.canon
_ALIAS_MISMA_TECLA = keys._ALIAS_MISMA_TECLA


def _combo_names(keys: list[str]) -> frozenset[str]:
    return frozenset(_canon(k) for k in keys)


def _warm_input_sources() -> None:
    """Gets macOS's input-source list built BEFORE creating the listener, and
    from the thread that calls this (which must be the main one).

    pynput starts its listener with `with keycode_context()` (_darwin.py:272),
    and that contextmanager calls TISGetInputSourceProperty from the
    listener's own thread. macOS requires the TIS/TSM APIs to go through the
    main thread, but only checks it when it has to REBUILD the list: with the
    cache warm the call passes without noise, which is why this worked for
    months. When something invalidates it —switching keyboard language, or
    pressing F5, which on a Mac is the system Dictation key— the next start
    rebuilds it from the wrong thread and HIToolbox kills the process with
    SIGTRAP in dispatch_assert_queue.

    Touching it here first leaves it cached, so the listener's call no longer
    rebuilds anything. A race window of milliseconds remains (the source
    changing right between this line and the listener start), but it is
    incomparably narrower than the one before.

    Never raises: it's a precaution, and pynput._util is private API that
    could move in a future version. If it disappears, we go back to the
    previous behavior instead of leaving the app without hotkeys.
    """
    try:
        from pynput._util.darwin import keycode_context

        with keycode_context():
            pass
    except Exception:
        log.debug("Couldn't pre-warm TIS/TSM before the listener", exc_info=True)


class HotkeyManager:
    def __init__(
        self,
        toggle_mode: str,
        toggle_keys: list[str],
        cycle_keys: list[str],
        on_toggle,
        on_start,
        on_stop,
        on_cycle,
        cancel_keys: list[str] | None = None,
        on_cancel=None,
        latch_keys: list[str] | None = None,
        on_latch=None,
        toggle_guard: bool = False,
        guard_delay: float = 0.3,
    ):
        self.toggle_mode = toggle_mode
        self.on_toggle = on_toggle
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_cycle = on_cycle
        self.on_cancel = on_cancel
        self.on_latch = on_latch

        # dictation key (hold mode: one single key)
        self._toggle_key = _canon(toggle_keys[0]) if toggle_keys else None
        # cancel key: a single key (Esc by default) or a combo such as
        # ctrl+shift+x. _cancel_key matches a lone key; _cancel_combo matches
        # the full set pressed at once (like cycle_mode). Previously only
        # _cancel_key existed, so a cancel combo only matched the FIRST
        # key and fired wrongly or never (point 1 of the feedback).
        self._cancel_key = (
            _canon(cancel_keys[0]) if cancel_keys and len(cancel_keys) == 1
            else None
        )
        self._cancel_combo = (
            _combo_names(cancel_keys) if cancel_keys and len(cancel_keys) > 1
            else None
        )
        # latch key (a single one; "shift" also matches shift_r)
        self._latch_key = _canon(latch_keys[0]) if latch_keys else None
        self._held = False
        self._latched = False
        # cycle combo, and also the toggle if mode "toggle" with a combo
        self._cycle_combo = _combo_names(cycle_keys) if cycle_keys else None
        self._toggle_combo = _combo_names(toggle_keys) if (toggle_mode != "hold" and toggle_keys) else None

        self._pressed: set[str] = set()
        self._pressed_lock = threading.Lock()
        self._listener: keyboard.Listener | None = None

        # Decision window (left modifiers only). See the header.
        self._guard = bool(toggle_guard)
        self._guard_delay = float(guard_delay)
        self._guard_timer: threading.Timer | None = None
        # Generation counter: invalidates the timer of an already-released
        # press. Without it, fast typing fires the timer of an old press
        # too late and starts a ghost recording.
        self._guard_seq = 0
        self._guard_lock = threading.Lock()
        # _held = the key is physically pressed.
        # _started = on_start() has actually been called.
        # With the guard the two diverge: the key can be pressed without the
        # recording having started. Without that distinction, releasing inside
        # the window would fire an on_stop() for a recording that never started.
        self._started = False

        # Capture mode: while there is a callback, _on_press diverts everything
        # here and fires no action. It serves the Shortcuts window WITHOUT
        # creating a second listener, which would abort the process (see header).
        self._capture_cb = None
        self._capture_orden: list[str] = []

    # --- decision window ---
    def _arm_guard(self) -> None:
        with self._guard_lock:
            self._guard_seq += 1
            seq = self._guard_seq
            t = threading.Timer(self._guard_delay, self._guard_fire, args=(seq,))
            t.daemon = True
            self._guard_timer = t
            t.start()

    def _cancel_guard(self) -> None:
        with self._guard_lock:
            self._guard_seq += 1  # invalidates any firing already in flight
            t, self._guard_timer = self._guard_timer, None
        if t is not None:
            t.cancel()

    def _guard_fire(self, seq: int) -> None:
        with self._guard_lock:
            if seq != self._guard_seq or not self._held:
                return
            # _started only means "on_start() has actually been called" (see
            # the attribute's comment in __init__): in toggle mode what
            # fires is on_toggle(), not on_start(), so leaving it False
            # there is correct, not an oversight.
            hold = self.toggle_mode == "hold"
            if hold:
                self._started = True
        threading.Thread(target=self.on_start if hold else self.on_toggle, daemon=True).start()

    def reconfigure(
        self,
        toggle_key: str,
        toggle_mode: str,
        guard: bool,
        guard_delay: float | None = None,
    ) -> bool:
        """Changes the dictation key without recreating the manager.

        Lives here and not in app.py because rebuilding _toggle_combo when
        switching to "toggle" mode is an internal detail of this class: the
        caller only knows which key it wants. The listener is NOT restarted
        here — that's up to the caller, who is the only one who knows whether
        it is on the main thread (and starting two listeners at once aborts
        the process).

        Returns False and leaves the previous configuration intact if the key
        canonicalizes to the same one that already has an owner (latch or
        cancel). Today that collision is prevented by keys._RESERVADAS, but
        that only protects whoever goes through keys.resolve/validate_custom
        before getting here — whoever calls reconfigure() directly skips it
        entirely. Without this check,
        reconfigure(toggle_key="shift_l", ...) leaves _toggle_key == _latch_key
        == "shift": the latch ends up dead (the `return` of the hold branch of
        the dictation itself never lets it get there) and the right shift
        pins silently instead of dictating — the same silent failure as always.

        No exception is raised: the caller is AppKit menu code, and an
        uncaught exception there takes the whole app down over a badly chosen
        key. Returning False lets the caller decide how to warn (e.g. not
        closing the submenu) without risking the process.
        """
        canon = _canon(toggle_key)
        if canon and (canon == self._latch_key or canon == self._cancel_key):
            log.warning(
                "reconfigure(%r) rejected: canonicalizes to %r, which is already in "
                "use (latch=%r, cancel=%r). Keeping the previous key (%r).",
                toggle_key, canon, self._latch_key, self._cancel_key, self._toggle_key,
            )
            return False

        self._toggle_key = canon
        self.toggle_mode = toggle_mode
        self._guard = bool(guard)
        # guard_delay=None keeps the current one: someone only changing the
        # style has no reason to know which delay is set.
        if guard_delay is not None:
            self._guard_delay = float(guard_delay)
        self._toggle_combo = (
            None if toggle_mode == "hold" else _combo_names([self._toggle_key])
        )
        self._cancel_guard()
        self._held = False
        self._started = False
        self._latched = False
        return True

    def rebind(self, sid: str, names: list[str]) -> bool:
        """Changes cycle_mode / latch / cancel with the listener already running.

        Lives here and not in app.py for the same reason as reconfigure():
        rebuilding a combo frozenset is an internal detail of this class. The
        listener is NOT restarted — _on_press re-reads these attributes on
        every event, and starting a second listener aborts the process with
        SIGABRT.

        Returns False if the binding collides with the dictation key. That
        collision leaves the shortcut silently dead: the hold branch of
        _on_press returns before reaching latch or cancel, so the
        user would see the key assigned in the window and nothing would
        happen. shortcuts.validate() already filters it beforehand, but
        whoever calls rebind() directly would skip it entirely.

        No exception is raised: the caller is AppKit code and an uncaught
        exception there takes the app down.
        """
        canon = [_canon(n) for n in names] if names else []
        if not canon:
            return False
        if self._toggle_key in canon:
            log.warning(
                "rebind(%r, %r) rejected: collides with the dictation key (%r).",
                sid, names, self._toggle_key,
            )
            return False

        if sid == "cycle_mode":
            self._cycle_combo = frozenset(canon)
        elif sid == "latch":
            self._latch_key = canon[0]
        elif sid == "cancel":
            # Combo vs lone key (see __init__): a cancel combo matches the
            # full set, not just the first key.
            if len(canon) > 1:
                self._cancel_combo = frozenset(canon)
                self._cancel_key = None
            else:
                self._cancel_combo = None
                self._cancel_key = canon[0]
        else:
            log.warning("rebind(%r): id desconocido.", sid)
            return False
        log.info("Shortcut %s reassigned to %s.", sid, canon)
        return True

    # --- capture mode (Shortcuts window) ---
    @property
    def capturing(self) -> bool:
        return self._capture_cb is not None

    def begin_capture(self, cb) -> None:
        """Diverts key presses to `cb` and stops firing actions.

        `cb` receives the list of names pressed so far, in press order, with
        the same names _norm() reports at runtime — which is exactly what
        makes the chosen key actually match later.
        """
        self._cancel_guard()
        # If a real recording is in progress (_started) or pinned with latch
        # (_latched), entering capture mode orphans it: _on_press is going to
        # swallow every incoming event -including Esc- while capturing,
        # so neither on_cancel nor the next on_stop of the normal flow will
        # ever see it again. It has to be closed here, with on_stop() (not
        # on_cancel()) because the user already said something: transcribing
        # it and keeping it in the history is recoverable if the paste lands
        # in the Shortcuts window; throwing away the recorded audio is not.
        if self._started or self._latched:
            threading.Thread(target=self.on_stop, daemon=True).start()
        self._held = False
        self._started = False
        self._latched = False
        with self._pressed_lock:
            self._pressed.clear()
        self._capture_orden = []
        self._capture_cb = cb

    def end_capture(self) -> None:
        """Back to normal behavior. Idempotent on purpose: closing the
        window mid-capture also calls this, and failing to restore
        would leave the app without hotkeys until restart."""
        self._capture_cb = None
        self._capture_orden = []
        with self._pressed_lock:
            self._pressed.clear()

    # --- listener callbacks ---
    def _on_press(self, key):
        name = _norm(key)
        if not name:
            return

        # Capture: swallows the whole event. Goes before everything else so
        # that neither the dictation, nor the latch, nor the combos see the
        # key — picking the right ⌘ as the dictation key cannot start recording.
        cb = self._capture_cb
        if cb is not None:
            if name not in self._capture_orden:
                self._capture_orden.append(name)
            try:
                cb(list(self._capture_orden))
            except Exception:
                # The callback is AppKit code: if it blows up, the app cannot
                # be left without hotkeys forever.
                log.exception("Capture callback failed")
            return

        with self._pressed_lock:
            already = name in self._pressed
            self._pressed.add(name)
            raw = frozenset(self._pressed)

        # View for matching combos: canonicalizes the names (unifies left
        # sides: shift_l→shift, ctrl_l→ctrl) and, in HOLD MODE with a single
        # dictation key, removes that key. The dictation key stays held
        # during the WHOLE dictation, so without removing it the snapshot
        # of a combo (e.g. cancel=ctrl+shift) would always carry cmd_r inside
        # and would never match while dictating — the text got pasted anyway
        # after cancelling. Only in hold: in toggle, the dictation key IS the
        # combo (_toggle_combo) and removing it would break the trigger.
        # combo_view is what cancel/toggle/cycle combos use.
        combo_view = frozenset(_canon(k) for k in raw)
        if self._toggle_key and self.toggle_mode == "hold":
            combo_view = combo_view - {self._toggle_key}

        # Any key other than the dictation key closes the window: the
        # user is doing a combo (⌘C), not dictating. Outside the
        # window it cancels nothing — mid-way through a dictation already
        # started, a stray key cannot throw away the recorded audio.
        if name != self._toggle_key:
            self._cancel_guard()

        # --- dictation: hold always goes through here; toggle only when the
        # key needs the guard (Fix 1) — without the guard, toggle remains an
        # instant tap via _toggle_combo, further down. Before this fix
        # this branch required plain `toggle_mode == "hold"`, so a
        # guarded key in toggle mode never went through _arm_guard(): the
        # menu and the README advertised a 300ms delay that didn't exist.
        if name == self._toggle_key and (self.toggle_mode == "hold" or self._guard):
            if self.toggle_mode == "hold" and self._latched:
                # tap with the recording pinned = finish. `already` filters
                # the autorepeat of a key kept held after the tap.
                if not already:
                    self._latched = False
                    self._started = False
                    threading.Thread(target=self.on_stop, daemon=True).start()
                return
            if not self._held and not already:
                self._held = True
                if self._guard:
                    self._arm_guard()   # fires only if it stays alone the whole window
                else:
                    self._started = True
                    threading.Thread(target=self.on_start, daemon=True).start()
            return

        # --- latch: pin the recording while the dictation key is held ---
        # Only pins if the latch key comes ALONE with the dictation key: if
        # another key is pressed (e.g. ctrl, because you're building
        # ctrl+shift to cancel), the combo goes to cancel, not to latch.
        # Without this guard, the second key of the cancel combo fired the
        # latch and the cancel never got to match.
        raw_without_toggle = (
            raw - {self._toggle_key} if self._toggle_key else raw
        )
        if (
            self.toggle_mode == "hold"
            and self._latch_key
            and self._started          # can't pin what hasn't started
            and not self._latched
            and len(raw_without_toggle) == 1   # only the latch key, no extras
            and (name == self._latch_key or name.startswith(self._latch_key + "_"))
        ):
            self._latched = True
            if self.on_latch:
                threading.Thread(target=self.on_latch, daemon=True).start()
            return

        if already:
            return  # autorepeat: don't re-fire combos or the cancel

        # --- cancel dictation (Esc or a combo such as ctrl+shift+x) ---
        # _cancel_combo matches the COMPLETE set pressed at once (via
        # combo_view, which removes the dictation key in hold); _cancel_key
        # matches a lone key. Only one of the two is active by design (see
        # __init__/rebind), so the order between the two branches doesn't matter.
        if self.on_cancel:
            if self._cancel_combo is not None:
                if combo_view == self._cancel_combo:
                    self._latched = False  # a cancelled dictation stops being pinned
                    self._started = False
                    threading.Thread(target=self.on_cancel, daemon=True).start()
                    return
            elif name == self._cancel_key:
                self._latched = False
                self._started = False
                threading.Thread(target=self.on_cancel, daemon=True).start()
                return

        # --- combos (includes toggle in toggle mode if it's a combo) ---
        if self._toggle_combo and combo_view == self._toggle_combo:
            threading.Thread(target=self.on_toggle, daemon=True).start()
            return
        if self._cycle_combo and combo_view == self._cycle_combo:
            threading.Thread(target=self.on_cycle, daemon=True).start()
            return

    def _on_release(self, key):
        name = _norm(key)
        if not name:
            return
        # fn ALWAYS arrives as a release (see _VK_FN): if the system says the
        # fn bit is still down, this is the press in disguise and it is routed
        # to the press. Goes before the capture cut-off so the Shortcuts
        # window can capture fn like any other key.
        if name == "fn" and _fn_down():
            self._on_press(key)
            return
        if self._capture_cb is not None:
            return
        with self._pressed_lock:
            self._pressed.discard(name)

        if self.toggle_mode == "hold" and name == self._toggle_key:
            self._held = False
            self._cancel_guard()   # releasing inside the window = it never started
            if not self._started:
                return             # nothing to stop
            if self._latched:
                return             # pinned: keeps recording until the next tap
            self._started = False
            threading.Thread(target=self.on_stop, daemon=True).start()
            return

        # --- toggle with guard (Fix 1): releasing before the window
        # expires cancels the attempt — the toggle only counts if the key
        # held out alone for the full time, just like the start in hold
        # mode. Without this cancel, a loose tap would leave the timer
        # alive and fire a ghost toggle after the release. ---
        if self.toggle_mode != "hold" and self._guard and name == self._toggle_key:
            self._held = False
            self._cancel_guard()

    def start(self) -> None:
        _warm_input_sources()
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()
        log.info("Hotkeys active (mode %s, dictation key: %s).", self.toggle_mode, self._toggle_key)

    def stop(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                log.debug("listener.stop() failed", exc_info=True)
            # JOIN: without it, the old listener's thread can still be alive
            # when start() creates the next one → two listeners at once, each
            # calling TIS/TSM from its own thread and HIToolbox aborts with
            # SIGABRT (the crash this module's header documents). Restarting
            # the hotkey (e.g. after onboarding) requires the old one to be
            # DEAD first.
            try:
                self._listener.join(timeout=2.0)
            except Exception:
                log.debug("listener.join() failed", exc_info=True)
            self._listener = None
