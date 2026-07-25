"""Degradation signal: the user must know when the AI did not act.

Owner directive (2026-07-20): if there is no key or the provider does not
work, warn — and still paste whatever we can. Raw text due to FAILURE sets
last_fallback; DELIBERATE raw text (literal mode, no backend) does not.
"""

import sys

import pytest
import requests

from voooxly import refine


class CfgFake:
    def __init__(self, valores):
        self._v = valores

    def get(self, path, default=None):
        return self._v.get(path, default)


def _cfg_ollama():
    return CfgFake({
        "llm.backend": "ollama",
        "llm.ollama.host": "http://localhost:11434",
        "llm.ollama.model": "llama3.2",
        "llm.ollama.timeout": 5,
    })


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


def test_network_failure_marks_last_fallback_and_returns_raw(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_ollama())
    out = r.refine("hola que tal", "ordenar", "es")
    assert out == "hola que tal"
    assert r.last_fallback


def test_success_leaves_last_fallback_none(monkeypatch):
    class R:
        status_code = 200
        text = "{}"
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "Hola, ¿qué tal?"}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    r = refine.Refiner(_cfg_ollama())
    assert r.refine("hola que tal", "ordenar", "es") == "Hola, ¿qué tal?"
    assert r.last_fallback is None


def test_literal_mode_does_not_mark_fallback():
    r = refine.Refiner(_cfg_ollama())
    assert r.refine("tal cual", "literal", "es") == "tal cual"
    assert r.last_fallback is None


def test_backend_none_does_not_mark_fallback():
    """With no AI configured, raw text is what was promised, not a failure."""
    r = refine.Refiner(CfgFake({"llm.backend": "none"}))
    assert r.refine("hola", "ordenar", "es") == "hola"
    assert r.last_fallback is None


def test_success_after_failure_clears_flag(monkeypatch):
    """The flag belongs to the LAST refine(), not a sticky alarm."""
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_ollama())
    r.refine("uno", "ordenar", "es")
    assert r.last_fallback

    class R:
        status_code = 200
        text = "{}"
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": "Dos."}}
    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    r.refine("dos", "ordenar", "es")
    assert r.last_fallback is None


def test_broken_claude_prelude_falls_back_to_ollama_and_marks_last_fallback(monkeypatch):
    """The `anthropic` import and the client construction live INSIDE
    _claude's try. A broken install (or any failure before calling the
    API) has to follow the same path as an API failure: fallback to
    Ollama and last_fallback set — never an exception escaping refine()
    without warning the user."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # sys.modules["anthropic"] = None makes "import anthropic" raise
    # ImportError, regardless of whether the package is installed or not.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola que tal", "ordenar", "es")
    assert out == "hola que tal"
    assert r.last_fallback


def test_explicit_claude_without_env_key_still_dispatches_to_claude(monkeypatch):
    """An explicitly chosen "claude" backend ALWAYS dispatches to _claude,
    even if ANTHROPIC_API_KEY is not in the environment (e.g. the keychain
    read failed at startup). Before, without the variable, refine() skipped
    the Claude branch and called _ollama directly: silently refined by the
    wrong engine, or failures attributed to Ollama. The path attributed to
    Claude must run: _claude fails (broken import), falls back to _ollama,
    and the Ollama failure leaves last_fallback set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))

    llamadas_claude = []
    original = refine.Refiner._claude

    def espia(self, system, user):
        llamadas_claude.append(True)
        return original(self, system, user)

    monkeypatch.setattr(refine.Refiner, "_claude", espia)
    r = refine.Refiner(_cfg_claude())
    out = r.refine("hola que tal", "ordenar", "es")
    assert llamadas_claude, "refine() debe despachar a _claude aunque falte la env key"
    assert out == "hola que tal"
    assert r.last_fallback


def test_broken_claude_prelude_in_strict_mode_reraises(monkeypatch):
    """In strict mode (used by _probe/validate) the same failure must
    propagate: papering over the gap with Ollama would hide that THIS
    candidate (Claude) never answered."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setitem(sys.modules, "anthropic", None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: (_ for _ in ()).throw(
        requests.ConnectionError("sin red")))
    r = refine.Refiner(_cfg_claude())
    r.strict = True
    with pytest.raises(ImportError):
        r.refine("hola que tal", "ordenar", "es")
