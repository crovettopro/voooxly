"""El diff de correcciones: de dos textos, los reemplazos que el usuario quiso.

Precisión sobre exhaustividad: un falso positivo mete un reemplazo malo que
corrompe TODOS los dictados futuros (dictionary.apply es case-insensitive y
global). Mejor perder una corrección que aprender una mentira.
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
    # Coma añadida: no es una grafía que Whisper deba aprender.
    assert corrections("hola que tal", "hola, que tal") == []


def test_ignora_reescrituras_grandes():
    # Si el usuario reescribió la frase entera no hay "palabra corregida"
    # que aprender: un segmento largo NO es un reemplazo de diccionario.
    got = corrections(
        "manda el informe cuando puedas",
        "por favor envíame el documento final hoy mismo",
    )
    assert got == []


def test_ignora_borrados_e_inserciones():
    # Borrar o añadir palabras no enseña grafías.
    assert corrections("hola muy buenas tardes", "hola buenas tardes") == []
    assert corrections("hola buenas", "hola muy buenas") == []


def test_tolera_entradas_vacias():
    assert corrections("", "algo") == []
    assert corrections("algo", "") == []
    assert corrections("", "") == []


# Tests for learn_from (Task 2)
from voooxly import dictionary
from voooxly.learn import learn_from


def test_learn_from_guarda_reemplazos_en_el_diccionario(tmp_path):
    d = tmp_path / "dictionary.json"
    descs = learn_from("uso boxli a diario", "uso Voooxly a diario", path=d)
    assert len(descs) == 1
    data = dictionary.load(d)
    assert data["replacements"]["boxli"] == "Voooxly"
    assert "Voooxly" in data["words"]          # la grafía buena sesga el STT


def test_learn_from_sin_cambios_no_toca_el_fichero(tmp_path):
    d = tmp_path / "dictionary.json"
    assert learn_from("igual", "igual", path=d) == []
    assert not d.exists()


def test_learn_from_nunca_lanza_con_diccionario_roto(tmp_path):
    d = tmp_path / "dictionary.json"
    d.write_text("{json roto", encoding="utf-8")
    # dictionary.load ya tolera basura; learn_from debe heredar el best-effort.
    descs = learn_from("uso boxli", "uso Voooxly", path=d)
    assert descs  # aprendió igualmente (load devuelve dict vacío y add reescribe)
