"""llm.custom_rules: las reglas personales del usuario deben llegar al system
prompt de cualquier modo (menos Verbatim) y no aparecer cuando están vacías.
"""
from unittest.mock import patch

from dictador.refine import Refiner


class _Cfg:
    def __init__(self, extra=None):
        self._d = {"llm.backend": "ollama", **(extra or {})}

    def get(self, key, default=None):
        return self._d.get(key, default)


def _refine_capturing_system(cfg, mode="ordenar"):
    captured = {}

    def fake_ollama(self, system, user):
        captured["system"] = system
        return "ok"

    with patch.object(Refiner, "_ollama", fake_ollama):
        Refiner(cfg).refine("hola qué tal", mode, None)
    return captured.get("system", "")


def test_las_reglas_personales_llegan_al_prompt():
    cfg = _Cfg({"llm.custom_rules": "Never use semicolons. Spell it Ucademy."})
    system = _refine_capturing_system(cfg)
    assert "Personal rules from the user" in system
    assert "Never use semicolons. Spell it Ucademy." in system


def test_sin_reglas_no_se_añade_la_seccion():
    assert "Personal rules" not in _refine_capturing_system(_Cfg())
    assert "Personal rules" not in _refine_capturing_system(_Cfg({"llm.custom_rules": "   "}))


def test_verbatim_ignora_las_reglas_y_el_llm():
    cfg = _Cfg({"llm.custom_rules": "whatever"})
    with patch.object(Refiner, "_ollama", side_effect=AssertionError("no debe llamarse")):
        out = Refiner(cfg).refine("tal cual", "literal", None)
    assert out == "tal cual"
