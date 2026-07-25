"""The post-paste window: it may only learn from a state the user SETTLED on.

Polling is what makes this delicate. The single read of v1.8.0 happened when
the user started their next dictation — a moment they were demonstrably not
typing. A window that samples every couple of seconds sees INTERMEDIATE
states, and a half-typed correction is a perfect phonetic match: measured
against the real auto_corrections(), "wisperflow" → "Wispr Flo" passes every
precision filter and would be written as a global, case-insensitive
replacement. It is unrecoverable — dictionary.apply() rewrites the dictation
before it is pasted, so that misspelling never reaches a field again and the
entry can never be re-learned.

Hence the rule these tests pin: a snapshot is only learnable once it has been
read IDENTICAL twice in a row. The exits that fire when the user walks away
return that confirmed state, never the last raw read.
"""
import threading
import time

import pytest

from voooxly.learn import auto_corrections, auto_learn_from, watch_field

PEGADO = "hola equipo, el informe de wisperflow llega mañana por la tarde"
FIX = PEGADO.replace("wisperflow", "Wispr Flow")
MEDIAS = PEGADO.replace("wisperflow", "Wispr Flo")  # mid-keystroke
PREVIO = "Notas del lunes.\n\n"


class Reloj:
    """Fake clock advanced BY the fake sleep.

    A scripted list of timestamps desyncs: watch_field calls clock() several
    times per iteration and any refactor shifts the list. Tying time to sleep
    means the two fakes can never disagree, and no test waits a real second.
    """

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, secs: float) -> None:
        self.t += secs


def lecturas(*snapshots):
    """read() over a script; once exhausted it keeps returning the last value
    (a field does not change when the user stops typing). Counts calls so the
    tests can pin the AX polling budget."""
    restantes = list(snapshots)
    lecturas.calls = 0

    def read():
        read.calls += 1
        return restantes.pop(0) if len(restantes) > 1 else restantes[0]

    read.calls = 0
    return read


def _watch(read, **kw):
    reloj = Reloj()
    kw.setdefault("clock", reloj)
    kw.setdefault("sleep", reloj.sleep)
    return watch_field(PEGADO, read, **kw), reloj


# --- the happy path -------------------------------------------------------


def test_learns_the_state_the_user_settled_on():
    read = lecturas(PEGADO, FIX)
    out, reloj = _watch(read)

    assert out == FIX
    assert read.calls == 4  # settle costs stable_s rounded up to a poll, plus one
    assert reloj.t == 6.0


def test_learns_a_paste_sitting_inside_a_longer_document():
    read = lecturas(PREVIO + PEGADO, PREVIO + FIX)
    out, _ = _watch(read)

    assert out == PREVIO + FIX  # the raw field: the caller locates the region again


def test_typing_elsewhere_in_the_document_does_not_hold_the_window_open():
    """The debounce watches the pasted region, not the whole document: writing
    the next paragraph must not keep resetting it until the window burns out."""
    read = lecturas(
        PREVIO + FIX, PREVIO + FIX + " sigo", PREVIO + FIX + " sigo escribiendo"
    )
    out, reloj = _watch(read)

    assert out is not None and "Wispr Flow" in out
    assert reloj.t < 15.0


def test_a_field_with_no_corrections_settles_and_teaches_nothing():
    read = lecturas(PEGADO)
    out, _ = _watch(read)

    assert out == PEGADO
    assert auto_corrections(PEGADO, out) == []


# --- the precision rule: never learn from a state seen only once ----------


def test_does_not_learn_a_half_typed_correction_when_the_field_vanishes():
    read = lecturas(PEGADO, MEDIAS, None)
    out, _ = _watch(read)

    assert out is None, f"iba a aprender de un estado a medio teclear: {out!r}"
    assert auto_learn_from(PEGADO, out or "") == []


def test_learns_a_settled_correction_even_though_the_field_then_vanishes():
    read = lecturas(PEGADO, FIX, FIX, None)
    out, _ = _watch(read)

    assert out == FIX  # the whole point of the window


def test_does_not_learn_a_half_typed_correction_when_the_window_expires():
    """A keystroke on every poll: nothing is ever confirmed quiet.

    The letters are typed without the space on purpose: the region is compared
    word by word, so "Wispr" and "Wispr " are the same state and would count
    as settled — correctly, but it would not be testing what this test claims.
    """
    tecleando = [PEGADO] + [
        PEGADO.replace("wisperflow", "WisprFlow"[:i]) for i in range(1, 10)
    ]
    read = lecturas(*tecleando)
    out, reloj = _watch(read)

    assert out is None
    assert read.calls == 8  # window_s / poll_s, the budget claimed in the study
    assert reloj.t <= 16.0


def test_ignores_another_field_that_merely_looks_like_the_paste():
    otro = "cosas de otro sitio que no se parecen en nada a lo pegado aquí"
    read = lecturas(PEGADO, FIX, FIX, otro)
    out, _ = _watch(read)

    assert out == FIX


# --- the ⌘V is still in flight -------------------------------------------


def test_waits_for_the_paste_to_land_before_giving_up():
    """output.deliver posts the keystroke and returns; the app inserts the text
    asynchronously. Reading once at t=0 and quitting would kill the feature."""
    read = lecturas(None, PEGADO, FIX)
    out, _ = _watch(read)

    assert out == FIX


def test_waits_for_the_paste_to_land_in_a_field_that_already_had_text():
    read = lecturas(PREVIO, PREVIO + PEGADO, PREVIO + FIX)
    out, _ = _watch(read)

    assert out == PREVIO + FIX


def test_an_unreadable_field_gives_up_fast_and_teaches_nothing():
    """Terminals: the scrollback never exposes AXValue. Must not poll for 15s."""
    read = lecturas(None)
    out, reloj = _watch(read)

    assert out is None
    assert read.calls <= 3
    assert reloj.t <= 4.0


def test_survives_a_single_blink_of_focus():
    read = lecturas(PEGADO, None, FIX, FIX)
    out, _ = _watch(read)

    assert out == FIX


# --- a newer paste supersedes this window ---------------------------------


def test_a_watch_that_is_already_superseded_never_reads_the_field():
    parar = threading.Event()
    parar.set()
    read = lecturas(PEGADO, FIX)
    out, _ = _watch(read, stop=parar)

    assert out is None
    assert read.calls == 0


def test_being_superseded_midway_keeps_what_was_already_confirmed():
    parar = threading.Event()
    guion = [PEGADO, FIX, FIX]

    def read():
        if guion:
            return guion.pop(0)
        parar.set()  # another dictation just pasted: this window is stale
        return MEDIAS  # and the user is mid-keystroke again

    out, _ = _watch(read, stop=parar)

    assert out == FIX


# --- never spin, never raise, never wait for real -------------------------


def test_a_zero_poll_interval_from_config_does_not_spin():
    read = lecturas(PEGADO, FIX)
    out, reloj = _watch(read, poll_s=0)

    assert out == FIX
    assert read.calls < 40
    assert reloj.t <= 16.0


def test_a_zero_window_from_config_never_reads_the_field():
    read = lecturas(PEGADO, FIX)
    out, _ = _watch(read, window_s=0)

    assert out is None
    assert read.calls == 0


def test_a_read_that_blows_up_does_not_escape_the_thread():
    def read():
        raise RuntimeError("AX se cayó")

    out, _ = _watch(read)

    assert out is None


def test_a_read_that_blows_up_midway_keeps_what_was_already_confirmed():
    fallos = [PEGADO, FIX, FIX]

    def read():
        if fallos:
            return fallos.pop(0)
        raise RuntimeError("AX se cayó")

    out, _ = _watch(read)

    assert out == FIX


def test_the_real_defaults_never_sleep_for_real_in_the_tests():
    t0 = time.monotonic()
    _watch(lecturas(PEGADO, FIX))

    assert time.monotonic() - t0 < 1.0, "sleep no está inyectado: la suite esperaría 15s"


def test_a_none_result_is_safe_for_the_caller(tmp_path):
    dic = tmp_path / "dict.json"

    assert auto_learn_from(PEGADO, None, path=dic) == []
    assert not dic.exists()


@pytest.mark.parametrize("kw", [{"window_s": "15"}, {"poll_s": "2"}, {"stable_s": "3"}])
def test_a_quoted_yaml_value_does_not_crash_the_thread(kw):
    out, _ = _watch(lecturas(PEGADO, FIX), **kw)

    assert out == FIX
