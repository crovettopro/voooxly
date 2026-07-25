"""The default language cannot be the author's.

With `stt.language: "es"` hard-set in the shipped config, Whisper transcribes
whatever anyone says as Spanish; and with `app.language: "es"` the refiner
translates into Spanish what an English speaker just dictated in English. Both
make the app look broken for anyone who is not Spanish.
"""
import pathlib

import yaml

from voooxly import config as config_mod
from voooxly import modes

CONFIG = pathlib.Path(__file__).resolve().parents[1] / "config.yaml"


def _shipped():
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_el_config_distribuido_no_fuerza_idioma_de_salida():
    """app.language must ship empty: the output keeps the spoken language."""
    assert _shipped()["app"]["language"] in (None, "", "auto")


def test_distributed_config_does_not_force_transcription_language():
    """stt.language: 'auto' = use each user's system language."""
    assert _shipped()["stt"]["language"] in (None, "auto")


def test_el_diccionario_distribuido_no_lleva_datos_personales():
    """The dictionary biases the transcription: it must not carry the author's names."""
    dicc = " ".join(_shipped()["stt"].get("dictionary") or []).lower()
    for termino in ("ucademy", "eduardo", "crovetto"):
        assert termino not in dicc


def test_sin_idioma_el_prompt_no_pide_traducir():
    """The language hint is what would translate the output; with no language it must be absent."""
    prompt = modes.system_prompt("ordenar", None)
    assert "Write the output in the same language the user spoke" in prompt
    assert "regardless of the language spoken" not in prompt


def test_con_idioma_el_prompt_si_lo_pide():
    assert "Write the output in en" in modes.system_prompt("ordenar", "en")


def test_system_language_devuelve_codigo_de_dos_letras_o_none():
    lang = config_mod.system_language()
    assert lang is None or (isinstance(lang, str) and len(lang) == 2 and lang.islower())
