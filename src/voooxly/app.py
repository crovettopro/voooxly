"""Menu-bar app (rumps) that orchestrates the whole dictation system.

Simple state machine:
  IDLE -> (toggle) -> RECORDING -> (toggle | silence) -> PROCESSING -> IDLE

During RECORDING the overlay shows the partial transcription.
On finish: final STT -> per-mode refine -> deliver (clipboard + paste).
"""
from __future__ import annotations

import collections
import json
import logging
import os
import plistlib
import subprocess
import threading
import time

import rumps

from . import audio, axfield, dictionary, history, i18n, keys, langlock, learn, media, modes, output, providers, recgate, refine, richtext, setup_checks, shortcuts, stats, stt, updates
from .config import get_config, resolve_language
from .hotkey import HotkeyManager
from .overlay import Overlay

log = logging.getLogger("voooxly")

# Preferences touched from the menu (config.yaml lives INSIDE the .app and
# is read-only in practice): a small json in ~/.voooxly.
PREFS_PATH = os.path.expanduser("~/.voooxly/prefs.json")
# "Start at login": a classic LaunchAgent — no ServiceManagement APIs,
# works the same launched from the repo or from /Applications.
LAUNCH_AGENT = os.path.expanduser(
    "~/Library/LaunchAgents/com.eduardocrovetto.voooxly.plist"
)
HISTORY_SIZE = 10


def _load_prefs() -> dict:
    try:
        with open(PREFS_PATH) as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_prefs(prefs: dict) -> None:
    try:
        os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
        with open(PREFS_PATH, "w") as f:
            json.dump(prefs, f, indent=2)
    except Exception:
        log.warning("Couldn't save prefs in %s", PREFS_PATH)


def ai_menu_labels(selection) -> list[tuple[str, bool]]:
    """Rows for the AI engine submenu: (label, is it the active one?).

    At module level and not as a method so it can be tested: instantiating
    VoooxlyApp builds AppKit menus and that doesn't run in a test.
    """
    filas = []
    for prov in providers.PROVIDERS.values():
        # Clean label, no "…": the short list is already clear and the "…" on
        # every row looked noisy. Clicking asks for the key (or the Ollama
        # model), but that doesn't justify cluttering the five rows.
        etiqueta = prov.label
        activo = selection is not None and selection.provider.key == prov.key
        filas.append((etiqueta, activo))
    return filas


# Short names for the backends refine.detect_backend() returns: the rows of
# the "AI engine" submenu can no longer show them (they only carry a check),
# so this title compensates via the submenu's parent, which does accept text.
_BACKEND_LABELS = {"ollama": "Ollama", "claude": "Claude", "openai": "OpenAI"}


def ai_engine_title(selection, detected: str) -> str:
    """Title of the AI engine submenu's parent item: the only visible hint of
    which engine is active (the child rows only carry a check).

    At module level and not as a method, for the same reason as
    ai_menu_labels: instantiating VoooxlyApp builds AppKit menus.
    """
    if selection is not None:
        # .name, not .label: label carries the note ("Groq — free") and it
        # would read "AI engine — Groq — free", with two em dashes in a row.
        return f"AI engine — {selection.provider.name}"
    if detected == "none":
        return "AI engine — none (raw text)"
    label = _BACKEND_LABELS.get(detected, detected)
    return f"AI engine — {label} (auto)"


def _migrate_shortcuts_prefs(prefs: dict) -> bool:
    """Migrates `prefs` (in memory) to the `shortcuts` block and persists the
    result to disk — but ONLY if `shortcuts.migrate()` actually changed
    something. Returns whether it wrote.

    At module level and not inline in __init__, for the same reason as
    apply_shortcut: instantiating VoooxlyApp builds AppKit menus and that
    doesn't run in a test.

    Without this save, a user upgrading from v1.3.0 who never opens the
    Shortcuts window never ends up with the "shortcuts" key in their
    prefs.json: today that's harmless because resolve() recomputes the same
    thing by reading the old keys on every launch, but the day a future
    version stops reading them, that user loses their configuration without
    having done anything wrong. And writing ALWAYS (whether anything was
    migrated or not) would rewrite prefs.json on every launch for no reason.
    """
    if not shortcuts.migrate(prefs):
        return False
    _save_prefs(prefs)
    return True


def apply_shortcut(hk, sid: str, fila: dict) -> tuple[bool, str]:
    """Applies a shortcut to the HotkeyManager. Returns (ok, message in English).

    At module level and not as a method so it can be tested: instantiating
    VoooxlyApp builds AppKit menus and that doesn't run in a test.

    Never raises: it's called by the Shortcuts window, which is AppKit code,
    and an uncaught exception there takes the whole app down with it.
    """
    try:
        if sid == "dictation":
            tecla = (fila.get("keys") or [""])[0]
            delay_ms = int(fila.get("delay_ms") or 0)
            # The guard is the "hold the key for N ms before dictation
            # starts" window (keeps a ⌘C from triggering a recording). It
            # used to activate ONLY if the key needed it by design
            # (keys.needs_guard: left keys yes, right keys no), so the
            # slider was ignored entirely on the right ⌘ even if the
            # user set a delay on it (feedback point 2). Now the
            # delay is the user's choice on any key: needs_guard
            # still decides the DEFAULT (left keys → 400), but a delay>0
            # always enables it. needs_guard is kept separate so that
            # a left key with delay 0 doesn't lose its guard.
            ok = hk.reconfigure(
                toggle_key=tecla,
                toggle_mode=fila.get("style", "hold"),
                guard=keys.needs_guard(tecla) or delay_ms > 0,
                # The hotkey works in SECONDS; the window and prefs.json in ms.
                guard_delay=float(delay_ms) / 1000.0,
            )
        else:
            ok = hk.rebind(sid, list(fila.get("keys") or []))
    except Exception:
        log.exception("Couldn't apply shortcut %s", sid)
        return False, "Something went wrong applying that shortcut."
    if not ok:
        return False, "That key collides with another shortcut, so the previous one is still active."
    return True, ""


def check_now_message(status: str, info: dict | None, local: str) -> tuple[str, str]:
    """(title, message) for the result of a manual 'Check for updates…'.

    Pure: the UI wiring calls it from _check_now and hands it whatever
    updates.check_status() returned. No info -> error or up to date per status.
    """
    if status == updates.UPDATE_AVAILABLE and info:
        ver = info["version"]
        notes = (info.get("notes") or "").strip()
        body = i18n.t("Voooxly {ver} is available.").format(ver=ver) + (
            f"\n\n{notes}" if notes else ""
        )
        return i18n.t("Update available"), body
    if status == updates.UP_TO_DATE:
        return i18n.t("Up to date"), i18n.t(
            "You're running the latest version (Voooxly {local})."
        ).format(local=local)
    return i18n.t("Couldn't check"), i18n.t(
        "Couldn't reach the update server. Try again later."
    )


def apply_ai_selection(cfg, sel) -> None:
    """Applies the choice to the LIVE config (here it's right to: this is configuring the app).

    At module level and not as a method so it can be tested without
    instantiating VoooxlyApp (same reason as ai_menu_labels/ai_engine_title:
    AppKit doesn't run in pytest).

    Unlike _probe(), which must not touch the singleton, this IS the
    moment to write it: the user just made a choice. The path depends on the
    kind — same branching as _probe and for the same reason (the
    OpenAI-compatible presets share llm.openai.*).
    """
    if sel is None:
        return
    cfg._set_path("llm.backend", sel.provider.kind)
    cfg._set_path(f"llm.{sel.provider.kind}.model", sel.model)
    if sel.provider.kind == "ollama":
        cfg._set_path("llm.ollama.host", sel.base_url)
    elif sel.base_url:
        # Claude has no base_url of its own (the anthropic SDK manages its
        # endpoint by itself, base_url == "" by design in providers.py):
        # writing here unconditionally left llm.openai.base_url = "" live
        # every time Claude was connected or restored, breaking the
        # OpenAI-compatible path until the next openai-kind provider connected.
        cfg._set_path("llm.openai.base_url", sel.base_url)


def _record_token_usage(refiner, prefs) -> None:
    """Counts the tokens of the last remote refine, if there was one.

    At module level (same reason as apply_ai_selection: to be testable
    without instantiating VoooxlyApp) and because _process calls it AFTER
    output.deliver() on purpose: counting tokens is pure best-effort so
    whoever uses a free tier can see how much they've spent, and it can NEVER
    prevent or precede the paste. Before, ai_settings.load(self._prefs) ran
    inside _process's try/except and BEFORE deliver(); if it raised (a
    corrupt prefs.json, for example), _process aborted to the catch-all and
    the already-refined text never got pasted — losing the user's dictation
    over a token-counting failure is the worst possible outcome here.
    """
    try:
        usados = getattr(refiner, "last_usage", None)
        if not usados:
            return
        from . import ai_settings

        sel = ai_settings.load(prefs)
        stats.bump_tokens(usados, sel.provider.name if sel else "")
    except Exception:
        log.debug("Couldn't count tokens after pasting", exc_info=True)


# --- Auto-learn glue -------------------------------------------------------
# At module level for the same reason as _record_token_usage: these are the
# only two decisions of the feature that can corrupt state, and they have to
# be testable without building the AppKit menus.


class LearnState:
    """Shared state of auto-learn, behind its own lock.

    Several daemon threads can touch it at once: the post-paste window of the
    dictation just delivered, the window of the previous one (they overlap —
    with a 1.2s silence cutoff the pastes are ~5s apart and the window lasts
    15s), and the next-dictation fallback. Generations are what tell them
    apart: a window may only disarm the fallback of ITS OWN paste, never that
    of a newer one.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gen = 0
        self._stop: threading.Event | None = None
        self._pending: str | None = None
        self._note: str | None = None

    def start(self, pasted: str) -> tuple[int, threading.Event]:
        """A new paste: supersedes the running window and arms the fallback."""
        with self._lock:
            if self._stop is not None:
                self._stop.set()
            self._stop = threading.Event()
            self._gen += 1
            self._pending = pasted
            return self._gen, self._stop

    def take_pending(self) -> str | None:
        """What the next dictation should compare against, once."""
        with self._lock:
            pending, self._pending = self._pending, None
            return pending

    def done(self, gen: int, note: str | None) -> None:
        """A window finished. Only the current generation disarms the fallback."""
        with self._lock:
            if not note:
                return  # nothing learned: the next dictation still has a go
            self._note = "\n".join(x for x in (self._note, note) if x)
            if gen == self._gen:
                self._pending = None

    def park_note(self, note: str) -> None:
        with self._lock:
            self._note = "\n".join(x for x in (note, self._note) if x)

    def take_note(self) -> str | None:
        with self._lock:
            note, self._note = self._note, None
            return note


def _drain_learned_note(state: LearnState, idle: bool, prefs: dict, show) -> bool:
    """Paints the "✨ Learned" notice if the HUD is free; keeps it if not.

    The first-run "you can turn this off" line — and the pref that spends it —
    are decided HERE, when the notice is actually painted, not where the pairs
    are learned. The window learns while the gate is IDLE, seconds after
    _process already drained its own note: deciding it there would burn the
    one-time disclosure on a notice nobody ever saw.
    """
    note = state.take_note()
    if not note:
        return False
    if not idle:
        state.park_note(note)  # a dictation owns the HUD: wait for its turn
        return False
    if not prefs.get("auto_learn_seen"):
        prefs["auto_learn_seen"] = True
        _save_prefs(prefs)
        note += "\n" + i18n.t("Turn off in Settings if you prefer.")
    try:
        show(note)
    except Exception:
        # The pairs are already in the dictionary; a notice that cannot be
        # painted is a debug line, never a traceback out of a daemon thread.
        log.debug("auto-learn: couldn't paint the notice", exc_info=True)
        return False
    return True


def _watch_and_learn(cfg, state: LearnState, pasted: str, gen: int, stop, read=None, **kw) -> list[str]:
    """Body of the post-paste window thread. Best-effort: it never raises.

    `read` and the clock/sleep in **kw are injected so the whole thing can be
    driven by a script in the tests. The defaults live here and not only in
    config.yaml because a user's ~/.voooxly/config.yaml shadows the bundled
    file wholesale (no merge): without them, an existing install gets None.
    """
    learned: list[str] = []
    traza: list[tuple[int, bool]] = []
    window_s = cfg.get("learn.window_seconds", 15.0)
    # Counts only, never the field: what the user has written around our paste
    # is theirs. But SOMETHING has to be said — most of the manual gate is
    # cases where nothing may happen, and without a trace a window that never
    # ran looks exactly like one that ran and correctly stayed quiet.
    log.info("Auto-learn: watching the pasted field for up to %ss.", window_s)
    try:
        field = learn.watch_field(
            pasted,
            read or axfield.app_locked_reader(),
            window_s=window_s,
            poll_s=cfg.get("learn.poll_interval", 2.0),
            stable_s=cfg.get("learn.stable_seconds", 3.0),
            acquire_s=cfg.get("learn.acquire_seconds", 4.0),
            stop=stop,
            trace=traza,
            **kw,
        )
        learned = learn.auto_learn_from(pasted, field or "")
    except Exception:
        log.debug("auto-learn (window) silent", exc_info=True)
    if learned:
        log.info("Auto-learn: learned %d correction(s).", len(learned))
    else:
        # Counts, never the text. Which of the three numbers is zero says
        # which boundary failed: 0 readable = the app exposes nothing;
        # readable but 0 located = it does and we failed to find our paste.
        log.info(
            "Auto-learn: nothing learned (%d polls, %d readable, %d located; %s).",
            len(traza),
            sum(1 for chars, _ in traza if chars),
            sum(1 for _, ok in traza if ok),
            axfield.describe_focused(),
        )
    state.done(gen, "\n".join(learned) if learned else None)
    return learned


class VoooxlyApp(rumps.App):
    def __init__(self):
        cfg = get_config()
        self.cfg = cfg
        self.mode = cfg.get("app.default_mode", "ordenar")
        # "auto" -> the system language of whoever uses the app, not the author's.
        self.language = resolve_language(cfg.get("app.language", None))
        self.stt_model = cfg.get("stt.model")
        self.stt_lang = resolve_language(cfg.get("stt.language", None))
        # Every recording transition goes through the gate (see recgate.py):
        # start/stop/cancel arrive from hotkey threads with no guaranteed order
        # and a stop that outruns the start-up cannot be lost.
        self._gate = recgate.RecordingGate()
        # Esc while recording/processing: discard the dictation, paste nothing.
        self._cancel = threading.Event()
        self._recorder: audio.Recorder | None = None
        self._overlay = Overlay(cfg.get("app.overlay_position", "bottom-right"))
        self._last_result = ""
        self._show_overlay = bool(cfg.get("app.show_overlay", True))
        self._partial_thread: threading.Thread | None = None
        self._partial_running = threading.Event()
        self._prefs = _load_prefs()
        self._sounds = bool(self._prefs.get("sounds", cfg.get("app.sounds", True)))
        self._snd_cache: dict = {}   # NSSounds kept alive while playing (else, dealloc mid-sound)
        self._history: collections.deque[str] = collections.deque(maxlen=HISTORY_SIZE)
        # Kept separate from _history because _search_history replaces the
        # deque's content with search hits (self._history[0] stops being "the
        # last dictation"). _correct_last needs the real dictation, not the
        # most relevant hit of a search.
        self._last_dictation: str | None = None
        # Auto-learn: the last text pasted (watched right after the paste, and
        # compared again on the next dictation as a fallback) plus the
        # "✨ Learned" note waiting for the HUD to be free.
        self._learn = LearnState()
        # Dictionary (config + personal) → Whisper initial prompt (biases it
        # toward those spellings). Whisper only uses ~224 tokens: it gets trimmed.
        self.stt_prompt = self._build_stt_prompt()

        icon_path = self._asset("menubar.png")
        self._has_icon = icon_path is not None
        self._idle_icon = icon_path
        self._rec_icon = self._asset("menubar-rec.png")
        self._rec_shown = False
        self._timer_seq = 0
        super().__init__(
            name="Voooxly",
            icon=icon_path,          # template glyph (adapts to light/dark)
            title=None if self._has_icon else "🎙",
            template=True,
            quit_button=None,        # rumps adds its own "Quit" unless overridden
        )                            # (we use ours, which shuts down server/hotkey)
        # Resolved BEFORE _build_menu(): the Shortcuts item sets its
        # initial state by reading self._dictation_key/self._toggle_mode, so
        # they have to exist before those NSMenuItems are built.
        _migrate_shortcuts_prefs(self._prefs)
        self._shortcuts = shortcuts.resolve(self._prefs, cfg)
        dic = self._shortcuts["dictation"]
        tecla, modo = dic["keys"][0], dic["style"]
        self._toggle_mode = modo
        self._dictation_key = tecla
        # UI language (menu and dialogs): manual override in config.yaml or,
        # by default, the system's first preferred language. i18n.py doesn't
        # touch AppKit at module level, so we resolve NSLocale here and hand
        # it the already-resolved string.
        ui_lang = cfg.get("app.ui_language", None)
        if not ui_lang:
            try:
                from Foundation import NSLocale

                ui_lang = i18n.resolve_lang(list(NSLocale.preferredLanguages()))
            except Exception:
                ui_lang = "en"
        i18n.set_lang(ui_lang)
        self._build_menu()
        self._apply_login_default()
        self._hotkey = HotkeyManager(
            toggle_mode=modo,
            toggle_keys=[tecla],
            cycle_keys=self._shortcuts["cycle_mode"]["keys"],
            on_toggle=self.toggle_record,
            on_start=self.start_record,
            on_stop=self.stop_record,
            on_cycle=self.cycle_mode,
            cancel_keys=self._shortcuts["cancel"]["keys"],
            on_cancel=self.cancel_record,
            latch_keys=self._shortcuts["latch"]["keys"],
            on_latch=self._on_latch,
            # See apply_shortcut: the delay is the user's choice on any
            # key, not only the ones needs_guard says need it.
            toggle_guard=keys.needs_guard(tecla) or int(dic.get("delay_ms") or 0) > 0,
            guard_delay=float(dic.get("delay_ms") or 0) / 1000.0,
        )

    def _on_latch(self):
        log.info("Latch: recording pinned, tap the dictation key to finish.")
        try:
            self._overlay.update("🔒 Hands-free — tap the dictation key to finish")
        except Exception:
            pass

    @staticmethod
    def _asset(name: str) -> str | None:
        import os
        import sys

        cands = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cands.append(os.path.join(meipass, "assets", name))
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cands.append(os.path.join(repo, "assets", name))
        for c in cands:
            if os.path.exists(c):
                return c
        return None

    # ---------- menu ----------
    def _build_menu(self):
        items = []
        for key, info in modes.modes_by_key().items():
            mi = rumps.MenuItem(info["label"], callback=self._make_mode_cb(key))
            mi.state = 1 if key == self.mode else 0
            items.append(mi)
        self.mode_items = {key: mi for (key, _), mi in zip(modes.modes_by_key().items(), items)}

        self.status = rumps.MenuItem(i18n.t("Ready"), callback=None)
        self.ai = rumps.MenuItem(i18n.t("AI engine"))
        self._ai_items = {}
        for prov_key, (etiqueta, _) in zip(providers.PROVIDERS, ai_menu_labels(None)):
            mi = rumps.MenuItem(etiqueta, callback=self._make_provider_cb(prov_key))
            self.ai.add(mi)
            self._ai_items[prov_key] = mi
        self.ai.add(rumps.separator)
        self.ai_auto_item = rumps.MenuItem(i18n.t("Detect automatically"), callback=self._reset_to_auto)
        self.ai.add(self.ai_auto_item)
        self.ai_test_item = rumps.MenuItem(i18n.t("Test connection"), callback=self._test_ai)
        self.ai.add(self.ai_test_item)
        self.stats_item = rumps.MenuItem(i18n.t("Usage stats…"), callback=self._show_stats)
        self.quit = rumps.MenuItem(i18n.t("Quit Voooxly"), callback=self._quit)
        # Hidden until the checker finds a new version (see _warmup).
        self.update_item = rumps.MenuItem(i18n.t("Update available"), callback=self._open_update)
        self.about_item = rumps.MenuItem(i18n.t("About Voooxly"), callback=self._show_about)
        self._update_url = ""
        self._update_version = ""
        self._update_downloading = False
        # Periodic re-check every updates.CHECK_INTERVAL; HUD once per version.
        self._update_timer: threading.Timer | None = None
        self._notified_update_version: str | None = None
        self._paused_players: list[str] = []
        self._mode_flash_seq = 0
        self._mic_warned = False

        # Recent: the latest dictations, click = copy them to the clipboard again.
        # Items are PRE-created hidden: adding/removing items of an NSMenu from the
        # processing thread would be unsafe; changing title/hidden works fine.
        self.recent_parent = rumps.MenuItem(i18n.t("Recent"))
        # "Correct and learn" (v1 of the auto-learned dictionary, pre-launch
        # plan): the user corrects the last dictation in a
        # dialog and the changed spellings go into the dictionary. The 100%
        # automatic detection (reading another app's field) is left for H2.
        self.correct_item = rumps.MenuItem(
            i18n.t("Correct last dictation…"), callback=self._correct_last
        )
        self.recent_parent.add(self.correct_item)
        self._recent_empty = rumps.MenuItem(i18n.t("(empty)"))
        self.recent_parent.add(self._recent_empty)
        self._recent_items: list[rumps.MenuItem] = []
        for i in range(HISTORY_SIZE):
            mi = rumps.MenuItem(f"recent-{i}", callback=self._make_recent_cb(i))
            self.recent_parent.add(mi)
            mi._menuitem.setHidden_(True)
            self._recent_items.append(mi)

        settings = rumps.MenuItem(i18n.t("Settings"))
        self.login_item = rumps.MenuItem(i18n.t("Start at login"), callback=self._toggle_login)
        self.login_item.state = 1 if os.path.exists(LAUNCH_AGENT) else 0
        self.sounds_item = rumps.MenuItem(i18n.t("Sounds"), callback=self._toggle_sounds)
        self.sounds_item.state = 1 if self._sounds else 0
        self.dict_item = rumps.MenuItem(i18n.t("Add to dictionary…"), callback=self._add_to_dictionary)
        # Auto-learn: learn from the corrections made to the pasted text.
        self.auto_learn_item = rumps.MenuItem(
            i18n.t("Learn from my corrections"), callback=self._toggle_auto_learn
        )
        self.auto_learn_item.state = 1 if self._prefs.get("auto_learn", True) else 0
        settings.add(self.login_item)
        settings.add(self.sounds_item)
        settings.add(self.dict_item)
        settings.add(self.auto_learn_item)

        # "Shortcuts" submenu at the TOP level (Jeff's v1.6 feedback: the
        # shortcuts are the most important part of the app and were buried in
        # Settings): one row per shortcut with its real binding — clicking
        # any of them opens the window — and "Customize…" at the end. The titles
        # are decided by shortcuts.menu_summary (pure, tested) and refresh when
        # a change is applied from the window (_apply_shortcut).
        self.shortcuts_menu = rumps.MenuItem(i18n.t("Shortcuts"))
        self._shortcut_rows: dict[str, rumps.MenuItem] = {}
        for sid, texto in shortcuts.menu_summary(self._shortcuts):
            mi = rumps.MenuItem(texto, callback=self._open_shortcuts)
            self.shortcuts_menu.add(mi)
            self._shortcut_rows[sid] = mi
        self.shortcuts_menu.add(rumps.separator)
        self.shortcuts_item = rumps.MenuItem(i18n.t("Customize…"), callback=self._open_shortcuts)
        self.shortcuts_menu.add(self.shortcuts_item)

        # Dictation language: Auto (with the learned lock visible), Español, English.
        # Language names are endonyms: they don't get translated.
        self.lang_menu = rumps.MenuItem(i18n.t("Dictation language"))
        self._lang_items = {}
        for code, label in (("auto", i18n.t("Auto")), ("es", "Español"), ("en", "English")):
            mi = rumps.MenuItem(label, callback=self._make_lang_cb(code))
            self._lang_items[code] = mi
            self.lang_menu.add(mi)
        self._refresh_lang_menu()

        self.search_item = rumps.MenuItem(i18n.t("Search history…"), callback=self._search_history)
        # The usage guide (v1.6 feedback: lots of features, no guide).
        self.guide_item = rumps.MenuItem(i18n.t("How to use Voooxly…"), callback=self._show_guide)

        self.menu = [
            *items,
            rumps.separator,
            self.recent_parent,
            self.search_item,
            rumps.separator,
            self.status,
            self.ai,
            self.shortcuts_menu,
            self.lang_menu,
            self.stats_item,
            settings,
            rumps.separator,
            self.guide_item,
            self.about_item,
            self.update_item,
            self.quit,
        ]
        # setHidden_ must come AFTER assigning self.menu: until then rumps hasn't
        # created the real NSMenuItem and the hiding is lost.
        self.update_item._menuitem.setHidden_(True)
        self._refresh_title()

    def _make_mode_cb(self, key):
        def cb(_sender):
            self.set_mode(key)
        return cb

    def _toggle_auto_learn(self, sender):
        on = not self._prefs.get("auto_learn", True)
        self._prefs["auto_learn"] = on
        _save_prefs(self._prefs)
        sender.state = 1 if on else 0

    def _make_lang_cb(self, code: str):
        def cb(_sender):
            self._prefs["stt_language"] = code
            if code == "auto":
                # Going back to Auto resets the learning: streak and lock go.
                self._prefs["lang_streak"] = []
                self._prefs["stt_lang_lock"] = None
            _save_prefs(self._prefs)
            self._refresh_lang_menu()
        return cb

    def _refresh_lang_menu(self):
        """Check on the active language; the Auto item shows the learned lock."""
        try:
            sel = self._prefs.get("stt_language", "auto")
            lock = self._prefs.get("stt_lang_lock")
            title = i18n.t("Auto")
            if lock:
                title += " (Español)" if lock == "es" else " (English)"
            self._lang_items["auto"].title = title
            for code, mi in self._lang_items.items():
                mi.state = 1 if code == sel else 0
        except Exception:
            pass

    def set_mode(self, key: str):
        if key not in modes.MODES:
            return
        self.mode = key
        # mi.state is AppKit on NSMenuItem; set_mode is also called from the
        # Ctrl+Shift+M hotkey (background thread), not only from the menu → goes
        # through main or it crashes with the menu open (same SIGTRAP as _refresh_title).
        def apply():
            for k, mi in self.mode_items.items():
                mi.state = 1 if k == key else 0
        self._on_main(apply)
        self._refresh_title()
        log.info("Modo: %s", modes.MODES[key]["label"])
        self._flash_mode()

    def _flash_mode(self):
        """HUD flash with the just-activated mode (name + position + hint).

        Without this, cycling with Ctrl+Shift+M is blind: 9 modes and no clue
        which one you landed on. It auto-hides after ~1.4s; cycling fast only
        renews the timer (the newest seq wins) and a dictation in progress
        takes priority over the flash.
        """
        if not self._show_overlay or not getattr(self._overlay, "_built", False):
            log.debug(
                "flash: discarded (show_overlay=%s, built=%s)",
                self._show_overlay, getattr(self._overlay, "_built", None),
            )
            return
        if self._gate.state != "IDLE":
            return  # the HUD is busy with a dictation
        self._mode_flash_seq += 1
        seq = self._mode_flash_seq

        def _do():
            try:
                title, body = modes.flash_parts(self.mode)
                self._overlay.show(body, title=title)
                time.sleep(1.4)
                if self._mode_flash_seq != seq:
                    return  # another mode change happened: its flash wins
                if self._gate.state != "IDLE":
                    return  # a dictation started: its flow manages the HUD
                self._overlay.hide()
            except Exception:
                log.warning("Mode flash failed", exc_info=True)

        threading.Thread(target=_do, daemon=True).start()

    def cycle_mode(self):
        keys = list(modes.MODES.keys())
        try:
            i = keys.index(self.mode)
        except ValueError:
            i = -1
        self.set_mode(keys[(i + 1) % len(keys)])

    def _on_main(self, fn):
        """Runs fn on the main thread. AppKit is NOT thread-safe: writing the
        title of the bar or of an NSMenuItem from a recording/processing
        thread while a menu is OPEN reflows the popup window from the wrong
        thread and aborts with SIGTRAP (EXC_BREAKPOINT). Every write of
        .title goes through here. If a menu is open the runloop is in
        tracking and the update applies when it closes: it shows up an
        instant late, but it never crashes."""
        if threading.current_thread() is threading.main_thread():
            try:
                fn()
            except Exception:
                log.debug("title update failed", exc_info=True)
            return
        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(fn)
        except Exception:
            log.debug("couldn't enqueue title update on the main thread", exc_info=True)

    def _refresh_title(self):
        label = modes.MODES.get(self.mode, {}).get("label", "Voooxly")
        state = self._gate.state
        # Menu bar: template glyph while idle; recording = red dot +
        # stopwatch (handled by _rec_timer); processing = glyph + "…".
        if state == "RECORDING" and self._rec_icon:
            self._swap_icon(rec=True)
            set_bar = False   # the stopwatch (_start_rec_timer) owns the title
        else:
            self._swap_icon(rec=False)
            set_bar = True
        bar = {"RECORDING": "🔴", "PROCESSING": "…"}.get(
            state, None if self._has_icon else "🎙"
        )
        state_en = {"IDLE": "ready", "RECORDING": "recording", "PROCESSING": "processing"}
        status = f"{i18n.t('Mode')}: {label} · {i18n.t(state_en.get(state, state))}"

        # AppKit from the recording thread kills the app with the menu open: it
        # gets marshaled. The icon already was (_swap_icon); the titles were NOT
        # — that was the SIGTRAP-at-60s bug with the menu unfolded.
        def apply():
            if set_bar:
                self.title = bar
            self.status.title = status

        self._on_main(apply)

    def _swap_icon(self, rec: bool):
        """Swaps the bar icon on the main thread (AppKit is not
        thread-safe and _refresh_title arrives from recording threads)."""
        if not self._has_icon or rec == self._rec_shown or (rec and not self._rec_icon):
            return
        self._rec_shown = rec

        def apply():
            try:
                self.template = not rec
                self.icon = self._rec_icon if rec else self._idle_icon
            except Exception:
                log.debug("Couldn't change the bar icon", exc_info=True)

        try:
            from PyObjCTools import AppHelper

            AppHelper.callAfter(apply)
        except Exception:
            apply()

    def _start_rec_timer(self):
        """A 0:07 stopwatch next to the red dot while recording."""
        self._timer_seq += 1
        seq = self._timer_seq
        t0 = time.monotonic()

        def run():
            while self._timer_seq == seq:
                if self._gate.state != "RECORDING":
                    break
                s = int(time.monotonic() - t0)
                txt = f" {s // 60}:{s % 60:02d}"
                # This thread used to write self.title directly: AppKit from a
                # background thread. Marshaled to main like the rest (see _on_main).
                self._on_main(lambda txt=txt: setattr(self, "title", txt))
                time.sleep(1.0)

        threading.Thread(target=run, daemon=True).start()

    # ---------- recording ----------
    def toggle_record(self):
        state = self._gate.state
        if state == "IDLE":
            self._begin_record(auto_stop=True)
        elif state == "RECORDING":
            self._stop_record(force=True)
        elif state == "STARTING":
            # Second tap while the start-up is still on its thread: it gets noted
            # and _start_record applies it as soon as the recorder is open.
            self._gate.request_stop()

    def start_record(self):
        """Push-to-talk: key pressed -> start recording (if IDLE)."""
        self._begin_record(auto_stop=False)

    def _begin_record(self, auto_stop: bool):
        # try_begin reserves IDLE→STARTING atomically: two presses in a row
        # can no longer open two recorders (the first was left orphaned with
        # the mic open — half of Jeff's bug).
        if not self._gate.try_begin():
            return
        try:
            self._start_record(auto_stop=auto_stop)
        except Exception:
            log.exception("Error starting recording (reset to IDLE)")
            # If the recorder got as far as opening the stream before blowing
            # up, it must be closed: going back to IDLE with the mic open would
            # be the same mic-on-forever that this gate exists to prevent.
            try:
                if self._recorder:
                    self._recorder.stop()
            except Exception:
                pass
            self._gate.begin_failed()
            self._refresh_title()

    def stop_record(self):
        """Push-to-talk: key released -> finish the recording.

        If the release outruns the start-up (quick tap), the gate notes it and
        _start_record applies it when done: before, that stop was a no-op and
        the recording was left orphaned until audio.max_duration — the mic
        "constantly on" (the other half of Jeff's bug).
        """
        if self._gate.request_stop() != "stop":
            return
        try:
            self._stop_record(force=True)
        except Exception:
            log.exception("Error en stop_record")

    def cancel_record(self):
        """Esc: discards the dictation in progress (recording or processing). Pastes nothing.

        It fires on EVERY system Esc, so the no-op while IDLE
        has to be immediate and side-effect free.
        """
        state = self._gate.state
        if state == "IDLE":
            return
        self._cancel.set()
        log.info("Dictation cancelled by user (state %s).", state)
        if self._gate.request_stop() == "stop":
            try:
                self._stop_record(force=True)  # triggers _on_stop, which will see _cancel
            except Exception:
                log.exception("Error cancelling recording")
        # "deferred": _start_record will close once the start-up finishes and
        # _on_stop will see _cancel. "no": it's PROCESSING and _process already checks _cancel.

    def _start_record(self, auto_stop: bool = True):
        """Starts the recorder. Only called by _begin_record, with the gate in STARTING."""
        self._cancel.clear()
        # Auto-learn, FALLBACK path: the post-paste window (see
        # _auto_learn_watch) already had its go and disarmed this if it
        # learned. What is left here are the corrections made after the window
        # closed but before this dictation — one read, on a separate thread
        # that never delays the recording.
        pending = self._learn.take_pending()
        if pending and self._prefs.get("auto_learn", True):
            try:
                threading.Thread(target=self._auto_learn_check, args=(pending,), daemon=True).start()
            except Exception:
                # Not even the impossible case (failing to spawn the thread) may touch the recording.
                log.debug("auto-learn: couldn't spawn the thread", exc_info=True)
        # Push-to-talk (auto_stop=False): the user controls the end with the key,
        # we disable the silence auto-stop so it doesn't close when they pause to think.
        # Menu/toggle (auto_stop=True): the recording closes by itself after silence.
        silence = self.cfg.get("audio.silence_to_stop", 1.2)
        if not auto_stop:
            silence = 9999.0
        acfg = audio.AudioConfig(
            device=self.cfg.get("audio.device"),
            vad_aggressiveness=self.cfg.get("audio.vad_aggressiveness", 2),
            silence_to_stop=silence,
            max_duration=self.cfg.get("audio.max_duration", 300.0),
            min_duration=self.cfg.get("audio.min_duration", 0.4),
        )
        self._recorder = audio.Recorder(acfg)
        if self._show_overlay:
            self._overlay.show("Speak now.", title="● Listening")
        # partials thread: re-transcribes the recent window
        self._partial_running.set()
        self._partial_thread = threading.Thread(target=self._partial_loop, daemon=True)
        self._partial_thread.start()
        self._recorder.start(on_stop=self._on_stop)
        # With the stream open we're truly RECORDING. If a stop or an Esc
        # arrived during the start-up (quick tap), it's applied RIGHT HERE:
        # before, that event fell into a no-op and the recording was left orphaned.
        if self._gate.begin_done():
            log.info("Stop overtook the start (quick tap): closing now.")
            self._stop_record(force=True)
            return
        self._refresh_title()
        self._start_rec_timer()
        self._play_sound("Pop")     # "I'm listening"
        # Pause the music (Spotify/Music) while you dictate. On a separate thread:
        # osascript takes 100-300ms and must not delay the mic capture.
        if self.cfg.get("audio.pause_media", True):
            threading.Thread(target=self._pause_media, daemon=True).start()
        log.info("Grabando…")

    def _pause_media(self):
        try:
            self._paused_players = media.pause_playing()
        except Exception:
            self._paused_players = []
        # Ultra-short press: if the dictation ended while we were pausing,
        # _on_stop already went by and nobody else will resume. Do it here.
        if self._gate.state != "RECORDING":
            self._resume_media()

    def _resume_media(self):
        players, self._paused_players = self._paused_players, []
        if players:
            threading.Thread(target=media.resume, args=(players,), daemon=True).start()

    def _stop_record(self, force: bool):
        if self._recorder:
            if force:
                self._recorder.force_finish()
            else:
                self._recorder.stop()

    def _partial_loop(self):
        interval = self.cfg.get("stt.partial_interval", 1.5)
        while self._partial_running.is_set():
            time.sleep(interval)
            if not self._partial_running.is_set() or self._recorder is None:
                break
            try:
                a = self._recorder.get_recent_audio()
                # without enough signal we don't transcribe: Whisper hallucinates on silence
                if len(a) / audio.SR < 0.4 or audio.rms_of(a) < self._min_rms():
                    continue
                text = stt.transcribe(a, self.stt_model, self._stt_language(), self.stt_prompt)
                if text and self._partial_running.is_set():
                    self._overlay.update(text)
            except Exception as e:
                log.debug("partial error: %s", e)

    def _min_rms(self) -> float:
        return float(self.cfg.get("audio.min_rms", 50))

    def _stt_language(self) -> str | None:
        """Effective language for STT: mode > menu > config > learned lock.

        A mode can force its own (e.g. Translate EN→ES dictates in English);
        the lock is learned by langlock after 3 consecutive dictations in the
        same language and saves ~1.1s of auto-detection per dictation (measured)."""
        mode_lang = modes.MODES.get(self.mode, {}).get("stt_lang")
        if mode_lang:
            return mode_lang
        manual = self._prefs.get("stt_language", "auto")
        if manual != "auto":
            return manual
        return self.stt_lang or self._prefs.get("stt_lang_lock") or None

    def _on_stop(self, audio_buf, duration: float):
        self._partial_running.clear()
        # The music comes back as soon as the mic closes: the refine may go on
        # for a few seconds, but the user is no longer speaking.
        self._resume_media()
        if self._cancel.is_set():
            threading.Thread(target=self._finish_cancel, daemon=True).start()
            return
        self._play_sound("Tink")    # "got it, processing"
        rec = self._recorder
        had_speech = rec.had_speech if rec else False
        speech_ratio = rec.speech_ratio if rec else 0.0
        self._gate.processing()
        self._refresh_title()
        self._overlay.show("Transcribing…", title="✦ Processing")
        threading.Thread(
            target=self._process,
            args=(audio_buf, duration, had_speech, speech_ratio),
            daemon=True,
        ).start()

    def _flash(self, msg: str, secs: float = 1.6, title: str | None = None):
        """Brief message on the HUD (the finally of _process closes it afterwards)."""
        try:
            self._overlay.show(msg, title=title)
            time.sleep(secs)
        except Exception:
            pass

    # ---------- user notices ----------
    # rumps.notification (NSUserNotification) delivers NOTHING on macOS 26: the app
    # never even gets registered in Notification Center and the notices are
    # silently discarded. Every notice goes out through one of these two paths,
    # both verified with screencapture/CGWindowList:
    #   _alert() → modal NSAlert, for info the user asked for and wants to read.
    #   _hud()   → ephemeral HUD, for background events that must NOT steal focus.

    def _alert(self, title: str, message: str = ""):
        """Modal for info the user asked for. Doesn't block the caller."""

        def show():
            try:
                rumps.alert(title=title, message=message, ok="OK")
            except Exception:
                log.warning("Couldn't show alert %r", title, exc_info=True)

        # NSAlert can only run on the main thread; menu callbacks are already
        # on it, but _warmup and the downloads arrive from daemon threads.
        if threading.current_thread() is threading.main_thread():
            show()
        else:
            try:
                from PyObjCTools import AppHelper

                AppHelper.callAfter(show)
            except Exception:
                log.warning("Couldn't enqueue alert %r", title, exc_info=True)

    def _hud(self, msg: str, title: str | None = None, secs: float = 2.0):
        """Ephemeral notice on the HUD, without blocking or stealing focus.

        Shares the counter with the mode flash: the newest message wins and a
        dictation in progress takes priority (its flow manages the HUD).
        """
        if not self._show_overlay or not getattr(self._overlay, "_built", False):
            log.info("HUD unavailable, logging only: %s — %s", title or "", msg)
            return
        self._mode_flash_seq += 1
        seq = self._mode_flash_seq

        def _do():
            try:
                if self._gate.state != "IDLE":
                    return
                self._overlay.show(msg, title=title)
                time.sleep(secs)
                if self._mode_flash_seq != seq:
                    return  # a newer notice arrived: that one wins
                if self._gate.state != "IDLE":
                    return  # a dictation started
                self._overlay.hide()
            except Exception:
                log.warning("HUD notice failed", exc_info=True)

        threading.Thread(target=_do, daemon=True).start()

    def _finish_cancel(self):
        """Visual wrap-up of a dictation canceled with Esc."""
        self._play_sound("Basso")
        self._flash("(canceled — nothing pasted)", 0.9)
        self._reset_idle()

    def _process(self, audio_buf, duration, had_speech: bool = True, speech_ratio: float = 0.0):
        t0 = time.monotonic()
        try:
            if audio_buf is None or len(audio_buf) == 0:
                log.info("Recording discarded (too short).")
                self._flash("(too short)", 1.0)
                return
            # 0) guards: never send silence to Whisper (it hallucinates "Gracias"/"Thank you").
            # Two distinct silences: RMS≈0 is DIGITAL silence (TCC permission
            # denied or mic muted — must warn, but only once per
            # session); low but nonzero RMS is a quiet room with someone
            # who didn't speak — discreet discard with no system notification.
            level = audio.rms_of(audio_buf)
            if level < self._min_rms():
                if level < 3.0 and not self._mic_warned:
                    self._mic_warned = True
                    log.warning(
                        "Microphone with no signal (RMS=%.0f). Microphone permission granted?", level
                    )
                    self._flash("🎤 No signal from the microphone", 2.5)
                else:
                    log.info("Discarded: no voice (RMS=%.0f).", level)
                    self._flash("(no speech — nothing pasted)", 1.2)
                return
            self._mic_warned = False  # healthy audio: if the mic dies later, warn again
            if not had_speech:
                log.info("No voice detected by VAD (RMS=%.0f).", level)
                self._flash("(no speech detected)", 1.2)
                return
            # 1) final transcription
            stt_t0 = time.monotonic()
            transcript = stt.transcribe(
                audio_buf, self.stt_model, self._stt_language(), self.stt_prompt
            )
            stt_t1 = time.monotonic()
            log.info(
                "Transcription (%.1fs, RMS=%.0f, voice=%.0f%%): %s",
                duration, level, speech_ratio * 100, transcript,
            )
            if self._cancel.is_set():
                log.info("Cancelled after transcription; nothing pasted.")
                self._flash("(canceled — nothing pasted)", 0.9)
                return
            if not transcript:
                # Distinguish "you said nothing" from "the STT engine is down":
                # with speech detected by the VAD and the server not responding,
                # the problem is the engine's and retrying in a few seconds works.
                if had_speech and not stt.server_ready():
                    log.warning("STT with no transcription but voice detected: server down.")
                    self._flash("⚠️ Speech engine restarting — try again in a moment", 2.2)
                else:
                    self._flash("(no speech detected)", 1.2)
                return
            if stt.looks_hallucinated(transcript, speech_ratio):
                log.warning("Discarded as Whisper hallucination: %r", transcript)
                self._flash("(didn't catch that — say it again)", 1.5)
                return
            # Language auto-lock: only learns while this dictation went out WITHOUT
            # a fixed language (no mode, no menu, no config, no previous lock).
            if self._stt_language() is None:
                try:
                    streak, lock = langlock.update_lock(
                        self._prefs.get("lang_streak", []),
                        langlock.detect_lang_es_en(transcript),
                    )
                    if (streak != self._prefs.get("lang_streak")
                            or lock != self._prefs.get("stt_lang_lock")):
                        self._prefs["lang_streak"] = streak
                        self._prefs["stt_lang_lock"] = lock
                        _save_prefs(self._prefs)
                        if lock:
                            log.info("Dictation language pinned automatically: %s", lock)
                            self._on_main(self._refresh_lang_menu)
                except Exception:
                    pass
            # Show the transcription right away: the refine wait (2-6s) is easier
            # to understand seeing the text than with an opaque "Processing…".
            self._overlay.show(transcript, title="✦ Polishing")
            # 2) per-mode refine (on failure, falls back to the raw transcription: never blocks)
            # Fast-lane: short dictations in flagged modes get pasted as-is —
            # Whisper already punctuates short sentences well and we save 2-6s of LLM.
            fast_words = int(self.cfg.get("llm.fast_lane_words", 9))
            n_words = len(transcript.split())
            # refiner is only instantiated on the branch that actually calls refine():
            # the notice further down checks it with getattr(refiner, ...), so
            # in fast-lane (refiner=None) it simply doesn't fire — never a
            # stale flag from a previous dictation.
            refiner = None
            # Same as refiner=None: it's only set to True inside the branch
            # that actually calls refine(), so in fast-lane it stays
            # inert (never a notice from a previous dictation).
            refine_crashed = False
            if (
                fast_words > 0
                and modes.MODES.get(self.mode, {}).get("fast_lane")
                and n_words <= fast_words
            ):
                log.info("Fast-lane (%d words): no LLM refine.", n_words)
                final = transcript
            else:
                refiner = refine.Refiner(self.cfg)
                try:
                    final = refiner.refine(transcript, self.mode, self.language)
                except Exception:
                    log.exception("Refine failed; using raw transcription")
                    final = transcript
                    # Safety net: a refine bug doesn't lose the dictation
                    # (it's pasted raw), but that must NOT happen silently —
                    # the user has to find out just like with last_fallback.
                    refine_crashed = True
            final = final or transcript
            ref_t1 = time.monotonic()
            log.info(
                "⏱ stt=%dms refine=%dms total=%dms",
                int((stt_t1 - stt_t0) * 1000),
                int((ref_t1 - stt_t1) * 1000),
                int((ref_t1 - stt_t0) * 1000),
            )
            # Personal dictionary replacements: deterministic correction of the
            # spellings Whisper keeps getting wrong even when they're in the prompt.
            try:
                final = dictionary.apply(final)
            except Exception:
                log.debug("dictionary.apply failed; continuing without replacements", exc_info=True)
            if self._cancel.is_set():
                log.info("Cancelled during refine; nothing pasted.")
                self._flash("(canceled — nothing pasted)", 0.9)
                return
            self._last_result = final
            self._push_history(final)
            stats.bump(len(final.split()), duration)
            log.info("Final (+%.1fs): %s", time.monotonic() - t0, final)
            # 3) deliver
            auto_paste = bool(self.cfg.get("output.auto_paste", True))
            copy = bool(self.cfg.get("output.copy_to_clipboard", True))
            # Modes with Markdown structure: a second HTML flavor on the
            # clipboard so Mail/Gmail/Notion paste headings and
            # lists rendered (plain-text apps don't even see it).
            html = None
            if modes.MODES.get(self.mode, {}).get("rich_paste"):
                try:
                    html = richtext.markdown_to_html(final)
                except Exception:
                    log.debug("markdown_to_html failed; pasting plain text only", exc_info=True)
            status = output.deliver(final, auto_paste=auto_paste, copy=copy, html=html)
            # Remote LLM tokens, if any — ALWAYS after delivering:
            # nothing on this path may prevent or precede the paste (see
            # _record_token_usage). getattr because in fast-lane refiner is
            # None — the same pattern as the last_fallback notice below.
            _record_token_usage(refiner, self._prefs)
            # Auto-learn: watch the field we just pasted into for a few seconds.
            # The correction the user makes right now, in a field they are
            # about to leave (send the message, close the tab, switch app), is
            # exactly the one the next-dictation read used to lose. Spawned
            # AFTER the token accounting and wrapped like _start_record's
            # thread: nothing here may pre-empt the notices below, which are
            # what rescue a paste that failed.
            if self._prefs.get("auto_learn", True):
                try:
                    gen, stop = self._learn.start(final)
                    threading.Thread(
                        target=self._auto_learn_watch,
                        args=(final, gen, stop),
                        daemon=True,
                    ).start()
                except Exception:
                    log.debug("auto-learn: couldn't spawn the window", exc_info=True)
            # The text is already pasted (refined or not): this notice only says
            # the AI didn't act and the raw transcription was pasted due to a
            # failure (network down, broken provider..., or the catch-all above
            # if refine() threw something not even Refiner knew how to handle).
            # The deliberate paths (literal mode, fast-lane, "none" backend)
            # leave neither last_fallback nor refine_crashed set.
            if refine_crashed or getattr(refiner, "last_fallback", None):
                self._flash(
                    "Your words were pasted as-is.", 2.2,
                    title="⚠ AI didn't answer",
                )
            if auto_paste and status == "copied":
                # The paste failed but the text IS on the clipboard:
                # without this notice the user sees "nothing happens" and loses it.
                self._flash("Press ⌘V to paste it where you need it.", 2.2, title="✓ Copied")
            else:
                # show the result briefly and close
                self._overlay.show(final, title="✓ Pasted")
                time.sleep(1.6)
        except Exception:
            log.exception("Error processing dictation")
        finally:
            self._reset_idle()
        # With the gate already IDLE, whatever the fallback learned while this
        # dictation was recording can finally paint without _hud eating it.
        self._drain_learn_note()

    def _drain_learn_note(self) -> None:
        """Shows the "✨ Learned" notice, or keeps it until the HUD is free."""
        _drain_learned_note(
            self._learn,
            self._gate.state == "IDLE",
            self._prefs,
            lambda note: self._hud(note, title=i18n.t("✨ Learned")),
        )

    def _auto_learn_watch(self, pasted: str, gen: int, stop) -> None:
        """Post-paste window: watches the field just pasted into and learns.

        Runs on a daemon thread spawned at delivery time. It reads the focused
        field a handful of times over a few seconds — the same scope as the
        fallback read, several times — and only learns from a state it saw
        settle. Neither the text nor anything derived from it is logged or
        persisted: only the learned pairs reach the dictionary.
        """
        if _watch_and_learn(self.cfg, self._learn, pasted, gen, stop):
            self._drain_learn_note()  # the gate is IDLE: it paints right now

    def _auto_learn_check(self, pasted: str) -> None:
        """Fallback: one read at the start of the NEXT dictation. Best-effort.

        The post-paste window covers the field while the user is still in it;
        this catches what they corrected afterwards — and it is the only path
        left when the window found nothing (an app whose AXValue only settles
        late, a correction made minutes later). The notice is parked because
        at this moment the gate is recording and _hud would discard it.
        """
        try:
            field = axfield.read_focused_text()
            if not field:
                return
            learned = learn.auto_learn_from(pasted, field)
            if learned:
                self._learn.park_note("\n".join(learned))
        except Exception:
            log.debug("auto-learn silencioso", exc_info=True)

    def _reset_idle(self):
        self._overlay.hide()
        self._gate.idle()
        self._refresh_title()

    # ---------- history ----------
    def _save_history_on(self) -> bool:
        return bool(self.cfg.get("app.save_history", True))

    def _push_history(self, text: str):
        self._history.appendleft(text)
        self._last_dictation = text
        # undoes a previous search filter. Called from the _process
        # thread (background): the NSMenuItem title write goes through main.
        self._on_main(lambda: setattr(self.recent_parent, "title", i18n.t("Recent")))
        self._refresh_recent()
        if self._save_history_on():
            history.append(text, self.mode)

    def _refresh_recent(self):
        """Dumps self._history into the Recent submenu. Called from the _process
        and _warmup threads (background): mutating an NSMenuItem's title/setHidden_
        with the menu open crashes (SIGTRAP), so EVERYTHING goes through _on_main.
        (Only updates already-created NSMenuItems; adding/removing isn't done here.)"""
        def apply():
            try:
                self._recent_empty._menuitem.setHidden_(len(self._history) > 0)
                for i, mi in enumerate(self._recent_items):
                    if i < len(self._history):
                        t = self._history[i].replace("\n", " ")
                        mi.title = (t[:57] + "…") if len(t) > 58 else t
                        mi._menuitem.setHidden_(False)
                    else:
                        mi._menuitem.setHidden_(True)
            except Exception:
                log.debug("Couldn't refresh the Recent submenu", exc_info=True)
        self._on_main(apply)

    def _search_history(self, _sender):
        if not self._save_history_on():
            self._alert(
                i18n.t("History is off"),
                i18n.t("Set app.save_history: true in config.yaml to keep dictations."),
            )
            return
        resp = rumps.Window(
            message=i18n.t("Find past dictations containing:"),
            title=i18n.t("Search history"),
            ok=i18n.t("Search"),
            cancel=i18n.t("Cancel"),
            dimensions=(300, 24),
        ).run()
        query = (resp.text or "").strip() if resp.clicked else ""
        if not query:
            return
        hits = history.search(query, HISTORY_SIZE)
        if not hits:
            self._alert(
                i18n.t("No matches"),
                i18n.t('Nothing matches "{query}".').format(query=query),
            )
            return
        # The results are served in the Recent submenu itself (click = copy);
        # the next dictation returns it to plain "Recent".
        self._history.clear()
        for t in reversed(hits):
            self._history.appendleft(t)
        self.recent_parent.title = f"{i18n.t('Recent')} — “{query}”"
        self._refresh_recent()
        self._alert(
            i18n.t("{n} match(es)").format(n=len(hits)),
            i18n.t("They're in the Recent submenu — click one to copy it."),
        )

    def _make_recent_cb(self, i: int):
        def cb(_sender):
            if i < len(self._history):
                output.copy_to_clipboard(self._history[i])
                self._hud(self._history[i][:80], title="✓ Copied to clipboard")
        return cb

    # ---------- settings ----------
    def _build_stt_prompt(self) -> str | None:
        terms = [str(t).strip() for t in (self.cfg.get("stt.dictionary", []) or [])]
        try:
            for t in dictionary.stt_terms():
                if t not in terms:
                    terms.append(t)
        except Exception:
            log.debug("Couldn't read the personal dictionary", exc_info=True)
        return ", ".join(t for t in terms if t)[:600] or None

    def _correct_last(self, _sender):
        """Corrects the last dictation and learns the changed spellings.

        rumps.Window is modal and runs on the main thread (menu callback,
        we're already there). The corrected text is re-copied to the clipboard:
        the #1 reason to correct is pasting it right again.
        """
        if not self._last_dictation:
            self._alert(i18n.t("Nothing to correct"), i18n.t("Dictate something first."))
            return
        original = self._last_dictation
        resp = rumps.Window(
            message=i18n.t(
                "Fix any misheard words — Voooxly learns the right "
                "spelling for next time:"
            ),
            title=i18n.t("Correct last dictation"),
            default_text=original,
            ok=i18n.t("Learn & copy"),
            cancel=i18n.t("Cancel"),
            dimensions=(360, 120),
        ).run()
        corrected = (resp.text or "").strip() if resp.clicked else ""
        if not corrected or corrected == original:
            return
        from . import learn

        descs = learn.learn_from(original, corrected)
        try:
            self._last_dictation = corrected
            # If _history is in search mode (_search_history filled it
            # with hits), [0] isn't this dictation: we don't overwrite it.
            if self._history and self._history[0] == original:
                self._history[0] = corrected
                self._refresh_recent()
            output.copy_to_clipboard(corrected)
        except Exception:
            log.debug("Couldn't re-copy the correction", exc_info=True)
        if descs:
            self.stt_prompt = self._build_stt_prompt()  # biases the next one already
            self._hud("\n".join(descs), title="✓ Learned")
        else:
            self._hud("Copied — no new spellings to learn.", title="✓ Corrected")

    def _add_to_dictionary(self, _sender):
        resp = rumps.Window(
            message=(
                "A word Whisper misspells (e.g. Ucademy), or a fix:\n"
                "wrong spelling -> right spelling"
            ),
            title=i18n.t("Add to dictionary"),
            ok=i18n.t("Add"),
            cancel=i18n.t("Cancel"),
            dimensions=(300, 24),
        ).run()
        entry = (resp.text or "").strip() if resp.clicked else ""
        if not entry:
            return
        try:
            desc = dictionary.add(entry)
        except ValueError as e:
            self._alert(i18n.t("Not added"), str(e))
            return
        self.stt_prompt = self._build_stt_prompt()  # biases the next dictation already
        self._hud(desc, title="✓ Added to dictionary")

    def _install_launch_agent(self) -> bool:
        try:
            os.makedirs(os.path.dirname(LAUNCH_AGENT), exist_ok=True)
            with open(LAUNCH_AGENT, "wb") as f:
                # `open -a` instead of the binary directly: doesn't duplicate the
                # instance if Voooxly is already running and survives the .app being moved
                plistlib.dump(
                    {
                        "Label": "com.eduardocrovetto.voooxly",
                        "ProgramArguments": ["/usr/bin/open", "-a", "Voooxly"],
                        "RunAtLoad": True,
                    },
                    f,
                )
            return True
        except Exception:
            log.exception("Couldn't create the LaunchAgent")
            return False

    def _apply_login_default(self):
        """Start at login ships enabled from the factory, exactly ONCE.

        A hotkey app is only useful while it's running: if the user reboots
        and Voooxly doesn't start, the hotkey "doesn't work". If the user turns
        it off in Settings, the flag in prefs prevents ever re-enabling it on them.
        """
        if self._prefs.get("login_default_applied"):
            return
        if not os.path.exists(LAUNCH_AGENT) and self._install_launch_agent():
            self.login_item.state = 1
            log.info("Start at login enabled by default (first run).")
        self._prefs["login_default_applied"] = True
        _save_prefs(self._prefs)

    def _toggle_login(self, sender):
        if sender.state:
            try:
                os.unlink(LAUNCH_AGENT)
            except FileNotFoundError:
                pass
            except Exception:
                log.exception("Couldn't remove the LaunchAgent")
                return
            sender.state = 0
        else:
            if self._install_launch_agent():
                sender.state = 1

    def _toggle_sounds(self, sender):
        self._sounds = not self._sounds
        sender.state = 1 if self._sounds else 0
        self._prefs["sounds"] = self._sounds
        _save_prefs(self._prefs)
        if self._sounds:
            self._play_sound("Pop")

    def _open_shortcuts(self, _sender):
        """Opens the Shortcuts window. rumps menu callback → already on the
        main thread, which is the only one where an NSWindow can be created."""
        from . import settings_window

        if getattr(self, "_shortcuts_win", None) is not None:
            self._shortcuts_win.show()
            return
        self._shortcuts_win = (
            settings_window.ShortcutsController.alloc()
            .initWithState_onChange_(self._shortcuts, self._apply_shortcut)
        )
        self._shortcuts_win.attachHotkey_(self._hotkey)
        self._shortcuts_win.show()

    def _apply_shortcut(self, sid: str, fila: dict) -> tuple[bool, str]:
        """The window's on_change: applies to the hotkey and persists if it sticks."""
        ok, msg = apply_shortcut(self._hotkey, sid, fila)
        if not ok:
            return False, msg
        self._shortcuts[sid] = fila
        if sid == "dictation":
            self._dictation_key = fila["keys"][0]
            self._toggle_mode = fila.get("style", "hold")
        self._prefs.setdefault("shortcuts", {})[sid] = fila
        _save_prefs(self._prefs)
        self._refresh_shortcut_rows()
        return True, ""

    def _refresh_shortcut_rows(self):
        """Repaints the bindings of the bar's Shortcuts submenu. NSMenuItem
        titles are AppKit: through the main thread, like every repaint."""
        def apply():
            for sid, texto in shortcuts.menu_summary(self._shortcuts):
                mi = self._shortcut_rows.get(sid)
                if mi is not None:
                    mi.title = texto
        self._on_main(apply)

    def _show_guide(self, _sender):
        """Opens the usage guide. rumps menu callback → main thread,
        the only one where guide.py can create its NSWindow."""
        from . import guide

        guide.show_guide(self._shortcuts)

    def _play_sound(self, name: str):
        if not self._sounds:
            return
        try:
            from AppKit import NSSound

            snd = self._snd_cache.get(name)
            if snd is None:
                snd = NSSound.soundNamed_(name)
                if snd is None:
                    return
                snd.setVolume_(0.35)   # subtle, Wispr-style
                self._snd_cache[name] = snd
            snd.stop()   # in case it's still playing from last time
            snd.play()
        except Exception:
            pass

    # ---------- menu actions ----------
    def _update_ai_item(self, force: bool = True) -> str:
        """Marks the active provider in the submenu. Returns its key.

        The AppKit writes (mi.state, self.ai.title) go through _on_main: this is
        called from the _warmup thread (initial detection + keepalive every N min),
        not only from menu callbacks. detect_backend (network) stays on the calling
        thread so the value is returned synchronously."""
        from . import ai_settings

        sel = ai_settings.load(self._prefs)
        if sel is None:
            detected = refine.detect_backend(self.cfg, force=force)
            title = ai_engine_title(sel, detected)
            ret = detected
        else:
            title = ai_engine_title(sel, "")
            ret = sel.provider.key

        def apply():
            for prov_key, mi in self._ai_items.items():
                mi.state = 1 if (sel and sel.provider.key == prov_key) else 0
            self.ai.title = title
        self._on_main(apply)
        return ret

    def _apply_ai_selection(self, sel) -> None:
        """Thin delegate: the logic lives in apply_ai_selection (module
        level) so it can be tested without instantiating VoooxlyApp."""
        apply_ai_selection(self.cfg, sel)

    def _make_provider_cb(self, prov_key: str):
        def cb(_sender):
            self._connect_provider(prov_key)
        return cb

    def _connect_ai_from_onboarding(self):
        """Provider picker for the onboarding's "Connect AI" step, which
        delegates to _connect_provider (proven flow: asks for the key, validates,
        saves to keychain + prefs). What's connected persists across the app relaunch.

        Nobody has AI on first launch, so there's no "test" here: it's
        connecting. It's optional; the onboarding makes clear dictation works without it.
        """
        from AppKit import NSAlert, NSPopUpButton
        from Foundation import NSMakeRect

        from . import providers

        keys = list(providers.PROVIDERS.keys())
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Connect an AI engine")
        alert.setInformativeText_(
            "Pick a provider — Voooxly will ask for its API key next. It's "
            "optional; dictation works fine without it.")
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(0, 0, 260, 26), False)
        for k in keys:
            popup.addItemWithTitle_(providers.PROVIDERS[k].label)
        alert.setAccessoryView_(popup)
        alert.addButtonWithTitle_("Continue")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() != 1000:  # NSAlertFirstButtonReturn = Continue
            return
        self._connect_provider(keys[popup.indexOfSelectedItem()])

    def _choose_model(self, prov, actual: str | None) -> str | None:
        """Provider model picker: the curated list from providers.py.

        v1.4 feedback ("internally select a specific model when an option
        is chosen, like cloud"): connecting a provider used to impose its
        default without asking. The default goes first and preselected (or the
        model the user already had saved, if it's still in the list).
        Returns the chosen model, or None if canceled.
        """
        from AppKit import NSAlert, NSPopUpButton
        from Foundation import NSMakeRect

        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Choose the {prov.name} model")
        alert.setInformativeText_(
            "The first one is the recommended default. Lighter models answer "
            "faster; bigger ones write better.")
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(0, 0, 260, 26), False)
        for m in prov.models:
            popup.addItemWithTitle_(m)
        if actual in prov.models:
            popup.selectItemWithTitle_(actual)
        alert.setAccessoryView_(popup)
        alert.addButtonWithTitle_("Continue")
        alert.addButtonWithTitle_("Cancel")
        if alert.runModal() != 1000:  # NSAlertFirstButtonReturn = Continue
            return None
        return prov.models[popup.indexOfSelectedItem()]

    def _connect_provider(self, prov_key: str):
        """Asks for whatever is missing, validates against the provider and saves if it works."""
        from . import ai_settings, keychain, providers

        prov = providers.get(prov_key)
        if prov is None:
            return
        base_url, model = prov.base_url, prov.default_model

        if len(prov.models) > 1:
            sel_previa = ai_settings.load(self._prefs)
            actual = (
                sel_previa.model
                if sel_previa and sel_previa.provider.key == prov.key
                else None
            )
            model = self._choose_model(prov, actual)
            if model is None:
                return

        if prov.kind == "ollama":
            # The model isn't assumed: THEIR Ollama gets asked (Task 5).
            # Neither is the host: llm.ollama.host may come from the user's
            # config or from VOOOXLY_LLM_OLLAMA_HOST (remote Ollama), and THAT
            # host is the one to probe — and to save as the selection's base_url,
            # so that what was tested is exactly what gets persisted.
            base_url = (
                self.cfg.get("llm.ollama.host", "")
                or base_url
                or "http://localhost:11434"
            )
            modelos = refine.list_ollama_models(base_url)
            if not modelos:
                self._alert(
                    "Ollama has no models",
                    "Install Ollama and pull a model (for example: "
                    "ollama pull llama3.2), then click here again.",
                )
                return
            listado = "\n".join(f"• {m}" for m in modelos)
            resp = rumps.Window(
                message=f"Models on your Ollama:\n{listado}\n\nType the one to use:",
                title="Choose your Ollama model",
                default_text=modelos[0],
                ok="Next", cancel="Cancel", dimensions=(320, 24),
            ).run()
            if not resp.clicked or not resp.text.strip():
                return
            model = resp.text.strip()

        # The key is only asked for if the keychain doesn't have it: whoever
        # already connected once doesn't have to paste it again to switch
        # models (Eduardo's feedback: the dialog always showed, key already saved).
        api_key = None
        pedida = False
        if prov.needs_key:
            api_key = keychain.get_key(prov.key)
            if not api_key:
                api_key = self._pedir_key(prov)
                pedida = True
                if api_key is None:
                    return
                if not api_key:
                    self._alert("No API key", f"{prov.name} needs a key to work.")
                    return

        sel = ai_settings.Selection(prov, base_url, model)
        ok, msg = refine.validate(sel, api_key)
        if not ok and prov.needs_key and not pedida:
            # The saved key may be expired or revoked: a new one is asked
            # for ONCE and revalidated — without this the user would be stuck
            # in a loop where the failure repeats and there's no way to change it.
            nueva = self._pedir_key(prov, reintento=True)
            if nueva:
                api_key = nueva
                ok, msg = refine.validate(sel, api_key)
        if not ok:
            self._alert(f"Couldn't connect to {prov.name}", msg)
            return

        key_guardada = True
        if prov.needs_key and api_key:
            # set_key can return False (a keychain refusing the write):
            # the session keeps working because the key is already exported and
            # validated, but on restart it would vanish silently. We push
            # ahead (punishing the user twice doesn't fix the keychain)
            # and swap the final alert for an honest notice.
            key_guardada = keychain.set_key(prov.key, api_key)
        self._prefs = ai_settings.save(self._prefs, prov.key, base_url, model)
        _save_prefs(self._prefs)
        # Without this, until the next restart the app would dictate with the
        # old config: prefs.json is only read at startup. "Connected ✓" and then nothing.
        self._apply_ai_selection(ai_settings.load(self._prefs))
        refine.detect_backend(self.cfg, force=True)
        self._update_ai_item(force=False)
        if key_guardada:
            self._alert("AI engine connected", msg)
        else:
            self._alert(
                "Connected — but the key wasn't saved",
                "Your key works for this session, but macOS Keychain refused "
                "to store it. You'll be asked for it again after restarting "
                "Voooxly.",
            )

    def _pedir_key(self, prov, reintento=False):
        """API key dialog. None = canceled; "" = pressed Connect while blank.

        Only shown if the keychain had no key for this provider — or,
        with reintento=True, if the saved one just failed validation and
        the chance to paste a new one must be given.
        """
        msg = (
            f"The saved key for {prov.name} didn't work. Paste a new one:"
            if reintento else f"API key for {prov.name}:"
        )
        resp = rumps.Window(
            message=msg,
            title="Connect AI engine",
            ok="Connect", cancel="Cancel",
            dimensions=(320, 24), secure=True,
        ).run()
        if not resp.clicked:
            return None
        return resp.text.strip()

    def _test_ai(self, _sender):
        from . import ai_settings, keychain

        sel = ai_settings.load(self._prefs)
        if sel is None:
            self._alert("No AI engine selected", "Pick one from the AI engine menu first.")
            return
        api_key = keychain.get_key(sel.provider.key) if sel.provider.needs_key else None
        ok, msg = refine.validate(sel, api_key)
        self._alert("Connection OK" if ok else "Connection failed", msg)

    def _reset_to_auto(self, _sender):
        """Returns control to the auto-detection cascade."""
        from . import ai_settings

        for clave in (ai_settings.CLAVE_PROVEEDOR, ai_settings.CLAVE_BASE_URL,
                      ai_settings.CLAVE_MODELO):
            self._prefs.pop(clave, None)
        _save_prefs(self._prefs)
        self.cfg._set_path("llm.backend", "auto")
        b = refine.detect_backend(self.cfg, force=True)
        self._update_ai_item(force=False)
        self._alert("Back to automatic", f"Detected: {b}.")

    def _open_update(self, _sender):
        if not self._update_url or self._update_downloading:
            return
        self._update_downloading = True
        threading.Thread(target=self._download_update, daemon=True).start()

    def _maybe_prompt_update(self, info: dict) -> None:
        """The "Update available" pop-up with Download now / Later.

        Once per version, persisted in prefs (should_prompt): whoever
        picks "Later" doesn't see the alert again on every launch — only when
        a newer version comes out. The menu item always remains as the way
        to install later. The caller must leave _update_url and
        _update_version set beforehand: "Download now" delegates to _open_update.
        """
        if not updates.should_prompt(info, self._prefs.get("update_prompted_version")):
            return
        self._prefs["update_prompted_version"] = info["version"]
        _save_prefs(self._prefs)
        ver = info["version"]
        notes = (info.get("notes") or "").strip()
        body = f"Voooxly {ver} is ready to install." + (f"\n\n{notes}" if notes else "")

        def ask():
            try:
                # rumps.alert: 1 = ok button ("Download now"), 0 = cancel.
                if rumps.alert(title=i18n.t("Update available"), message=body,
                               ok=i18n.t("Download now"), cancel=i18n.t("Later")) == 1:
                    self._open_update(None)
            except Exception:
                log.warning("Couldn't show the update pop-up", exc_info=True)

        # NSAlert can only run on the main thread; this arrives from
        # _warmup or the periodic timer (daemon threads).
        self._on_main(ask)

    def _download_update(self):
        # Downloads the DMG to ~/Downloads and offers to install it by itself
        # (v1.6 feedback: no dragging into Applications). If the download fails,
        # the URL opens in the browser (the behavior of old) so the user
        # isn't left stranded.
        version = self._update_version or "latest"
        self._hud("The menu bar icon shows progress.", title=f"⏬ Downloading Voooxly {version}")
        try:
            path = updates.download(
                self._update_url, version,
                progress_cb=lambda p: setattr(self, "title", f"⏬ {p}%"),
            )
        finally:
            self._update_downloading = False
            self._refresh_title()
        if path:
            self._offer_install(path)
        else:
            subprocess.run(["open", self._update_url], check=False)

    def _offer_install(self, dmg_path):
        """After the download: install and relaunch in one click.

        Whoever picks "Later" keeps the DMG in ~/Downloads and the menu item
        stays there as the way back."""
        ver = self._update_version or "latest"

        def ask():
            try:
                # rumps.alert: 1 = ok button ("Install and relaunch"), 0 = cancel.
                if rumps.alert(
                    title=i18n.t("Update downloaded"),
                    message=f"Voooxly {ver} is ready. Install it and relaunch "
                            "now? Voooxly restarts by itself in a few seconds.",
                    ok=i18n.t("Install and relaunch"), cancel=i18n.t("Later"),
                ) == 1:
                    self._install_update(dmg_path)
            except Exception:
                log.warning("Couldn't offer the install", exc_info=True)

        # NSAlert only runs on the main thread; we come from the download thread.
        self._on_main(ask)

    def _install_update(self, dmg_path):
        """Mounts the DMG, leaves the swap script running OUTSIDE the bundle
        and gets out of the way: the script waits for us to die, replaces the
        .app (with a backup) and relaunches. If it can't be staged (dev with no
        bundle, weird DMG, hdiutil down), falls back to the manual flow of old:
        open the DMG and offer to quit the app for the drag."""

        def work():
            script = None
            try:
                script = updates.stage_install(
                    dmg_path, self._bundle_path(), os.getpid())
            except Exception:
                log.warning("Couldn't prepare the install", exc_info=True)
            if script:
                subprocess.Popen(["/bin/bash", str(script)],
                                 start_new_session=True)
                self._on_main(lambda: self._quit(None))
            else:
                subprocess.run(["open", str(dmg_path)], check=False)
                self._offer_quit_to_install()

        # hdiutil takes seconds: off the main thread so the menu doesn't freeze.
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _bundle_path():
        """Path of the installed .app, or None outside a bundle (dev)."""
        try:
            from AppKit import NSBundle

            p = str(NSBundle.mainBundle().bundlePath())
            if p.endswith(".app"):
                from pathlib import Path

                return Path(p)
        except Exception:
            log.debug("Couldn't resolve the bundle", exc_info=True)
        return None

    def _offer_quit_to_install(self):
        """After opening the DMG, offers to quit Voooxly so it can be replaced.

        Finder won't overwrite a running app ("the item is in use"): it's held
        by the process itself and by the whisper-server running INSIDE the
        bundle. _quit stops both, so accepting here is what makes the drag
        to Applications possible.
        """

        def ask():
            try:
                # rumps.alert: 1 = ok button ("Quit now"), 0 = cancel.
                if rumps.alert(
                    title=i18n.t("Update downloaded"),
                    message="Drag Voooxly into Applications to replace this "
                            "version, then open it again.\n\nVoooxly has to "
                            "quit first — macOS won't let you replace an app "
                            "that's running.",
                    ok=i18n.t("Quit now"), cancel=i18n.t("Not yet"),
                ) == 1:
                    self._quit(None)
            except Exception:
                log.warning("Couldn't prompt to quit for install", exc_info=True)

        # NSAlert only runs on the main thread; we come from the download thread.
        self._on_main(ask)

    def _show_about(self, _sender):
        """About dialog: icon, version and a button to check for updates."""
        from AppKit import (
            NSAlert,
            NSAlertFirstButtonReturn,
            NSAlertStyleInformational,
            NSApp,
        )

        alert = NSAlert.alloc().init()
        alert.setMessageText_("Voooxly")
        alert.setInformativeText_(
            f"Version {updates.current_version()}\n\nLocal dictation on your Mac."
        )
        alert.setIcon_(NSApp.applicationIconImage())
        alert.setAlertStyle_(NSAlertStyleInformational)
        alert.addButtonWithTitle_(i18n.t("Check for updates…"))
        alert.addButtonWithTitle_("OK")
        if alert.runModal() == NSAlertFirstButtonReturn:
            self._check_now(None)

    def _check_now(self, _sender):
        """Manual check (via the About button). Offloaded to a thread; alert with the result."""
        def _work():
            status, info = updates.check_status()
            def _on_done():
                if status == updates.UPDATE_AVAILABLE and info:
                    self._update_url = info["url"]
                    self._update_version = info["version"]
                    ver = info["version"]

                    def _show():
                        self.update_item.title = i18n.t("Update to {ver} →").format(ver=ver)
                        self.update_item._menuitem.setHidden_(False)

                    self._on_main(_show)
                title, message = check_now_message(
                    status, info, updates.current_version()
                )
                self._alert(title, message)

            self._on_main(_on_done)

        threading.Thread(target=_work, daemon=True).start()

    def _schedule_update_check(self):
        """Re-check every updates.CHECK_INTERVAL. Reschedules itself; cancelable."""
        self._update_timer = threading.Timer(
            updates.CHECK_INTERVAL, self._periodic_update_check
        )
        self._update_timer.daemon = True
        self._update_timer.start()

    def _periodic_update_check(self):
        # Silent except the first time a new version shows up: ephemeral
        # HUD (once per version) + the menu item. Network failures: log.
        try:
            info = updates.check()
            if info:
                self._update_url = info["url"]
                self._update_version = info["version"]
                ver = info["version"]

                def _show():
                    self.update_item.title = i18n.t("Update to {ver} →").format(ver=ver)
                    self.update_item._menuitem.setHidden_(False)

                self._on_main(_show)
                if updates.should_notify(info, self._notified_update_version):
                    self._notified_update_version = ver
                    # Before: an ephemeral HUD that was easy to miss. Now a real
                    # pop-up (v1.4 feedback), with its own persisted per-version
                    # gate so it doesn't repeat across launches.
                    self._maybe_prompt_update(info)
        except Exception:
            log.debug("periodic re-check failed (ignored)", exc_info=True)
        finally:
            self._schedule_update_check()

    def _show_stats(self, _sender):
        self._alert("Your dictation stats", stats.summary())

    def _quit(self, _sender):
        try:
            self._partial_running.clear()
            if self._recorder:
                self._recorder.stop()
            if self._hotkey:
                self._hotkey.stop()
            if self._update_timer:
                self._update_timer.cancel()
            stt.stop_server()
        finally:
            rumps.quit_application()

    # ---------- lifecycle ----------
    def run(self):
        # Create NSApplication on the main thread BEFORE starting pynput: pynput's
        # Listener calls TIS/TSM from its thread and if it races the initialization
        # of NSApplication (which also touches TSM) macOS aborts with SIGABRT.
        from AppKit import NSApplication

        _ = NSApplication.sharedApplication()
        # Build pynput's Controller right now: its __init__ queries TIS/TSM and
        # doing it later, from the _process thread, races the hotkey's listener
        # and HIToolbox kills the process (SIGTRAP, uncatchable). No other
        # threads exist yet and we're on the main thread, which is where TSM wants it.
        output.warmup()
        # The key lives in the keychain; the backends read it from os.environ. Without
        # this bridge the connection is lost on every restart.
        try:
            from . import ai_settings, keychain

            sel = ai_settings.load(self._prefs)
            if sel and sel.provider.needs_key:
                refine.export_key(sel, keychain.get_key(sel.provider.key))
            # Same helper _connect_provider uses: writing llm.openai.base_url
            # unconditionally here was the same per-kind path bug the
            # review caught in _probe (Task 4), repeated at startup.
            self._apply_ai_selection(sel)
        except Exception:
            log.warning("Couldn't restore the saved provider", exc_info=True)
        # Build the overlay on the main thread BEFORE any dictation:
        # NSPanel can only be instantiated here (AppKit throws if it's done from
        # the hotkey thread when the dictation key is pressed).
        if self._show_overlay:
            try:
                self._overlay.build()
            except Exception as e:
                log.warning("No se pudo construir el overlay: %s", e)
        # First launch (or revoked permission): the assistant explains what's
        # missing and guides each step. It goes here, on the main thread, because
        # NSWindow can't be instantiated off it. Non-blocking: the window coexists
        # with the app. needs_setup() probes permissions (mic, Accessibility): it's
        # called ONCE and reused. Defaults to True so a probe failure leaves the
        # cleanup alone instead of dropping an alert on an already-broken startup.
        needs_setup = True
        try:
            needs_setup = setup_checks.needs_setup()
            if needs_setup:
                from .onboarding import show_onboarding

                show_onboarding(on_finish=self._on_onboarding_done,
                                on_connect_ai=self._connect_ai_from_onboarding)
        except Exception as e:
            log.warning("Couldn't show onboarding: %s", e)
        # Setup already complete: if the installer's DMG is still mounted, we offer
        # to eject it and send it to the trash. It goes here, on the main thread,
        # which is what NSAlert demands. Asks a single time (flag in prefs).
        if not needs_setup:
            from AppKit import NSBundle

            from .installer_cleanup import maybe_clean_up

            maybe_clean_up(self._prefs, _save_prefs,
                           str(NSBundle.mainBundle().bundlePath()))
        # "What's new": the first launch of a freshly released version
        # tells what changed (Jeff's v1.6 feedback: it updated and you couldn't
        # tell what was new). The Timer gives 1.5 s of air to avoid overlapping
        # the startup; _alert already knows how to queue onto the main thread.
        # The last_run_version mark is persisted on fresh installs too so
        # that the NEXT version does show its notes.
        try:
            cur = updates.current_version()
            if not needs_setup and updates.should_show_whats_new(self._prefs, cur):
                whats_new_title = i18n.t("What's new in Voooxly") + f" {cur}"
                t = threading.Timer(
                    1.5, lambda: self._alert(whats_new_title,
                                             updates.WHATS_NEW))
                t.daemon = True
                t.start()
            if self._prefs.get("last_run_version") != cur:
                self._prefs["last_run_version"] = cur
                _save_prefs(self._prefs)
        except Exception:
            log.warning("Couldn't prepare What's new", exc_info=True)
        # start whisper-server in the background so the first dictation doesn't pay the cost
        threading.Thread(target=self._warmup, daemon=True).start()
        self._hotkey.start()
        super().run()

    def _on_onboarding_done(self):
        """Relaunches the app as a NEW process when the onboarding closes.

        In run() the pynput listener starts BEFORE Accessibility is
        granted: without that permission the CGEventTap isn't created and no
        global events arrive. Granting the permission midway — or even restarting
        the listener in-process (stop+start) — is NOT enough: macOS doesn't
        re-evaluate the Accessibility permission for the event tap within the
        same process. The user confirms it: after reopening the app (new process)
        it dictates; the in-process restart doesn't. The reliable way is to
        relaunch the app: with the permission already persisted in TCC, the new
        process creates a valid event tap and the hotkey just works. Only
        happens on the first launch.
        """
        import subprocess
        from AppKit import NSBundle

        relanzado = False
        try:
            bundle = str(NSBundle.mainBundle().bundlePath())
            # We only relaunch when running as a .app (installed). In dev (python -m)
            # bundlePath() isn't a .app and `open -n` would do something weird.
            if bundle.endswith(".app"):
                subprocess.Popen(["open", "-n", bundle])
                relanzado = True
                # a moment for launchd to register the new process, then exit
                threading.Timer(0.5, self._quit_for_relaunch).start()
        except Exception:
            log.warning("Couldn't relaunch Voooxly after onboarding", exc_info=True)

        if not relanzado:
            # Fallback (dev with no bundle): restart the listener in-process. Not
            # as reliable as relaunching, but at least it tries.
            try:
                self._hotkey.stop()
                self._hotkey.start()
                log.info("Hotkey rearrancado in-process (modo dev).")
            except Exception:
                log.warning("Couldn't restart hotkeys", exc_info=True)

    def _quit_for_relaunch(self):
        # terminate() touches AppKit: goes through the main thread.
        self._on_main(lambda: rumps.quit_application())

    def _warmup(self):
        # 0) speech model: if it's missing, it downloads itself with progress on the icon
        try:
            if not stt.find_model():
                self._alert(
                    "Downloading speech model",
                    "~550MB, one time only — the menu bar icon shows progress.",
                )

                def _dl_progress(pct: int):
                    # runs on the _warmup thread: the title goes through main.
                    self._on_main(lambda p=pct: setattr(self, "title", f"⏬ {p}%"))

                ok_model = stt.ensure_model(progress_cb=_dl_progress)
                self._refresh_title()
                if ok_model:
                    self._hud("Speech model installed.", title="✓ Ready")
                else:
                    self._alert(
                        "Model download failed",
                        "Check your connection and relaunch Voooxly.",
                    )
        except Exception as e:
            log.warning("Model auto-download failed: %s", e)
            self._refresh_title()
        # 1) whisper-server
        try:
            port = int(self.cfg.get("stt.server_port", 8080))
            threads = int(self.cfg.get("stt.threads", 4))
            ok = stt.start_server(threads=threads, port=port)
            if not ok:
                log.warning(
                    "whisper-server didn't start. Verify 'brew install whisper-cpp' "
                    "and the model in ~/.voooxly/models/ (see README)."
                )
        except Exception as e:
            log.warning("STT warmup failed (will try on first use): %s", e)
        # 2) detection of the available LLM engine
        try:
            self._update_ai_item(force=True)
        except Exception:
            pass
        # 3) new-version notice (silent if there's no network or the appcast fails)
        try:
            info = updates.check()
            if info:
                self._update_url = info["url"]
                self._update_version = info["version"]
                # If there's already news at startup, we count it as "notified" so
                # the periodic re-check doesn't repeat the notice 24 h later
                # for the same version: that notice is for versions that
                # show up NEW while the app is open.
                self._notified_update_version = info["version"]
                ver = info["version"]

                def _show_update():
                    self.update_item.title = f"Update to {ver} →"
                    self.update_item._menuitem.setHidden_(False)

                self._on_main(_show_update)
                # Pop-up upon detecting the news (v1.4 feedback): before, the
                # startup only showed the menu item and nobody noticed.
                self._maybe_prompt_update(info)
        except Exception:
            pass
        finally:
            # The periodic re-check must be armed whether the startup
            # check succeeded or failed (no network / appcast down):
            # if it goes to the `except` and `_schedule_update_check()` sits
            # inside the `try`, the 24 h timer would never start and versions
            # that show up while the app is open would go unnoticed until the
            # next restart.
            self._schedule_update_check()
        # 4) seed Recent with the persistent history from previous sessions
        try:
            if self._save_history_on() and not self._history:
                for t in reversed(history.load(HISTORY_SIZE)):
                    self._history.appendleft(t)
                if self._history:
                    self._last_dictation = self._history[0]
                    self._refresh_recent()
        except Exception:
            pass
        # Keepalive: on low-RAM Macs macOS pages out the model (~1.6GB) after
        # inactivity and the next dictation pays 10-19s to get back into memory.
        # A 0.4s silence ping every N min keeps it warm (~0.3s of
        # cost). stt.keepalive_min: 0 disables it.
        try:
            mins = float(self.cfg.get("stt.keepalive_min", 4))
        except (TypeError, ValueError):
            mins = 4.0
        if mins <= 0:
            return
        import numpy as np

        ping = np.zeros(int(0.4 * audio.SR), dtype=np.int16)
        while True:
            time.sleep(mins * 60)
            if self._gate.state != "IDLE":
                continue
            try:
                stt.transcribe(ping, self.stt_model, "es")
                # cheap re-detection: if the user started Ollama after
                # opening Voooxly, the menu finds out on its own
                self._update_ai_item(force=True)
            except Exception:
                pass