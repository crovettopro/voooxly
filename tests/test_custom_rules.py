"""llm.custom_rules: the user's personal rules must reach the system
prompt of every mode (except Verbatim) and not appear when they are empty.
"""
from unittest.mock import patch

from voooxly.refine import Refiner


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


def test_no_rules_no_section_added():
    assert "Personal rules" not in _refine_capturing_system(_Cfg())
    assert "Personal rules" not in _refine_capturing_system(_Cfg({"llm.custom_rules": "   "}))


def test_verbatim_ignores_rules_and_llm():
    cfg = _Cfg({"llm.custom_rules": "whatever"})
    with patch.object(Refiner, "_ollama", side_effect=AssertionError("no debe llamarse")):
        out = Refiner(cfg).refine("tal cual", "literal", None)
    assert out == "tal cual"
