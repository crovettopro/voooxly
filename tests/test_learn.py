"""The corrections diff: from two texts, the replacements the user intended.

Precision over recall: a false positive introduces a bad replacement that
corrupts ALL future dictations (dictionary.apply is case-insensitive and
global). Better to miss a correction than to learn a lie.
"""
from voooxly.learn import corrections


def test_detecta_una_palabra_corregida():
    got = corrections("hola wisperflow que tal", "hola Wispr Flow que tal")
    assert got == [("wisperflow", "Wispr Flow")]


def test_detecta_varias_correcciones_independientes():
    got = corrections("uso ucademi y boxli a diario", "uso Ucademy y Voooxly a diario")
    assert got == [("ucademi", "Ucademy"), ("boxli", "Voooxly")]


def test_ignora_textos_iguales():
    assert corrections("nada que ver", "nada que ver") == []


def test_ignora_cambios_solo_de_puntuacion():
    # Added comma: not a spelling Whisper should learn.
    assert corrections("hola que tal", "hola, que tal") == []


def test_ignora_reescrituras_grandes():
    # If the user rewrote the whole sentence there is no "corrected word"
    # to learn: a long segment is NOT a dictionary replacement.
    got = corrections(
        "manda el informe cuando puedas",
        "por favor envíame el documento final hoy mismo",
    )
    assert got == []


def test_ignora_borrados_e_inserciones():
    # Deleting or adding words teaches no spellings.
    assert corrections("hola muy buenas tardes", "hola buenas tardes") == []
    assert corrections("hola buenas", "hola muy buenas") == []


def test_tolera_entradas_vacias():
    assert corrections("", "algo") == []
    assert corrections("algo", "") == []
    assert corrections("", "") == []


# Tests for learn_from (Task 2)
from voooxly import dictionary
from voooxly.learn import learn_from


def test_learn_from_saves_replacements_to_dictionary(tmp_path):
    d = tmp_path / "dictionary.json"
    descs = learn_from("uso boxli a diario", "uso Voooxly a diario", path=d)
    assert len(descs) == 1
    data = dictionary.load(d)
    assert data["replacements"]["boxli"] == "Voooxly"
    assert "Voooxly" in data["words"]          # the good spelling biases the STT


def test_learn_from_without_changes_does_not_touch_file(tmp_path):
    d = tmp_path / "dictionary.json"
    assert learn_from("igual", "igual", path=d) == []
    assert not d.exists()


def test_learn_from_nunca_lanza_con_diccionario_roto(tmp_path):
    d = tmp_path / "dictionary.json"
    d.write_text("{json roto", encoding="utf-8")
    # dictionary.load already tolerates garbage; learn_from must inherit the best-effort.
    descs = learn_from("uso boxli", "uso Voooxly", path=d)
    assert descs  # learned anyway (load returns an empty dict and add rewrites)
