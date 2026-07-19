"""Diccionario personal: las palabras sesgan el STT, los reemplazos corrigen el
texto final. Un reemplazo debe ser quirúrgico — palabra completa, sin comerse
subcadenas ("marta" no toca "Smartphone") — y un fichero roto no estorba nunca.
"""
import pytest

from voooxly import dictionary


def test_add_palabra_y_stt_terms(tmp_path):
    p = tmp_path / "dict.json"
    assert dictionary.add("Ucademy", p) == "Word: “Ucademy”"
    dictionary.add("Ucademy", p)  # repetida: no duplica
    assert dictionary.stt_terms(p) == ["Ucademy"]


def test_add_reemplazo_crea_replacement_y_sesga_con_la_grafia_buena(tmp_path):
    p = tmp_path / "dict.json"
    desc = dictionary.add("wisperflow -> Wispr Flow", p)
    assert "wisperflow" in desc and "Wispr Flow" in desc
    data = dictionary.load(p)
    assert data["replacements"] == {"wisperflow": "Wispr Flow"}
    assert "Wispr Flow" in dictionary.stt_terms(p)


def test_add_reemplazo_incompleto_lanza(tmp_path):
    p = tmp_path / "dict.json"
    with pytest.raises(ValueError):
        dictionary.add("solo-mal ->", p)
    with pytest.raises(ValueError):
        dictionary.add("   ", p)


def test_apply_reemplaza_palabra_completa_sin_distinguir_mayusculas(tmp_path):
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


def test_fichero_corrupto_no_estorba(tmp_path):
    p = tmp_path / "dict.json"
    p.write_text("{esto no es json", encoding="utf-8")
    assert dictionary.load(p) == {"words": [], "replacements": {}}
    assert dictionary.apply("hola", p) == "hola"
    # y add() lo repara escribiendo uno nuevo válido
    dictionary.add("Voooxly", p)
    assert dictionary.stt_terms(p) == ["Voooxly"]
