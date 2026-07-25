"""Guardas de la vía automática: fonética es-aware + palabras comunes.

Una edición de estilo ("envía"→"manda") NO es un error de oído y no debe
aprenderse jamás: el filtro fonético es lo que separa auto-learn de
auto-corromper el diccionario.
"""
from voooxly.learn import _is_common, normalize_phonetic, sounds_alike


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
