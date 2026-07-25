"""Auto-detection cascade (detect_backend): what counts as a provider.

A reachable Ollama with no model configured is NOT a provider: Ollama.app
auto-starts its server, and claiming it doomed every dictation to a 400 + an
"AI didn't answer" warning forever (and shadowed the environment keys further
down the cascade). Until the user connects it from the menu, the raw paste
must stay clean and warning-free.
"""

import requests

from voooxly import refine


class CfgFake:
    def __init__(self, valores):
        self._v = valores

    def get(self, path, default=None):
        return self._v.get(path, default)


class _RespuestaOK:
    ok = True


def _servidor_ollama_alcanzable(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _RespuestaOK())


def _sin_keys_de_entorno(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_reachable_ollama_without_configured_model_is_not_a_provider(monkeypatch):
    """Server up + empty llm.ollama.model + no keys → "none"."""
    # monkeypatch restores the module cache when done: no leaks between tests.
    monkeypatch.setattr(refine, "_detected", None)
    _servidor_ollama_alcanzable(monkeypatch)
    _sin_keys_de_entorno(monkeypatch)
    cfg = CfgFake({"llm.ollama.model": ""})
    assert refine.detect_backend(cfg, force=True) == "none"


def test_ollama_sin_modelo_deja_pasar_la_cascada_hasta_claude(monkeypatch):
    """Server up + empty model + ANTHROPIC_API_KEY → "claude".

    Before, the cascade stopped at "ollama" on mere reachability and a
    perfectly functional environment key never got used.
    """
    monkeypatch.setattr(refine, "_detected", None)
    _servidor_ollama_alcanzable(monkeypatch)
    _sin_keys_de_entorno(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = CfgFake({"llm.ollama.model": ""})
    assert refine.detect_backend(cfg, force=True) == "claude"


def test_ollama_con_modelo_configurado_sigue_detectandose(monkeypatch):
    """Server up + model configured → "ollama", as always."""
    monkeypatch.setattr(refine, "_detected", None)
    _servidor_ollama_alcanzable(monkeypatch)
    _sin_keys_de_entorno(monkeypatch)
    cfg = CfgFake({"llm.ollama.model": "llama3.2"})
    assert refine.detect_backend(cfg, force=True) == "ollama"
