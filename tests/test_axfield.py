"""axfield must be importable and callable in any environment (CI included):
without a graphical session it returns None, it never raises.

The character cap is the one piece of real logic here, and it is not cosmetic:
the cut lands anywhere, including INSIDE the last word of what we just pasted.
A halved word reads as a 1→1 substitution to learn.corrections() — verified,
`mañana` cut short yields the pair ("mañana", "maña") — and a replacement is
global, whole-word and permanent. Cutting on a word boundary turns that into a
deletion, which the learner ignores by design.
"""
from voooxly import axfield


def test_importable_y_contrato():
    out = axfield.read_focused_text()
    assert out is None or isinstance(out, str)


def test_clip_leaves_a_field_under_the_cap_untouched():
    texto = "hola equipo, el informe llega mañana por la tarde"
    assert axfield.clip(texto) == texto


def test_clip_drops_the_half_word_left_by_the_cut():
    texto = "z " * (axfield._MAX_FIELD_CHARS // 2) + "mañana por la tarde"
    recortado = axfield.clip(texto)

    assert len(recortado) <= axfield._MAX_FIELD_CHARS
    assert not recortado.endswith("maña")
    assert recortado.split()[-1] == "z"


def test_clip_keeps_the_last_word_when_the_cut_falls_on_a_space():
    texto = "z" * (axfield._MAX_FIELD_CHARS - 5) + " hola mundo"
    recortado = axfield.clip(texto)

    assert recortado.split()[-1] == "hola"


def test_clip_of_one_endless_word_yields_nothing_rather_than_a_stump():
    assert axfield.clip("z" * (axfield._MAX_FIELD_CHARS + 100)) == ""


# --- Staying in the app that received the paste ---------------------------
# read_focused_text() follows FOCUS, not the element we pasted into, and the
# post-paste window reads several times. Matching is by text, so a field in
# another app holding nearly the same words is indistinguishable from ours.
# Refusing to read at all once the user has left the app closes that door for
# the common case (⌘Tab, clicking another window) at the cost of one pid call.


def _reader(textos, pids):
    return axfield.app_locked_reader(read=lambda: textos.pop(0), pid=lambda: pids.pop(0))


def test_the_locked_reader_keeps_reading_inside_the_same_app():
    read = _reader(["uno", "dos"], [501, 501])

    assert read() == "uno"
    assert read() == "dos"


def test_the_locked_reader_goes_blind_once_focus_leaves_the_app():
    read = _reader(["uno", "no debería leerse"], [501, 777])

    assert read() == "uno"
    assert read() is None


def test_the_locked_reader_locks_on_before_the_paste_has_landed():
    """The first read usually comes back empty — the ⌘V is still in flight —
    but the app is already the right one, so that is what we lock onto."""
    read = _reader([None, "ya está pegado"], [501, 501])

    assert read() is None
    assert read() == "ya está pegado"


def test_the_locked_reader_without_accessibility_just_reads():
    read = _reader(["uno", "dos"], [None, None])

    assert read() == "uno"
    assert read() == "dos"
