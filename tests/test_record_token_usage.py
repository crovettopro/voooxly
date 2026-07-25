"""_record_token_usage(): token counting can neither block nor pollute
the paste. At module level (same reason as apply_ai_selection, see
test_apply_ai_selection.py) so it can be tested without instantiating VoooxlyApp.

Finding 3: ai_settings.load(self._prefs) ran inside _process's try/except
and BEFORE output.deliver(). If it raised, the method aborted to the upper
catch-all and the already-refined text never got pasted — the worst possible
outcome for a task meant only to count tokens. stats.bump_tokens was already
properly wrapped; what was missing was wrapping the new call.
"""
from __future__ import annotations

from voooxly import ai_settings, app, stats


class _RefinerFake:
    def __init__(self, last_usage):
        self.last_usage = last_usage


def test_sin_uso_no_llama_a_bump_tokens(monkeypatch):
    llamadas = []
    monkeypatch.setattr(stats, "bump_tokens", lambda *a, **k: llamadas.append((a, k)))
    app._record_token_usage(_RefinerFake(None), {})
    assert not llamadas


def test_with_usage_calls_bump_tokens_with_saved_provider(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        stats, "bump_tokens", lambda tokens, provider: llamadas.append((tokens, provider))
    )
    prefs = {"ai_provider": "groq", "ai_model": "llama-3.3-70b-versatile"}
    app._record_token_usage(_RefinerFake(321), prefs)
    assert llamadas
    tokens, provider = llamadas[0]
    assert tokens == 321
    assert provider  # the label of the provider saved in prefs


def test_broken_ai_settings_load_does_not_raise(monkeypatch):
    """If ai_settings.load() were to raise (corrupt prefs.json, an
    unexpected type...) this must NOT escape: in _process it runs AFTER
    output.deliver(), and losing the paste over a token-counting failure
    is exactly what this finding forbids."""
    def load_roto(prefs):
        raise RuntimeError("prefs.json corrupto")

    monkeypatch.setattr(ai_settings, "load", load_roto)
    app._record_token_usage(_RefinerFake(100), {})  # must not raise


def test_bump_tokens_roto_tampoco_escapa(monkeypatch):
    def bump_roto(*a, **k):
        raise RuntimeError("disco lleno")

    monkeypatch.setattr(stats, "bump_tokens", bump_roto)
    app._record_token_usage(_RefinerFake(100), {})  # must not raise
