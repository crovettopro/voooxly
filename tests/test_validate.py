"""validate() manda una generación real y traduce el fallo a algo legible."""

import pytest

from voooxly import ai_settings, providers, refine


def seleccion(key="ollama", model="llama3.2"):
    return ai_settings.Selection(
        provider=providers.get(key),
        base_url=providers.get(key).base_url,
        model=model,
    )


def test_ok_cuando_el_modelo_responde(monkeypatch):
    monkeypatch.setattr(refine, "_probe", lambda *a, **k: "OK")
    ok, msg = refine.validate(seleccion(), None)
    assert ok is True
    assert "llama3.2" in msg


def test_falla_nombrando_el_modelo_que_no_existe(monkeypatch):
    """El caso glm-5.2:cloud: el servidor responde, el modelo no está."""
    def explota(*a, **k):
        raise refine.ModelNotAvailable("model 'glm-5.2:cloud' not found")

    monkeypatch.setattr(refine, "_probe", explota)
    ok, msg = refine.validate(seleccion(model="glm-5.2:cloud"), None)
    assert ok is False
    assert "glm-5.2:cloud" in msg


def test_falla_si_el_proveedor_pide_key_y_no_hay():
    ok, msg = refine.validate(seleccion("groq", "llama-3.3-70b-versatile"), None)
    assert ok is False
    assert "key" in msg.lower()


def test_falla_legible_si_no_hay_red(monkeypatch):
    import requests

    def sin_red(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(refine, "_probe", sin_red)
    ok, msg = refine.validate(seleccion(), None)
    assert ok is False
    assert msg and "Traceback" not in msg


def test_una_respuesta_vacia_cuenta_como_fallo(monkeypatch):
    monkeypatch.setattr(refine, "_probe", lambda *a, **k: "")
    ok, _ = refine.validate(seleccion(), None)
    assert ok is False
