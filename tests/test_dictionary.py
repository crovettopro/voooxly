"""Personal dictionary: the words bias the STT, the replacements correct the
final text. A replacement must be surgical — whole word, without eating
substrings ("marta" does not touch "Smartphone") — and a broken file never gets in the way.
"""
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
