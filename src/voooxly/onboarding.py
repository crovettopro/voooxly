"""First-run assistant in TWO steps, with product-level design.

  Step 1 — Configure   : permissions (mic, accessibility), voice model, optional AI.
  Step 2 — How to dictate: the dictation key and the shortcuts, with a hero ⌘.

Aesthetics (v2 redesign): **teal + paper** branding (voooxly.com + the app icon),
serif titles (Iowan Old Style), rows separated by hairlines instead of cards.
The state is re-checked every second with an NSTimer: when the user grants
Accessibility in Settings, the row checks itself off without restarting Voooxly.

Three macOS bugs this version fixes:
- System Settings blocked by the window: on pressing "Open Settings" we hide
  the onboarding (orderOut); the NSTimer shows it again when the permission is
  granted (or when the user comes back to the app).
- Mute hotkey the first time: pynput starts without Accessibility and the event
  tap isn't created; granting the permission midway or even restarting the
  listener in-process isn't enough (macOS doesn't re-evaluate the permission in
  the same process). That's why on_finish RELAUNCHES the app as a new process
  (see app.py _on_onboarding_done), and why closing the window with the red
  button also fires finish_.
- Two listeners at once: hotkey.stop() join()s the old listener.

macOS RESTRICTIONS learned through crashes:
- NSWindow can only be instantiated on the main thread (same as overlay.py).
- The window goes at FLOATING LEVEL: menu-bar app without Dock, so it doesn't
  get lost behind while the model downloads. On opening Settings it hides (see above).

"Dead" buttons on macOS 26 (Tahoe) — the bug that cost the most:
  The app is accessory (LSUIElement) and show() is called BEFORE the rumps run
  loop starts. On macOS 26 that leaves the window visible but NOT active/key,
  and the window server swallows the first click as "activate app" instead of
  delivering it to the button: mic and accessibility seemed unresponsive. The
  cure is promoting the app to Regular for the duration of the onboarding (a
  true foreground window, with focus and a Dock tile — which also makes
  minimize useful) and re-activating ONCE the run loop is already running. On
  finishing, Accessory is restored.
  The microphone button, additionally, sends to Settings if the permission was
  already denied: requestAccess only opens the prompt when it's "undecided".

Optional AI: "Connect AI" delegates to a callback (on_connect_ai) that opens
app.py's provider + key selector (an already proven flow). What's connected
persists across the relaunch. Nobody has AI on first launch, so this is NOT a
"test" button — it's a "connect", optional, that turns dictation into more
than transcribing (it cleans, formats and rewrites what's dictated).
"""
from __future__ import annotations

import logging
import threading
import time

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSFloatingWindowLevel,
    NSImageView,
    NSTextAlignmentCenter,
    NSTextAlignmentLeft,
    NSTextAlignmentRight,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSAttributedString, NSMakeRect, NSMakeSize, NSObject, NSTimer

from . import i18n, setup_checks, stt
from .theme import (  # noqa: F401  (re-exported: the pages use them)
    BTN_BORDER, BTN_GHOST_TEXT, CTA_DISABLED_BG, CTA_DISABLED_TEXT, DIVIDER,
    HAIRLINE, INK, INK_KEYCAP, INK_MUTED, INK_SOFT, KEYCAP_BG, KEYCAP_BG2,
    KEYCAP_EDGE, MODEL_BTN_BG, MODEL_BTN_BORDER, PAGE_BG, PENDING_RING,
    PROGRESS_TRACK, TEAL, TEAL_DARK,
)
from .theme import hex_ as _hex
from .theme import keycap as _keycap
from .theme import label as _label
from .theme import mono as _mono
from .theme import rule as _rule
from .theme import serif as _serif
from .theme import sf as _sf

log = logging.getLogger("voooxly.onboarding")

W, H = 580, 700
PAD = 40


def _y(top, h):
    """Converts a 'y from the top' (as in the design) to the bottom-left origin."""
    return H - top - h


def cta_label() -> str:
    """Text of the main CTA ('Continue →'), already translated.

    Single source for _build_page1 (paints it the first time) and _refresh
    (repaints it every second via NSTimer): before, _refresh used the English
    literal and stomped on the translation set when building the window. Pure,
    no AppKit, so it can be tested without instantiating anything.
    """
    return i18n.t("Continue →")


# key, title, explanation, button text, style. The order is check_all()'s.
STEPS = [
    ("mic", "Microphone",
     "So Voooxly can hear you. Your voice never leaves this Mac.", "Allow", "ghost"),
    ("accessibility", "Accessibility",
     "Lets Voooxly type into any app, use the dictation hotkey, and read the "
     "word you fix to learn it.", "Open Settings", "ghost"),
    ("model", "Speech model",
     "One-time 547 MB download. Runs fully offline after that.", "Download", "tint"),
    ("ai", "AI engine",
     "Optional, but it makes Voooxly more than a dictation tool: connect Claude, "
     "ChatGPT or Gemini and it cleans up, formats and rewrites what you say. "
     "You can also add it later from the menu bar.", "Connect AI", "text"),
]


class OnboardingController(NSObject):
    """Controller + window. NSObject subclass so it can be the buttons' target
    and the window's delegate (so closing with the red button = finish_)."""

    def initWithFinish_(self, on_finish):
        return self.initWithFinish_connectAI_(on_finish, None)

    def initWithFinish_connectAI_(self, on_finish, on_connect_ai):
        self = objc.super(OnboardingController, self).init()
        if self is None:
            return None
        self._on_finish = on_finish
        self._on_connect_ai = on_connect_ai
        self._rows = {}
        self._row_views = {}
        self._downloading = False
        self._timer = None
        self._page = 1
        self._hidden_for_settings = False
        self._hide_t = 0.0
        self._page1 = []
        self._page2 = []
        self._model_fill = None
        self._model_track_w = 1.0
        self._model_pct = None
        self._build()
        return self

    # ---------- construction ----------
    def _build(self):
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered,
            False,
        )
        self._win.setTitle_(i18n.t("Welcome to Voooxly"))
        self._win.setReleasedWhenClosed_(False)
        self._win.setLevel_(NSFloatingWindowLevel)
        self._win.setDelegate_(self)
        self._win.setBackgroundColor_(PAGE_BG)
        content = self._win.contentView()

        # Shared STEP label (top right, both pages).
        self._step_label = _label(NSMakeRect(W - PAD - 160, _y(38, 12), 160, 12),
                                  i18n.t("STEP 1 OF 2"), _mono(10, 0.3), INK_MUTED,
                                  align=NSTextAlignmentRight)
        content.addSubview_(self._step_label)

        self._build_page1(content)
        self._build_page2(content)
        self._show_page(1)
        self._refresh()

    # ---------------- page 1: configure ----------------
    def _build_page1(self, content):
        add = self._page1.append

        icon = NSImageView.alloc().initWithFrame_(NSMakeRect(PAD, _y(32, 60), 60, 60))
        try:
            icon.setImage_(NSApplication.sharedApplication().applicationIconImage())
        except Exception:
            log.debug("Couldn't load the icon in onboarding", exc_info=True)
        content.addSubview_(icon); add(icon)

        title = _label(NSMakeRect(PAD, _y(114, 34), W - 2 * PAD, 34),
                       i18n.t("Welcome to Voooxly"), _serif(27, semibold=True), INK)
        content.addSubview_(title); add(title)
        sub = _label(NSMakeRect(PAD, _y(154, 20), W - 2 * PAD, 20),
                     i18n.t("Dictate anywhere — Voooxly types what you say."),
                     _sf(14.5), INK_SOFT)
        content.addSubview_(sub); add(sub)

        div = _rule(NSMakeRect(PAD, _y(196, 1), W - 2 * PAD, 1), DIVIDER)
        content.addSubview_(div); add(div)

        sec = _label(NSMakeRect(PAD, _y(215, 14), W - 2 * PAD, 14),
                     i18n.t("A COUPLE OF ONE-TIME STEPS"), _sf(11, 0.3), INK_MUTED)
        content.addSubview_(sec); add(sec)

        rows_h = {"mic": 62, "accessibility": 62, "model": 72, "ai": 96}
        t = 241
        first = True
        for key, name, desc, action, style in STEPS:
            h = rows_h[key]
            if not first:
                hair = _rule(NSMakeRect(PAD, _y(t, 1), W - 2 * PAD, 1), HAIRLINE)
                content.addSubview_(hair); add(hair)
            first = False
            row = self._build_row(key, name, desc, action, style, NSMakeRect(PAD, _y(t, h), W - 2 * PAD, h))
            content.addSubview_(row); add(row)
            self._row_views[key] = row
            t += h

        foot = _label(NSMakeRect(PAD, 84, W - 2 * PAD, 32),
                      i18n.t("Takes about 2 minutes. You can change any of "
                             "this later from the menu bar (🎙 icon)."),
                      _sf(12), INK_MUTED,
                      align=NSTextAlignmentCenter, multiline=True)
        content.addSubview_(foot); add(foot)

        self._done = _cta_button(NSMakeRect(PAD, 26, W - 2 * PAD, 48), cta_label(), self, "continue:")
        content.addSubview_(self._done); add(self._done)

    # ---------------- page 2: how to dictate ----------------
    def _build_page2(self, content):
        add = self._page2.append

        hero = _keycap(NSMakeRect((W - 150) / 2, _y(56, 150), 150, 150), "⌘",
                       _serif(66), 28, gradient=True)
        content.addSubview_(hero); add(hero)

        title = _label(NSMakeRect(PAD, _y(232, 30), W - 2 * PAD, 30),
                       i18n.t("You're ready to dictate"), _serif(22, semibold=True), INK,
                       align=NSTextAlignmentCenter)
        content.addSubview_(title); add(title)
        sub = _label(NSMakeRect(PAD, _y(267, 20), W - 2 * PAD, 20),
                     i18n.t("Two keys are all you need."), _sf(14), INK_SOFT,
                     align=NSTextAlignmentCenter)
        content.addSubview_(sub); add(sub)

        cap = _label(NSMakeRect(PAD, _y(309, 20), W - 2 * PAD, 20),
                     i18n.t("Hold the RIGHT ⌘ key"), _sf(14.5, 0.3), INK,
                     align=NSTextAlignmentCenter)
        content.addSubview_(cap); add(cap)
        instr = _label(NSMakeRect((W - 420) / 2, _y(335, 34), 420, 34),
                       i18n.t("speak, then release — your words get typed "
                              "where the cursor is."),
                       _sf(13), INK_SOFT, align=NSTextAlignmentCenter, multiline=True)
        content.addSubview_(instr); add(instr)

        # The mode counter comes from the real registry: "8 modes" silently
        # went stale when the ninth arrived.
        from . import modes as _modes

        n_modos = len(_modes.modes_by_key())
        t = 387
        first = True
        for keys, ttl, desc in (
            ("⌘ + Shift", i18n.t("Hands-free"),
             i18n.t("Toggle dictation on/off without holding.")),
            ("⌃⇧M", i18n.t("Change mode"),
             i18n.t("Cycle {n} modes (verbatim, email, code…).").format(n=n_modos)),
            ("Esc", i18n.t("Cancel"),
             i18n.t("Throw away the dictation in progress.")),
        ):
            hair = _rule(NSMakeRect(PAD, _y(t, 1), W - 2 * PAD, 1), HAIRLINE)
            content.addSubview_(hair); add(hair)
            first = False
            card = self._shortcut_row(NSMakeRect(PAD, _y(t + 1, 52), W - 2 * PAD, 52), keys, ttl, desc)
            content.addSubview_(card); add(card)
            t += 53

        # Closes the list and warns that none of this is final. It goes here
        # and not in a tooltip because this is the only screen the user is
        # guaranteed to see: without this line, whoever can't use the right ⌘
        # (an external keyboard without it, or that hand busy) is left
        # thinking the app isn't for them, instead of opening Settings and
        # changing it in two clicks.
        hair = _rule(NSMakeRect(PAD, _y(t, 1), W - 2 * PAD, 1), HAIRLINE)
        content.addSubview_(hair); add(hair)
        nota = _label(NSMakeRect(PAD, _y(t + 16, 34), W - 2 * PAD, 34),
                      i18n.t("Prefer another key? Change it whenever you like "
                             "from the menu bar icon › Shortcuts › "
                             "Customize…"),
                      _sf(12), INK_SOFT, align=NSTextAlignmentCenter, multiline=True)
        content.addSubview_(nota); add(nota)

        self._start = _cta_button(NSMakeRect(PAD, 26, W - 2 * PAD, 48), i18n.t("Start dictating"), self, "finish:")
        content.addSubview_(self._start); add(self._start)

    def _shortcut_row(self, frame, keys, title, desc):
        row = NSView.alloc().initWithFrame_(frame)
        rw = frame.size.width
        chip = _keycap(NSMakeRect(0, 8, 72, 36), keys, _sf(13, 0.3), 8)
        row.addSubview_(chip)
        row.addSubview_(_label(NSMakeRect(88, 27, rw - 88, 17), title, _sf(13.5, 0.3), INK))
        d = _label(NSMakeRect(88, 8, rw - 88, 17), desc, _sf(12.5), INK_SOFT)
        row.addSubview_(d)
        return row

    def _build_row(self, key, name, desc, action, style, frame):
        row = NSView.alloc().initWithFrame_(frame)
        rw, rh = frame.size.width, frame.size.height
        title_x = 34

        # status dot (● done / ○ pending) aligned with the title
        status = _label(NSMakeRect(0, rh - 29, 20, 20), "○", _sf(15), PENDING_RING,
                        align=NSTextAlignmentCenter)
        row.addSubview_(status)

        row.addSubview_(_label(NSMakeRect(title_x, rh - 27, 200, 16), i18n.t(name), _sf(14, 0.3), INK))
        if key == "ai":  # gray "Optional" label next to the title
            row.addSubview_(_label(NSMakeRect(title_x + 78, rh - 26, 90, 15), i18n.t("Optional"),
                                   _sf(11.5), INK_MUTED))

        # Button on top, aligned with the title; the description goes BELOW,
        # full width (so the button doesn't clip it — the bug there was). The
        # width is computed over the English `action` (a stable table key);
        # only the painted text goes through t().
        btn_w = {"Allow": 70, "Open Settings": 116, "Download": 104, "Connect AI": 100}.get(action, 100)
        btn = _row_button(NSMakeRect(rw - btn_w, rh - 31, btn_w, 24), i18n.t(action), style, self, f"{key}:")
        row.addSubview_(btn)

        full_w = rw - title_x - 8
        if key == "model":
            desc_lbl = _label(NSMakeRect(title_x, 20, full_w, 18), i18n.t(desc), _sf(12), INK_SOFT)
        elif key == "ai":
            desc_lbl = _label(NSMakeRect(title_x, 8, full_w, rh - 40), i18n.t(desc), _sf(12),
                              INK_SOFT, multiline=True)
        else:
            desc_lbl = _label(NSMakeRect(title_x, 8, full_w, 20), i18n.t(desc), _sf(12), INK_SOFT)
        row.addSubview_(desc_lbl)

        bar = None
        if key == "model":
            track_w = rw - title_x - 48
            bar = NSView.alloc().initWithFrame_(NSMakeRect(title_x, 6, track_w, 4))
            bar.setWantsLayer_(True)
            bar.layer().setBackgroundColor_(PROGRESS_TRACK.CGColor())
            bar.layer().setCornerRadius_(2.0)
            bar.setHidden_(True)
            try:
                from Quartz import CALayer
                fill = CALayer.layer()
                fill.setBackgroundColor_(TEAL.CGColor())
                fill.setCornerRadius_(2.0)
                fill.setFrame_(NSMakeRect(0, 0, 0, 4))
                bar.layer().addSublayer_(fill)
                self._model_fill = fill
                self._model_track_w = float(track_w)
            except Exception:
                log.debug("No CALayer for the progress bar", exc_info=True)
            row.addSubview_(bar)
            self._model_pct = _label(NSMakeRect(title_x + track_w + 6, 3, 36, 12), "",
                                     _mono(10.5, 0.3), BTN_GHOST_TEXT)
            self._model_pct.setHidden_(True)
            row.addSubview_(self._model_pct)

        self._rows[key] = {"status": status, "button": btn, "bar": bar}
        return row

    # ---------- button actions (selectors mic:, accessibility:, ...) ----------
    def _hide_for_settings(self):
        """Hides the onboarding so System Settings is visible and
        usable: otherwise, the floating window stays on top and blocks it. The
        NSTimer (_refresh) shows it again when the permission is granted or
        when the user comes back to Voooxly."""
        self._win.orderOut_(None)
        self._hidden_for_settings = True
        self._hide_t = time.monotonic()

    def mic_(self, _sender):
        # requestAccess ONLY opens the system prompt when the permission is
        # "undecided". If the user already denied it once, macOS doesn't ask
        # again and the button would seem dead: they must be taken to Settings.
        status = setup_checks.microphone_status()
        log.info("Onboarding: clic en Microphone (status=%s)", status)
        if status == 0:  # notDetermined
            setup_checks.request_microphone()
        else:
            setup_checks.open_microphone_settings()
            self._hide_for_settings()

    def accessibility_(self, _sender):
        log.info("Onboarding: clic en Accessibility")
        setup_checks.open_accessibility_settings()
        self._hide_for_settings()

    def model_(self, _sender):
        if self._downloading:
            return
        self._downloading = True
        row = self._rows["model"]
        row["button"].setEnabled_(False)
        _set_button_title(row["button"], i18n.t("Downloading…"), TEAL_DARK)
        row["bar"].setHidden_(False)
        if self._model_pct is not None:
            self._model_pct.setHidden_(False)
        threading.Thread(target=self._download_model, daemon=True).start()

    def ai_(self, _sender):
        """Connect AI: delegates to the app's callback (provider + key
        selector, an already proven flow). Without a callback (test /
        standalone), it re-detects."""
        log.info("Onboarding: clic en Connect AI")
        if self._on_connect_ai is not None:
            try:
                self._on_connect_ai()
            except Exception:
                log.warning("Connect AI failed", exc_info=True)
            self._refresh()
        else:
            from . import refine
            refine.detect_backend(force=True)
            self._refresh()

    def continue_(self, _sender):
        """Page 1 → 2. Only enabled when the blocking checks pass."""
        self._show_page(2)

    def finish_(self, _sender):
        self._stop_timer()
        self._win.orderOut_(None)
        # Back to menu-bar app: no Dock icon or main menu. On a normal launch
        # on_finish relaunches a new process (which is already born
        # Accessory), but in the dev fallback we stay alive: must restore.
        try:
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory)
        except Exception:
            log.debug("Couldn't restore the Accessory policy", exc_info=True)
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                log.debug("on_finish callback failed", exc_info=True)

    def windowShouldClose_(self, _sender):
        # Closing with the red button counts as finish: relaunches the app (hotkey).
        self.finish_(None)
        return True

    # ---------- model download ----------
    def _download_model(self):
        """Runs on a secondary thread; every UI touch is forwarded to the main one."""
        try:
            stt.ensure_model(progress_cb=lambda pct:
                             self.performSelectorOnMainThread_withObject_waitUntilDone_(
                                 "updateProgress:", pct, False))
        except Exception as e:
            log.error("Model download failed: %s", e)
        finally:
            self._downloading = False
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "downloadFinished:", None, False)

    def updateProgress_(self, pct):
        try:
            p = float(pct)
            if self._model_fill is not None:
                self._model_fill.setFrame_(NSMakeRect(0, 0, self._model_track_w * p / 100.0, 4))
            if self._model_pct is not None:
                self._model_pct.setStringValue_(f"{int(p)}%")
        except Exception:
            pass

    def downloadFinished_(self, _arg):
        row = self._rows["model"]
        _set_button_title(row["button"], i18n.t("Download"), TEAL_DARK)
        if self._model_pct is not None:
            self._model_pct.setHidden_(True)
        self._refresh()

    # ---------- periodic refresh ----------
    def tick_(self, _timer):
        self._refresh()

    def _start_timer(self):
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True)

    def _stop_timer(self):
        if self._timer is not None:
            try:
                self._timer.invalidate()
            except Exception:
                pass
            self._timer = None

    def _refresh(self):
        ready = True
        for check in setup_checks.check_all():
            row = self._rows.get(check.key)
            if row is None:
                continue
            row["status"].setStringValue_("●" if check.ok else "○")
            row["status"].setTextColor_(TEAL if check.ok else PENDING_RING)
            if not (check.key == "model" and self._downloading):
                row["button"].setEnabled_(not check.ok or check.key == "ai")
            # When the requirement is met, the button is redundant (the ● dot
            # says so); the AI stays reconnectable forever.
            row["button"].setHidden_(bool(check.ok) and check.key != "ai")
            if check.key == "model" and check.ok and row["bar"] is not None:
                row["bar"].setHidden_(True)
            if check.blocking and not check.ok:
                ready = False
        _style_cta(self._done, ready, cta_label())

        # Re-show the window if we hid it to go to System Settings.
        if self._hidden_for_settings:
            granted = setup_checks.has_accessibility()
            back = NSApplication.sharedApplication().isActive()
            elapsed = time.monotonic() - self._hide_t
            # The ">1.5s" avoids re-showing in the same tick before Settings
            # steals focus. It re-shows on granting the permission or on returning.
            if granted or (back and elapsed > 1.5):
                self._hidden_for_settings = False
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                self._win.makeKeyAndOrderFront_(None)

    # ---------- pages ----------
    def _show_page(self, n):
        self._page = n
        for v in self._page1:
            v.setHidden_(n != 1)
        for v in self._page2:
            v.setHidden_(n != 2)
        if n == 1:
            self._step_label.setStringValue_(i18n.t("STEP 1 OF 2"))
            self._done.setKeyEquivalent_("\r")
            self._start.setKeyEquivalent_("")
        else:
            self._step_label.setStringValue_(i18n.t("STEP 2 OF 2"))
            self._done.setKeyEquivalent_("")
            self._start.setKeyEquivalent_("\r")

    def show(self):
        app = NSApplication.sharedApplication()
        # Promote to foreground app for the duration of the onboarding: this
        # way the window becomes truly key/active and clicks reach the buttons
        # (on macOS 26, being accessory, the window server swallowed them). It
        # also gets a Dock tile, which makes minimizing meaningful.
        try:
            app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        except Exception:
            log.debug("Couldn't promote to Regular", exc_info=True)
        app.activateIgnoringOtherApps_(True)
        self._win.center()
        self._win.makeKeyAndOrderFront_(None)
        self._start_timer()
        # show() runs BEFORE the rumps run loop starts, and activating too
        # early doesn't "stick". We re-activate once the loop is alive, and
        # ~half a second later we log the ALREADY settled state (checking it in
        # the same tick as the activate gives a false 'key=False' before it sets).
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "reactivate:", None, False)
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.7, self, "logState:", None, False)

    def reactivate_(self, _timer):
        try:
            app = NSApplication.sharedApplication()
            app.activateIgnoringOtherApps_(True)
            self._win.makeKeyAndOrderFront_(None)
        except Exception:
            log.debug("re-activation failed", exc_info=True)

    def logState_(self, _timer):
        try:
            app = NSApplication.sharedApplication()
            log.info("Onboarding activo: key=%s active=%s policy=%s",
                     self._win.isKeyWindow(), app.isActive(), app.activationPolicy())
        except Exception:
            pass


# ---------------- view helpers ----------------
def _row_button(rect, title, style, target, action):
    """Row button: 'ghost' (thin border), 'tint' (light teal fill) or
    'text' (teal text only)."""
    b = NSButton.alloc().initWithFrame_(rect)
    b.setBordered_(False)
    b.setBezelStyle_(0)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(8.0)
    b.setTarget_(target)
    b.setAction_(action)
    if style == "tint":
        b.layer().setBackgroundColor_(MODEL_BTN_BG.CGColor())
        b.layer().setBorderWidth_(1.0)
        b.layer().setBorderColor_(MODEL_BTN_BORDER.CGColor())
        fg = TEAL_DARK
    elif style == "text":
        fg = TEAL_DARK
    else:  # ghost
        b.layer().setBorderWidth_(1.0)
        b.layer().setBorderColor_(BTN_BORDER.CGColor())
        fg = BTN_GHOST_TEXT
    b.setTitle_(title)
    _set_button_title(b, title, fg)
    return b


def _set_button_title(b, title, fg):
    """Row-button title with brand color (attributedTitle wins over
    setTitle_, so the model's text changes go through here)."""
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
        title, {NSFontAttributeName: _sf(12.5, 0.3), NSForegroundColorAttributeName: fg}))


def _cta_button(rect, title, target, action):
    """Main CTA, teal fill, white text."""
    b = NSButton.alloc().initWithFrame_(rect)
    b.setBordered_(False)
    b.setBezelStyle_(0)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(10.0)
    b.setTarget_(target)
    b.setAction_(action)
    _style_cta(b, True, title)
    return b


def _style_cta(b, enabled, title):
    b.layer().setBackgroundColor_((TEAL if enabled else CTA_DISABLED_BG).CGColor())
    fg = NSColor.whiteColor() if enabled else CTA_DISABLED_TEXT
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
        title, {NSFontAttributeName: _sf(14, 0.3), NSForegroundColorAttributeName: fg}))
    b.setEnabled_(enabled)


# Global reference: without it the collector takes the window and it vanishes on its own.
_controller = None


def show_onboarding(on_finish=None, on_connect_ai=None) -> None:
    """Shows the assistant. MUST be called from the main thread."""
    global _controller
    try:
        _controller = OnboardingController.alloc().initWithFinish_connectAI_(
            on_finish, on_connect_ai)
        _controller.show()
    except Exception as e:
        log.error("Couldn't show onboarding: %s", e)
