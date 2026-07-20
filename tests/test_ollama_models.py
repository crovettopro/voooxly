"""Descubrir qué modelos tiene instalados el Ollama del usuario.

Fijar un modelo por defecto a fuego presupone cuál tiene: el usuario conecta SU
modelo, así que hay que preguntárselo a su servidor.
"""

import requests

from voooxly import refine


def _fake_get(payload=None, boom=None):
    class R:
        ok = True
        def json(self):
            return payload
    def get(*a, **k):
        if boom:
            raise boom
        return R()
    return get


def test_devuelve_los_nombres_que_reporta_ollama(monkeypatch):
    monkeypatch.setattr(
        requests, "get",
        _fake_get({"models": [{"name": "llama3.2:latest"}, {"name": "mistral"}]}),
    )
    assert refine.list_ollama_models("http://localhost:11434") == ["llama3.2:latest", "mistral"]


def test_sin_modelos_devuelve_lista_vacia(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({"models": []}))
    assert refine.list_ollama_models("http://localhost:11434") == []


def test_si_ollama_no_responde_devuelve_lista_vacia_sin_lanzar(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get(boom=requests.ConnectionError("nope")))
    assert refine.list_ollama_models("http://localhost:11434") == []


def test_cuerpo_con_forma_inesperada_no_lanza(monkeypatch):
    """Se llama al construir un diálogo: si lanza, el menú se rompe."""
    for payload in ({}, {"models": "no soy una lista"}, {"models": [{}]}, None):
        monkeypatch.setattr(requests, "get", _fake_get(payload))
        assert isinstance(refine.list_ollama_models("http://localhost:11434"), list)
