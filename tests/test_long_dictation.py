"""Un dictado largo no se puede perder a medias.

El tope de 60s anulaba el latch, que existe justo para dictados largos: el
usuario fijaba la grabación, hablaba dos minutos y todo lo posterior al
segundo 60 desaparecía sin aviso. Estos tests fijan los tres topes que tienen
que subir A LA VEZ — arreglar solo el primero mueve el problema en vez de
resolverlo: sin tope de audio, el techo pasa a ser max_tokens (texto cortado
a media frase) y luego el timeout del LLM (se pega la transcripción cruda).
"""
from voooxly import audio
from voooxly.config import load_config

# 5 minutos: un dictado largo real. No se quita el tope del todo porque sigue
# siendo la red de seguridad contra una tecla encallada, que grabaría hasta
# llenar el disco.
MIN_DURACION = 300.0


def test_el_dataclass_permite_dictados_largos():
    assert audio.AudioConfig().max_duration >= MIN_DURACION


def test_el_yaml_permite_dictados_largos():
    cfg = load_config()
    assert cfg.get("audio.max_duration", 0) >= MIN_DURACION


def test_el_refinado_no_corta_el_texto_de_un_dictado_largo():
    # 5 min de habla ≈ 750 palabras ≈ 1000 tokens de salida. Con 1200 el
    # texto salía cortado a media frase en cuanto se quitaba el tope de 60s.
    cfg = load_config()
    assert cfg.get("llm.claude.max_tokens", 0) >= 4000


def test_el_llm_local_tiene_tiempo_para_un_texto_largo():
    # 20s bastaban para 150 palabras; para 750 no. Al vencer, el código cae a
    # pegar la transcripción cruda: el usuario lo vive como "la IA dejó de
    # funcionar justo en los dictados largos".
    cfg = load_config()
    assert cfg.get("llm.ollama.timeout", 0) >= 60
