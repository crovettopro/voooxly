"""audio_ctx proporcional al audio: la mejora del 51% medida en el experimento.

Dos reglas de oro, ambas medidas en este Mac:
1. Dictados largos NO llevan audio_ctx (contexto corto sobre audio largo =
   alucinación en bucle, reproducido con 19s de audio).
2. SOLO múltiplos de 256: los kernels Metal de whisper.cpp solo van rápidos
   alineados (309/320/384 → ~4s; 256/512/768/1024 → <1.1s, mismo texto).
"""
from voooxly.stt import audio_ctx_for


def test_dictado_corto_recibe_el_multiplo_superior():
    # 4s * 75 = 300 frames → siguiente múltiplo de 256 = 512
    assert audio_ctx_for(4.0) == 512


def test_suelo_de_256_para_dictados_minimos():
    assert audio_ctx_for(1.0) == 256   # 75 frames → primer escalón
    assert audio_ctx_for(0.5) == 256
    assert audio_ctx_for(3.4) == 256   # 255 frames: justo bajo el escalón


def test_dictado_largo_no_lleva_audio_ctx():
    # 17.07s*75 ≈ 1281 → escalón 1536 > 1280 → contexto completo
    assert audio_ctx_for(17.1) is None
    assert audio_ctx_for(60.0) is None
    assert audio_ctx_for(300.0) is None


def test_tope_de_1280_todavia_aplica():
    # 17.0s * 75 = 1275 → escalón 1280, el máximo permitido
    assert audio_ctx_for(17.0) == 1280


def test_duracion_invalida_no_lleva_audio_ctx():
    assert audio_ctx_for(0.0) is None
    assert audio_ctx_for(-3.0) is None


def test_siempre_alineado_a_256_y_dentro_de_rango():
    for s in (0.3, 1, 2.5, 4, 5.7, 8, 10, 13.2, 15, 17):
        ctx = audio_ctx_for(s)
        assert ctx is not None and ctx % 256 == 0 and 256 <= ctx <= 1280
