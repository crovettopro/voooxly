"""Personal dictionary: the words bias the STT, the replacements correct the
final text. A replacement must be surgical — whole word, without eating
substrings ("marta" does not touch "Smartphone") — and a broken file never gets in the way.
"""
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


def test_corrupt_file_does_not_break(tmp_path):
    p = tmp_path / "dict.json"
    p.write_text("{esto no es json", encoding="utf-8")
    assert dictionary.load(p) == {"words": [], "replacements": {}}
    assert dictionary.apply("hola", p) == "hola"
    # and add() repairs it by writing a new valid one
    dictionary.add("Voooxly", p)
    assert dictionary.stt_terms(p) == ["Voooxly"]
