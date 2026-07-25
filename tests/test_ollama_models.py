"""Discover which models the user's Ollama has installed.

Hard-coding a default model presumes which one they have: the user connects THEIR
model, so we have to ask their server.
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


def test_if_ollama_does_not_respond_returns_empty_list_without_raising(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get(boom=requests.ConnectionError("nope")))
    assert refine.list_ollama_models("http://localhost:11434") == []


def test_unexpected_body_shape_does_not_raise(monkeypatch):
    """Called while building a dialog: if it raises, the menu breaks."""
    for payload in ({}, {"models": "no soy una lista"}, {"models": [{}]}, None):
        monkeypatch.setattr(requests, "get", _fake_get(payload))
        assert isinstance(refine.list_ollama_models("http://localhost:11434"), list)
