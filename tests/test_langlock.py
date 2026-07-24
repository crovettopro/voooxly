"""Auto-lock de idioma: fijar language= ahorra ~1,1s/dictado (medido).

Sesgo a precisión: en la duda, None — un lock equivocado transcribe mal
TODOS los dictados siguientes; uno no puesto solo cuesta 1,1s.
"""
from voooxly.langlock import LOCK_AFTER, detect_lang_es_en, update_lock


def test_detecta_espanol_claro():
    assert detect_lang_es_en("envía el informe a María cuando puedas por favor") == "es"


def test_detecta_ingles_claro():
    assert detect_lang_es_en("please send the report to the team when you can") == "en"


def test_texto_ambiguo_o_corto_devuelve_none():
    assert detect_lang_es_en("ok") is None
    assert detect_lang_es_en("") is None
    assert detect_lang_es_en(None) is None
    assert detect_lang_es_en("Wispr Flow GPT-5 API") is None


def test_lock_tras_tres_consecutivos():
    streak, lock = update_lock([], "es")
    assert (streak, lock) == (["es"], None)
    streak, lock = update_lock(streak, "es")
    assert (streak, lock) == (["es", "es"], None)
    streak, lock = update_lock(streak, "es")
    assert lock == "es" and len(streak) == LOCK_AFTER


def test_cambio_de_idioma_rompe_la_racha():
    streak, _ = update_lock(["es", "es"], "en")
    assert streak == ["en"]


def test_deteccion_ambigua_no_rompe_ni_alarga():
    streak, lock = update_lock(["es", "es"], None)
    assert (streak, lock) == (["es", "es"], None)


def test_racha_no_crece_sin_limite():
    streak = []
    for _ in range(10):
        streak, lock = update_lock(streak, "en")
    assert len(streak) == LOCK_AFTER and lock == "en"
