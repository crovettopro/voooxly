"""Guards for the automatic path: es-aware phonetics + common words.

A style edit ("envía"→"manda") is NOT a mishearing and must never
be learned: the phonetic filter is what separates auto-learn from
auto-corrupting the dictionary.
"""
from voooxly import dictionary
from voooxly.learn import (
    _is_common,
    auto_corrections,
    auto_learn_from,
    locate_pasted,
    normalize_phonetic,
    sounds_alike,
)

PEGADO = "hola equipo, el informe de wisperflow llega mañana por la tarde"


def test_normaliza_grafias_espanolas_equivalentes():
    assert normalize_phonetic("valla") == normalize_phonetic("baya")
    assert normalize_phonetic("hola") == normalize_phonetic("ola")
    assert normalize_phonetic("quiosco") == normalize_phonetic("kiosco")


def test_errores_de_oido_suenan_parecido():
    assert sounds_alike("wisperflow", "Wispr Flow")
    assert sounds_alike("ucademi", "Ucademy")
    assert sounds_alike("boxli", "Voooxly")


def test_ediciones_de_estilo_no_suenan_parecido():
    assert not sounds_alike("envía", "manda")
    assert not sounds_alike("informe", "documento")
    assert not sounds_alike("hola", "buenas")


def test_entradas_vacias_no_suenan_parecido():
    assert not sounds_alike("", "algo")
    assert not sounds_alike("algo", "")
    assert not sounds_alike("!!!", "???")


def test_palabras_comunes_es_y_en():
    assert _is_common("que") and _is_common("the")
    assert not _is_common("Voooxly") and not _is_common("Ucademy")


def test_locates_pasted_text_inside_a_long_document():
    doc = "Notas del lunes.\n\n" + PEGADO + "\n\nOtras cosas sin relación que ya estaban."
    assert locate_pasted(PEGADO, doc) == " ".join(PEGADO.split())


def test_localiza_aunque_este_corregido():
    doc = "Intro previa. " + PEGADO.replace("wisperflow", "Wispr Flow") + " Y un cierre."
    region = locate_pasted(PEGADO, doc)
    assert region is not None and "Wispr Flow" in region


def test_does_not_locate_if_field_is_different():
    assert locate_pasted(PEGADO, "totalmente otra cosa escrita aquí sin relación alguna") is None


def test_no_localiza_si_lo_pegado_fue_borrado_o_reescrito():
    assert locate_pasted(PEGADO, "al final lo reescribí entero con distintas palabras nuevas") is None
    assert locate_pasted(PEGADO, "") is None
    assert locate_pasted("", "algo") is None


def test_auto_aprende_solo_la_grafia_corregida():
    campo = "Contexto. " + PEGADO.replace("wisperflow", "Wispr Flow") + " Despedida."
    assert auto_corrections(PEGADO, campo) == [("wisperflow", "Wispr Flow")]


def test_auto_ignores_style_edits():
    campo = PEGADO.replace("llega", "aterriza")  # synonym: style, not mishearing
    assert auto_corrections(PEGADO, campo) == []


def test_auto_ignora_correcciones_a_palabras_comunes():
    campo = PEGADO.replace("por", "para")  # common and doesn't sound alike: double rejection
    assert auto_corrections(PEGADO, campo) == []


def test_auto_without_changes_learns_nothing():
    assert auto_corrections(PEGADO, "x " + PEGADO + " y") == []


def test_auto_learn_from_persists_to_dictionary(tmp_path):
    dic = tmp_path / "dictionary.json"
    campo = PEGADO.replace("wisperflow", "Wispr Flow")
    out = auto_learn_from(PEGADO, campo, path=dic)
    assert len(out) == 1
    data = dictionary.load(dic)
    assert data["replacements"].get("wisperflow") == "Wispr Flow"


def test_auto_learn_from_with_illegible_field_does_not_touch_dictionary(tmp_path):
    dic = tmp_path / "dictionary.json"
    assert auto_learn_from(PEGADO, "", path=dic) == []
    assert not dic.exists()
