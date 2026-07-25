"""Guardas de la vía automática: fonética es-aware + palabras comunes.

Una edición de estilo ("envía"→"manda") NO es un error de oído y no debe
aprenderse jamás: el filtro fonético es lo que separa auto-learn de
auto-corromper el diccionario.
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


def test_localiza_lo_pegado_dentro_de_un_documento_largo():
    doc = "Notas del lunes.\n\n" + PEGADO + "\n\nOtras cosas sin relación que ya estaban."
    assert locate_pasted(PEGADO, doc) == " ".join(PEGADO.split())


def test_localiza_aunque_este_corregido():
    doc = "Intro previa. " + PEGADO.replace("wisperflow", "Wispr Flow") + " Y un cierre."
    region = locate_pasted(PEGADO, doc)
    assert region is not None and "Wispr Flow" in region


def test_no_localiza_si_el_campo_es_otro():
    assert locate_pasted(PEGADO, "totalmente otra cosa escrita aquí sin relación alguna") is None


def test_no_localiza_si_lo_pegado_fue_borrado_o_reescrito():
    assert locate_pasted(PEGADO, "al final lo reescribí entero con distintas palabras nuevas") is None
    assert locate_pasted(PEGADO, "") is None
    assert locate_pasted("", "algo") is None


def test_auto_aprende_solo_la_grafia_corregida():
    campo = "Contexto. " + PEGADO.replace("wisperflow", "Wispr Flow") + " Despedida."
    assert auto_corrections(PEGADO, campo) == [("wisperflow", "Wispr Flow")]


def test_auto_ignora_ediciones_de_estilo():
    campo = PEGADO.replace("llega", "aterriza")  # sinónimo: estilo, no oído
    assert auto_corrections(PEGADO, campo) == []


def test_auto_ignora_correcciones_a_palabras_comunes():
    campo = PEGADO.replace("por", "para")  # común y no suena igual: doble rechazo
    assert auto_corrections(PEGADO, campo) == []


def test_auto_sin_cambios_no_aprende_nada():
    assert auto_corrections(PEGADO, "x " + PEGADO + " y") == []


def test_auto_learn_from_persiste_en_el_diccionario(tmp_path):
    dic = tmp_path / "dictionary.json"
    campo = PEGADO.replace("wisperflow", "Wispr Flow")
    out = auto_learn_from(PEGADO, campo, path=dic)
    assert len(out) == 1
    data = dictionary.load(dic)
    assert data["replacements"].get("wisperflow") == "Wispr Flow"


def test_auto_learn_from_con_campo_ilegible_no_toca_el_diccionario(tmp_path):
    dic = tmp_path / "dictionary.json"
    assert auto_learn_from(PEGADO, "", path=dic) == []
    assert not dic.exists()
