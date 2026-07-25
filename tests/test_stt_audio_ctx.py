"""audio_ctx proportional to the audio: the 51% improvement measured in the experiment.

Two golden rules, both measured on this Mac:
1. Long dictations get NO audio_ctx (short context over long audio =
   looping hallucination, reproduced with 19s of audio).
2. ONLY multiples of 256: whisper.cpp's Metal kernels are only fast when
   aligned (309/320/384 → ~4s; 256/512/768/1024 → <1.1s, same text).
"""
from voooxly.stt import audio_ctx_for


def test_dictado_corto_recibe_el_multiplo_superior():
    # 4s * 75 = 300 frames → next multiple of 256 = 512
    assert audio_ctx_for(4.0) == 512


def test_suelo_de_256_para_dictados_minimos():
    assert audio_ctx_for(1.0) == 256   # 75 frames → first step
    assert audio_ctx_for(0.5) == 256
    assert audio_ctx_for(3.4) == 256   # 255 frames: just below the step


def test_dictado_largo_no_lleva_audio_ctx():
    # 17.07s*75 ≈ 1281 → step 1536 > 1280 → full context
    assert audio_ctx_for(17.1) is None
    assert audio_ctx_for(60.0) is None
    assert audio_ctx_for(300.0) is None


def test_tope_de_1280_todavia_aplica():
    # 17.0s * 75 = 1275 → step 1280, the maximum allowed
    assert audio_ctx_for(17.0) == 1280


def test_duracion_invalida_no_lleva_audio_ctx():
    assert audio_ctx_for(0.0) is None
    assert audio_ctx_for(-3.0) is None


def test_siempre_alineado_a_256_y_dentro_de_rango():
    for s in (0.3, 1, 2.5, 4, 5.7, 8, 10, 13.2, 15, 17):
        ctx = audio_ctx_for(s)
        assert ctx is not None and ctx % 256 == 0 and 256 <= ctx <= 1280
