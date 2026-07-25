"""The auto-learn glue, at module level so it can be tested without building
VoooxlyApp's AppKit menus (same reason as _record_token_usage, see
test_record_token_usage.py).

Two things live here that the pure watch loop cannot own:

- **Whose pending dictation is it.** The window runs for seconds while the
  user may already be dictating again. A watch that finishes late must never
  clear the pending text of a NEWER paste, or the next-dictation fallback for
  that one disappears.
- **When the notice is painted.** _learned_note used to be drained only at the
  tail of _process, ~2s after the paste. A window finishing at t≈6s therefore
  showed "✨ Learned" at the end of the NEXT dictation — or never. Worse, the
  one-time "turn it off" line was consumed by a notice nobody saw.
"""
import threading

from voooxly import app as app_mod
from voooxly import config, dictionary
from voooxly.app import LearnState, _drain_learned_note, _watch_and_learn

PEGADO = "hola equipo, el informe de wisperflow llega mañana por la tarde"
FIX = PEGADO.replace("wisperflow", "Wispr Flow")


class _Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, secs):
        self.t += secs


def _lecturas(*snapshots):
    restantes = list(snapshots)
    return lambda: restantes.pop(0) if len(restantes) > 1 else restantes[0]


# --- whose pending dictation is it ---------------------------------------


def test_a_new_paste_supersedes_the_running_watch():
    state = LearnState()
    _, primero = state.start("uno")
    state.start("dos")

    assert primero.is_set()


def test_a_late_watch_does_not_clear_a_newer_pending_dictation():
    state = LearnState()
    viejo, _ = state.start(PEGADO)
    state.start("otro dictado más reciente")

    state.done(viejo, "wisperflow -> Wispr Flow")

    assert state.take_pending() == "otro dictado más reciente"


def test_a_watch_that_learned_clears_its_own_pending_dictation():
    state = LearnState()
    gen, _ = state.start(PEGADO)

    state.done(gen, "wisperflow -> Wispr Flow")

    assert state.take_pending() is None


def test_a_watch_that_learned_nothing_leaves_the_fallback_armed():
    state = LearnState()
    gen, _ = state.start(PEGADO)

    state.done(gen, None)

    assert state.take_pending() == PEGADO


def test_two_watches_finishing_together_do_not_lose_a_notice():
    state = LearnState()
    gen, _ = state.start(PEGADO)

    state.done(gen, "uno -> Uno")
    state.done(gen, "dos -> Dos")

    assert state.take_note() == "uno -> Uno\ndos -> Dos"
    assert state.take_note() is None


# --- when the notice is painted ------------------------------------------


def _prefs_guardadas(monkeypatch):
    guardadas = []
    monkeypatch.setattr(app_mod, "_save_prefs", lambda p: guardadas.append(dict(p)))
    return guardadas


def test_the_notice_is_painted_right_away_when_the_hud_is_free(monkeypatch):
    _prefs_guardadas(monkeypatch)
    state = LearnState()
    state.park_note("wisperflow -> Wispr Flow")
    pintadas = []

    mostrada = _drain_learned_note(
        state, idle=True, prefs={"auto_learn_seen": True}, show=pintadas.append
    )

    assert mostrada is True
    assert pintadas == ["wisperflow -> Wispr Flow"]
    assert state.take_note() is None


def test_the_notice_waits_instead_of_being_thrown_away_mid_dictation(monkeypatch):
    _prefs_guardadas(monkeypatch)
    state = LearnState()
    state.park_note("wisperflow -> Wispr Flow")
    pintadas = []

    mostrada = _drain_learned_note(
        state, idle=False, prefs={"auto_learn_seen": True}, show=pintadas.append
    )

    assert mostrada is False
    assert pintadas == []
    assert state.take_note() == "wisperflow -> Wispr Flow"


def test_the_first_notice_says_how_to_turn_it_off(monkeypatch):
    guardadas = _prefs_guardadas(monkeypatch)
    state = LearnState()
    state.park_note("wisperflow -> Wispr Flow")
    prefs = {}
    pintadas = []

    _drain_learned_note(state, idle=True, prefs=prefs, show=pintadas.append)

    assert "\n" in pintadas[0] and len(pintadas[0].splitlines()) == 2
    assert prefs["auto_learn_seen"] is True
    assert guardadas  # persisted, or it would explain itself on every launch


def test_the_turn_it_off_line_is_not_burned_by_a_notice_nobody_saw(monkeypatch):
    _prefs_guardadas(monkeypatch)
    state = LearnState()
    state.park_note("wisperflow -> Wispr Flow")
    prefs = {}
    pintadas = []

    _drain_learned_note(state, idle=False, prefs=prefs, show=pintadas.append)
    assert prefs.get("auto_learn_seen") is not True

    _drain_learned_note(state, idle=True, prefs=prefs, show=pintadas.append)
    assert len(pintadas[0].splitlines()) == 2


def test_the_explanation_is_not_repeated_on_the_second_notice(monkeypatch):
    _prefs_guardadas(monkeypatch)
    state = LearnState()
    prefs = {}
    pintadas = []

    state.park_note("uno -> Uno")
    _drain_learned_note(state, idle=True, prefs=prefs, show=pintadas.append)
    state.park_note("dos -> Dos")
    _drain_learned_note(state, idle=True, prefs=prefs, show=pintadas.append)

    assert pintadas[1] == "dos -> Dos"


def test_a_hud_that_blows_up_does_not_kill_the_watch_thread(monkeypatch):
    """This runs on a daemon thread, and _hud spawns one of its own — which
    can raise. The pairs are already in the dictionary by then: an unpaintable
    notice is worth a debug line, never a traceback."""
    _prefs_guardadas(monkeypatch)
    state = LearnState()
    state.park_note("wisperflow -> Wispr Flow")

    def explota(_):
        raise RuntimeError("no se pudo lanzar el hilo del HUD")

    assert _drain_learned_note(state, idle=True, prefs={}, show=explota) is False


def test_nothing_to_paint_is_not_an_error(monkeypatch):
    _prefs_guardadas(monkeypatch)

    assert _drain_learned_note(LearnState(), idle=True, prefs={}, show=print) is False


# --- the watch thread's body ---------------------------------------------


def test_a_correction_made_and_settled_lands_in_the_dictionary(tmp_path, monkeypatch):
    monkeypatch.setattr(dictionary, "DICT_FILE", tmp_path / "dict.json")
    state = LearnState()
    gen, stop = state.start(PEGADO)
    reloj = _Reloj()

    aprendido = _watch_and_learn(
        config.Config({}),
        state,
        PEGADO,
        gen,
        stop,
        read=_lecturas(PEGADO, FIX),
        clock=reloj,
        sleep=reloj.sleep,
    )

    assert aprendido == ["Replacement: “wisperflow” → “Wispr Flow”"]
    assert dictionary.load(tmp_path / "dict.json")["replacements"] == {
        "wisperflow": "Wispr Flow"
    }
    assert state.take_pending() is None
    assert state.take_note() == "Replacement: “wisperflow” → “Wispr Flow”"


def test_a_field_left_untouched_teaches_nothing_and_keeps_the_fallback(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(dictionary, "DICT_FILE", tmp_path / "dict.json")
    state = LearnState()
    gen, stop = state.start(PEGADO)
    reloj = _Reloj()

    aprendido = _watch_and_learn(
        config.Config({}),
        state,
        PEGADO,
        gen,
        stop,
        read=_lecturas(PEGADO),
        clock=reloj,
        sleep=reloj.sleep,
    )

    assert aprendido == []
    assert not (tmp_path / "dict.json").exists()
    assert state.take_pending() == PEGADO


def test_the_config_values_reach_the_watch(monkeypatch):
    recibido = {}

    def falso(pasted, read, **kw):
        recibido.update(kw)
        return None

    monkeypatch.setattr(app_mod.learn, "watch_field", falso)
    cfg = config.Config(
        {"learn": {"window_seconds": 9, "poll_interval": 1, "stable_seconds": 2,
                   "acquire_seconds": 3}}
    )
    state = LearnState()
    gen, stop = state.start(PEGADO)

    _watch_and_learn(cfg, state, PEGADO, gen, stop, read=lambda: None)

    assert recibido["window_s"] == 9
    assert recibido["poll_s"] == 1
    assert recibido["stable_s"] == 2
    assert recibido["acquire_s"] == 3


def test_a_config_without_the_learn_block_still_watches(monkeypatch):
    """A user's ~/.voooxly/config.yaml shadows the bundled one wholesale (no
    merge), so every key needs its default at the call site."""
    recibido = {}

    def falso(pasted, read, **kw):
        recibido.update(kw)
        return None

    monkeypatch.setattr(app_mod.learn, "watch_field", falso)
    state = LearnState()
    gen, stop = state.start(PEGADO)

    _watch_and_learn(config.Config({}), state, PEGADO, gen, stop, read=lambda: None)

    assert recibido["window_s"] and recibido["poll_s"] and recibido["stable_s"]


def test_a_watch_that_blows_up_does_not_escape_the_daemon_thread(monkeypatch):
    def explota(*a, **k):
        raise RuntimeError("AX se cayó del todo")

    monkeypatch.setattr(app_mod.learn, "watch_field", explota)
    state = LearnState()
    gen, stop = state.start(PEGADO)

    assert _watch_and_learn(config.Config({}), state, PEGADO, gen, stop) == []
    assert state.take_pending() == PEGADO  # el fallback sigue armado


def test_the_shipped_config_declares_the_learn_block():
    cfg = config.load_config(config.DEFAULT_CONFIG)

    assert cfg.get("learn.poll_interval") > 0
    assert 10 <= cfg.get("learn.window_seconds") <= 20
    assert 0 < cfg.get("learn.stable_seconds") <= cfg.get("learn.window_seconds")


def test_the_state_survives_being_hammered_from_many_threads():
    state = LearnState()
    gen, _ = state.start(PEGADO)
    hilos = [
        threading.Thread(target=state.done, args=(gen, f"par {i}")) for i in range(20)
    ]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(5)

    assert len((state.take_note() or "").splitlines()) == 20
