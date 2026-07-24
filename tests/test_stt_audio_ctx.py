"""audio_ctx proporcional al audio: la mejora del 51% medida en el experimento.

Regla de oro: dictados largos NO llevan audio_ctx (reproducimos alucinación
en bucle con contexto corto sobre audio de 19s). Margen 1.5x (75 frames/s
sobre los 50/s reales del encoder) y suelo de 256.
"""
from voooxly.stt import audio_ctx_for


def test_dictado_corto_recibe_contexto_proporcional():
    # 4s * 75 = 300 frames
    assert audio_ctx_for(4.0) == 300


def test_suelo_de_256_para_dictados_minimos():
    assert audio_ctx_for(1.0) == 256   # 75 < 256 → suelo
    assert audio_ctx_for(0.5) == 256


def test_dictado_largo_no_lleva_audio_ctx():
    assert audio_ctx_for(18.1) is None
    assert audio_ctx_for(60.0) is None
    assert audio_ctx_for(300.0) is None


def test_umbral_exacto_todavia_aplica():
    assert audio_ctx_for(18.0) == 1350   # 18*75, dentro del techo 1500


def test_duracion_invalida_no_lleva_audio_ctx():
    assert audio_ctx_for(0.0) is None
    assert audio_ctx_for(-3.0) is None


def test_nunca_supera_el_techo_del_encoder():
    # por si el umbral sube en el futuro: jamás > 1500
    assert all((audio_ctx_for(s) or 0) <= 1500 for s in (1, 5, 10, 15, 18))
