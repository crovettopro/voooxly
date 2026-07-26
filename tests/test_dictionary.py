"""Personal dictionary: the words bias the STT, the replacements correct the
final text. A replacement must be surgical — whole word, without eating
substrings ("marta" does not touch "Smartphone") — and a broken file never gets in the way.
"""
import json
import threading
import time

import pytest

from voooxly import dictionary


def test_add_palabra_y_stt_terms(tmp_path):
    p = tmp_path / "dict.json"
    assert dictionary.add("Ucademy", p) == "Word: “Ucademy”"
    dictionary.add("Ucademy", p)  # repeated: does not duplicate
    assert dictionary.stt_terms(p) == ["Ucademy"]


def test_add_reemplazo_crea_replacement_y_sesga_con_la_grafia_buena(tmp_path):
    p = tmp_path / "dict.json"
    desc = dictionary.add("wisperflow -> Wispr Flow", p)
    assert "wisperflow" in desc and "Wispr Flow" in desc
    data = dictionary.load(p)
    assert data["replacements"] == {"wisperflow": "Wispr Flow"}
    assert "Wispr Flow" in dictionary.stt_terms(p)


def test_add_incomplete_replacement_raises(tmp_path):
    p = tmp_path / "dict.json"
    with pytest.raises(ValueError):
        dictionary.add("solo-mal ->", p)
    with pytest.raises(ValueError):
        dictionary.add("   ", p)


def test_apply_replaces_full_word_case_insensitively(tmp_path):
    p = tmp_path / "dict.json"
    dictionary.add("boxli -> Voooxly", p)
    assert dictionary.apply("Boxli es genial, uso boxli a diario", p) == (
        "Voooxly es genial, uso Voooxly a diario"
    )


def test_apply_no_toca_subcadenas(tmp_path):
    p = tmp_path / "dict.json"
    dictionary.add("marta -> Marta", p)
    assert dictionary.apply("el smartphone de marta", p) == "el smartphone de Marta"


def test_apply_sin_fichero_devuelve_el_texto_tal_cual(tmp_path):
    assert dictionary.apply("hola", tmp_path / "no-existe.json") == "hola"


# --- Concurrency: auto-learn writes from daemon threads -------------------
# add() is a read-modify-write of the WHOLE file, and the post-paste watch can
# fire it from several threads at once (one per pending dictation) while
# apply()/stt_terms() read it on the dictation path. Without a lock the last
# writer wins and the other's entries are lost; without an atomic replace a
# reader — or a quit mid-write — sees a truncated file, which load() swallows
# as an EMPTY dictionary. Both silently, which is the worst kind.


def test_two_adds_at_once_do_not_lose_each_other(tmp_path, monkeypatch):
    p = tmp_path / "dict.json"
    real_load = dictionary.load
    reading = threading.Event()

    def slow_load(path=None):
        data = real_load(path)
        reading.set()
        time.sleep(0.2)  # widens the read→write window to make the race certain
        return data

    monkeypatch.setattr(dictionary, "load", slow_load)
    hilo = threading.Thread(
        target=dictionary.add, args=("uno -> Uno", p), daemon=True
    )
    hilo.start()
    assert reading.wait(2), "el hilo no llegó a leer el diccionario"
    dictionary.add("dos -> Dos", p)
    hilo.join(5)

    assert real_load(p)["replacements"] == {"uno": "Uno", "dos": "Dos"}


def test_add_replaces_the_file_instead_of_truncating_it_in_place(tmp_path):
    p = tmp_path / "dict.json"
    dictionary.add("boxli -> Voooxly", p)
    antes = p.stat().st_ino

    dictionary.add("wisperflow -> Wispr Flow", p)

    assert p.stat().st_ino != antes, (
        "se escribió in-place: un lector concurrente (o un quit) puede ver el "
        "fichero a medias, y load() lo trataría como diccionario vacío"
    )


def test_add_leaves_no_temporary_files_behind(tmp_path):
    p = tmp_path / "dict.json"
    dictionary.add("boxli -> Voooxly", p)
    dictionary.add("Ucademy", p)

    assert sorted(f.name for f in tmp_path.iterdir()) == ["dict.json"]


def test_corrupt_file_does_not_break(tmp_path):
    p = tmp_path / "dict.json"
    p.write_text("{esto no es json", encoding="utf-8")
    assert dictionary.load(p) == {"words": [], "replacements": {}}
    assert dictionary.apply("hola", p) == "hola"
    # and add() repairs it by writing a new valid one
    dictionary.add("Voooxly", p)
    assert dictionary.stt_terms(p) == ["Voooxly"]


# --- remove ----------------------------------------------------------------
# Until now nothing could take an entry out. A replacement is global and
# permanent, so a wrong one (auto-learned or mistyped) rewrote every later
# dictation with no way back short of editing the JSON by hand.

def _dic(tmp_path, data):
    p = tmp_path / "dictionary.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_remove_takes_out_the_replacement_and_its_bias_word(tmp_path):
    # add() writes the right spelling into words too, so remove() has to clean
    # both: leaving "Explora" behind keeps biasing Whisper towards producing it.
    p = _dic(tmp_path, {"words": ["Explora", "Ucademy"], "replacements": {"Explore": "Explora"}})
    dictionary.remove("Explore", p)
    data = dictionary.load(p)
    assert data["replacements"] == {}
    assert data["words"] == ["Ucademy"]


def test_remove_keeps_the_bias_word_if_another_replacement_still_needs_it(tmp_path):
    p = _dic(tmp_path, {
        "words": ["Vixiees"],
        "replacements": {"Vixi": "Vixiees", "Vixis": "Vixiees"},
    })
    dictionary.remove("Vixi", p)
    data = dictionary.load(p)
    assert data["replacements"] == {"Vixis": "Vixiees"}
    assert data["words"] == ["Vixiees"]


def test_remove_takes_out_a_plain_bias_word(tmp_path):
    p = _dic(tmp_path, {"words": ["hubspot", "presu"], "replacements": {}})
    dictionary.remove("hubspot", p)
    assert dictionary.load(p)["words"] == ["presu"]


def test_remove_ignores_capitalisation(tmp_path):
    # The user reads "Explore" off the list and types "explore".
    p = _dic(tmp_path, {"words": ["Explora"], "replacements": {"Explore": "Explora"}})
    dictionary.remove("explore", p)
    assert dictionary.load(p)["replacements"] == {}


def test_remove_accepts_the_whole_line_as_shown(tmp_path):
    # Symmetric with add(): pasting back "Explore -> Explora" has to work.
    p = _dic(tmp_path, {"words": ["Explora"], "replacements": {"Explore": "Explora"}})
    dictionary.remove("Explore -> Explora", p)
    assert dictionary.load(p)["replacements"] == {}


def test_remove_of_something_absent_says_so_and_changes_nothing(tmp_path):
    p = _dic(tmp_path, {"words": ["Ucademy"], "replacements": {"Explore": "Explora"}})
    with pytest.raises(ValueError):
        dictionary.remove("nothing-like-this", p)
    data = dictionary.load(p)
    assert data["replacements"] == {"Explore": "Explora"} and data["words"] == ["Ucademy"]


def test_remove_on_a_missing_file_does_not_create_one(tmp_path):
    p = tmp_path / "dictionary.json"
    with pytest.raises(ValueError):
        dictionary.remove("whatever", p)
    assert not p.exists()


def test_entries_lists_what_is_in_there_for_the_menu(tmp_path):
    # The remove window shows this: seeing the bad entry is how you find out
    # the dictionary is why your dictation keeps coming out wrong.
    p = _dic(tmp_path, {"words": ["Ucademy"], "replacements": {"Explore": "Explora"}})
    listado = dictionary.entries(p)
    assert "Explore → Explora" in listado
    assert "Ucademy" in listado
