"""Token counting: it can never alter which text gets pasted nor from which engine.

Review findings on d83f3bf (token counter for the free tier):

- No. 1: last_usage is assigned BEFORE the return value is built, so it
  can be left holding a cloud provider's value even though the pasted
  text ends up coming from Ollama (fallback) — a dictation attributed to
  the wrong engine in the stats.
- No. 2: the "getattr can't raise" comments overclaim: getattr only
  swallows AttributeError. Any other exception during counting (an SDK
  that changes shape, non-numeric input/output, a non-dict `usage`) escapes
  to the outer except and triggers a fallback to Ollama for a call that
  actually worked — pasting text from an engine the user did not choose.
"""
from __future__ import annotations

import sys
import types

import requests

from voooxly import refine


class CfgFake:
    def __init__(self, valores):
        self._v = valores

    def get(self, path, default=None):
        return self._v.get(path, default)


def _cfg_claude():
    return CfgFake({
        "llm.backend": "claude",
        "llm.claude.model": "claude-sonnet-5",
        "llm.claude.max_tokens": 1200,
        "llm.claude.timeout": 30,
        # _claude falls back to Ollama if it fails: it also needs its own config.
        "llm.ollama.host": "http://localhost:11434",
        "llm.ollama.model": "llama3.2",
        "llm.ollama.timeout": 5,
    })


def _cfg_openai():
    return CfgFake({
        "llm.backend": "openai",
        "llm.openai.base_url": "https://api.groq.com/openai/v1",
        "llm.openai.model": "llama-3.3-70b-versatile",
        "llm.openai.api_key_env": "GROQ_API_KEY",
        "llm.openai.timeout": 30,
        "llm.ollama.host": "http://localhost:11434",
        "llm.ollama.model": "llama3.2",
        "llm.ollama.timeout": 5,
    })


def _instalar_anthropic_falso(monkeypatch, resp):
    """Replaces the real `anthropic` module with one that always returns `resp`."""
    class FakeMessages:
        def create(self, **kwargs):
            return resp

    class FakeAnthropic:
        def __init__(self, *a, **k):
            self.messages = FakeMessages()

    modulo = types.ModuleType("anthropic")
    modulo.Anthropic = FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", modulo)


# --- Finding 1: last_usage must not go stale after a fallback ---


def test_claude_content_roto_no_deja_last_usage_con_tokens_de_una_llamada_descartada(monkeypatch):
    """Valid usage but a `content` that blows up when iterated: the final
    text comes from Ollama (fallback), so last_usage must NOT keep Claude's
    tokens — it would attribute to Claude the spend of a response that was
    never used."""
    class UsageValido:
        input_tokens = 100
        output_tokens = 50

    class ContentQueRevienta:
        def __iter__(self):
            raise RuntimeError("iterar content explota")

    class RespRota:
        usage = UsageValido()
        content = ContentQueRevienta()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _instalar_anthropic_falso(monkeypatch, RespRota())

    class R:
        status_code = 200
        text = "{}"
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "Texto de Ollama"}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())

    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Texto de Ollama"
    assert r.last_usage is None, "los tokens de Claude no pueden sobrevivir a un fallback"


def test_openai_choices_vacio_no_deja_last_usage_con_tokens_de_una_llamada_descartada(monkeypatch):
    """`usage` arrives before `choices` in the response JSON: if choices is
    empty (IndexError) the final text comes from Ollama, and last_usage must
    not keep the tokens that broken response advertised."""
    def fake_post(url, **kwargs):
        if "chat/completions" in url:
            class Rota:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"usage": {"total_tokens": 321}, "choices": []}
            return Rota()
        class Rok:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Texto de Ollama"}}
        return Rok()

    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    monkeypatch.setattr(requests, "post", fake_post)

    r = refine.Refiner(_cfg_openai())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Texto de Ollama"
    assert r.last_usage is None


# --- Finding 2: "getattr can't raise" overclaims ---


def test_claude_usage_que_lanza_no_tumba_una_llamada_exitosa(monkeypatch):
    """`usage.input_tokens` is a property that raises something that is NOT
    an AttributeError: getattr only swallows AttributeError, so this used to
    take down a Claude call that DID respond fine and retried it against
    Ollama."""
    class UsageQueExplota:
        @property
        def input_tokens(self):
            raise RuntimeError("el SDK cambió de forma")
        output_tokens = 50

    class Bloque:
        text = "Texto limpio de Claude"

    class RespBuena:
        usage = UsageQueExplota()
        content = [Bloque()]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _instalar_anthropic_falso(monkeypatch, RespBuena())
    llamadas = []
    def post_espia(*a, **k):
        llamadas.append(1)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Ollama de emergencia"}}
        return R()
    monkeypatch.setattr(requests, "post", post_espia)

    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Texto limpio de Claude"
    assert not llamadas, "no debería haber fallback a Ollama"
    assert r.last_fallback is None


def test_claude_entrada_mas_salida_no_numerico_no_rompe_una_llamada_exitosa(monkeypatch):
    """`entrada + salida` assumes both are numeric: with schema drift (one
    arrives as text) a TypeError must not throw overboard a Claude response
    that did arrive fine."""
    class UsageRaro:
        input_tokens = "muchos"
        output_tokens = 50

    class Bloque:
        text = "Otra respuesta válida"

    class RespBuena:
        usage = UsageRaro()
        content = [Bloque()]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _instalar_anthropic_falso(monkeypatch, RespBuena())
    llamadas = []
    def post_espia(*a, **k):
        llamadas.append(1)
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Ollama de emergencia"}}
        return R()
    monkeypatch.setattr(requests, "post", post_espia)

    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Otra respuesta válida"
    assert not llamadas, "no debería haber fallback a Ollama"
    assert r.last_fallback is None
    assert r.last_usage is None  # the count was lost, but the text was not


def test_openai_usage_no_dict_no_rompe_una_llamada_exitosa(monkeypatch):
    """`usage.get("total_tokens")` assumes a dict: a provider sending a
    truthy non-dict value (schema drift) must not lose an OpenAI response
    that did answer fine."""
    llamadas = []
    def fake_post(url, **kwargs):
        if "chat/completions" in url:
            class Rota:
                status_code = 200
                def raise_for_status(self): pass
                def json(self):
                    return {
                        "usage": "pendiente",  # neither dict nor None: .get() blows up
                        "choices": [{"message": {"content": "Respuesta válida de OpenAI"}}],
                    }
            return Rota()
        llamadas.append(1)
        class Rok:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {"message": {"content": "Ollama de emergencia"}}
        return Rok()

    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    monkeypatch.setattr(requests, "post", fake_post)

    r = refine.Refiner(_cfg_openai())
    out = r.refine("hola", "ordenar", "es")

    assert out == "Respuesta válida de OpenAI"
    assert not llamadas, "no debería haber fallback a Ollama"
    assert r.last_fallback is None
    assert r.last_usage is None
