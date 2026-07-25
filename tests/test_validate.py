"""validate() sends a real generation and translates the failure into something readable."""

import copy
import os

import pytest

from voooxly import ai_settings, providers, refine


def seleccion(key="ollama", model="llama3.2"):
    return ai_settings.Selection(
        provider=providers.get(key),
        base_url=providers.get(key).base_url,
        model=model,
    )


class _FakeCfg:
    """Minimal config to instantiate a Refiner without touching the real one."""

    def __init__(self, valores=None):
        self._valores = valores or {}

    def get(self, path, default=None):
        return self._valores.get(path, default)


class _FakeResp:
    """Fake HTTP response for monkeypatching requests.post."""

    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


def test_ok_when_model_responds(monkeypatch):
    monkeypatch.setattr(refine, "_probe", lambda *a, **k: "OK")
    ok, msg = refine.validate(seleccion(), None)
    assert ok is True
    assert "llama3.2" in msg


def test_falla_nombrando_el_modelo_que_no_existe(monkeypatch):
    """The glm-5.2:cloud case: the server responds, the model is not there."""
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


def test_fails_if_no_model_chosen():
    """With an empty model (e.g. after deleting the key from config.yaml) the
    message must ask to pick a model, never talk about "reach"/"connect" — that
    text sent the user off to debug their network over an unchosen model."""
    ok, msg = refine.validate(seleccion(model=""), None)
    assert ok is False
    assert "model" in msg.lower()
    assert "reach" not in msg.lower()
    assert "connect" not in msg.lower()


def test_falla_si_no_hay_modelo_no_hace_ninguna_peticion(monkeypatch):
    """The guard has to cut in BEFORE _probe(): with no model, no HTTP
    request may go out."""
    llamadas = []
    monkeypatch.setattr(
        refine.requests, "post", lambda *a, **k: llamadas.append(a or k) or None
    )
    ok, _ = refine.validate(seleccion(model=""), None)
    assert ok is False
    assert llamadas == []


def test_fails_legibly_if_no_network(monkeypatch):
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


# --- Finding 1: the GENERATED text cannot trigger ModelNotAvailable ---
# These tests do NOT monkeypatch _probe: they exercise the real _ollama against
# a fake requests.post, which is exactly what the 4 tests above did not cover.


def test_200_con_no_encontrado_en_el_texto_generado_no_debe_fallar(monkeypatch):
    """Reproduces finding 1: a 200 whose content says "not found" (because
    the user dictated that phrase) has to be returned as-is, never raise
    ModelNotAvailable."""
    contenido = "The file was not found in the folder, so I created it."
    resp = _FakeResp(200, {"message": {"content": contenido}})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    r = refine.Refiner(_FakeCfg())
    salida = r._ollama("system", "user")
    assert salida == contenido


def test_error_real_de_modelo_ausente_lanza_ModelNotAvailable(monkeypatch):
    """A real error (status >= 400) with "not found" in the JSON error field
    does have to be singled out as ModelNotAvailable."""
    resp = _FakeResp(404, {"error": "model 'glm-5.2:cloud' not found, try pulling it first"})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    r = refine.Refiner(_FakeCfg({"llm.ollama.model": "glm-5.2:cloud"}))
    with pytest.raises(refine.ModelNotAvailable):
        r._ollama("system", "user")


# --- Findings 2 and 3: _probe cannot touch the config singleton ---


def test_probe_does_not_modify_config_singleton_after_success(monkeypatch):
    from voooxly.config import get_config

    cfg = get_config()
    antes = copy.deepcopy(cfg.raw)

    resp = _FakeResp(200, {"message": {"content": "OK"}})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    ok, _ = refine.validate(seleccion(), None)
    assert ok is True
    assert cfg.raw == antes


def test_probe_no_modifica_el_singleton_de_config_tras_fallo(monkeypatch):
    from voooxly.config import get_config

    cfg = get_config()
    antes = copy.deepcopy(cfg.raw)

    resp = _FakeResp(404, {"error": "model 'llama3.2' not found"})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    ok, msg = refine.validate(seleccion(), None)
    assert ok is False
    assert cfg.raw == antes


# --- Finding 3: each "kind" probes its own host/base_url route ---


def test_probe_ollama_targets_candidate_host_not_config_host(monkeypatch):
    llamadas = []
    resp = _FakeResp(200, {"message": {"content": "OK"}})

    def fake_post(url, **kwargs):
        llamadas.append(url)
        return resp

    monkeypatch.setattr(refine.requests, "post", fake_post)

    sel = ai_settings.Selection(
        provider=providers.get("ollama"),
        base_url="http://candidate-host:9999",
        model="llama3.2",
    )
    refine._probe(sel, None, 5.0)
    assert llamadas and llamadas[0].startswith("http://candidate-host:9999")


def test_probe_openai_apunta_al_base_url_del_candidato(monkeypatch):
    llamadas = []
    resp = _FakeResp(200, {"choices": [{"message": {"content": "OK"}}]})

    def fake_post(url, **kwargs):
        llamadas.append(url)
        return resp

    monkeypatch.setattr(refine.requests, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    sel = ai_settings.Selection(
        provider=providers.get("openai"),
        base_url="https://candidate.example/v1",
        model="gpt-4o-mini",
    )
    refine._probe(sel, None, 5.0)
    assert llamadas and llamadas[0].startswith("https://candidate.example/v1")


# --- Finding 4: the probe cannot hide behind the live-dictation fallback ---
#
# _openai() and _claude() fall back to Ollama if the remote backend fails —
# right for a real dictation, where the user prefers unrefined text to nothing.
# But _probe() reuses those same methods: without strict mode, a broken
# openai/claude candidate (invalid key, no network, nonexistent base_url) fell
# back to the Ollama ALREADY CONFIGURED on the machine, which answered fine, and
# validate() reported success naming a provider that never actually replied.
# None of these tests monkeypatch _probe: they exercise the real _openai/_claude
# against a fake requests.post, just like the "Finding 1" ones.


def test_failing_probe_openai_does_not_fall_back_to_configured_ollama(monkeypatch):
    """Without strict mode, this test would fail: fake_post would answer "OK"
    on the second call (the fallback to Ollama) and validate() would return
    success for a candidate that actually returned 401."""
    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(url)
        if "candidate.example" in url:
            raise Exception("401 unauthorized")
        # If this ever gets called, the Ollama fallback slipped through: it
        # answers fine on purpose to show it would mask the failure.
        return _FakeResp(200, {"message": {"content": "OK"}})

    monkeypatch.setattr(refine.requests, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-bad-key")

    sel = ai_settings.Selection(
        provider=providers.get("openai"),
        base_url="https://candidate.example/v1",
        model="gpt-4o-mini",
    )
    ok, msg = refine.validate(sel, "sk-bad-key", timeout=5.0)
    assert ok is False
    # Only the call to the candidate: had the fallback slipped through there
    # would be a second call (to the Ollama host).
    assert llamadas == ["https://candidate.example/v1/chat/completions"]


def test_failing_probe_claude_does_not_fall_back_to_configured_ollama(monkeypatch):
    """Same idea with kind="claude": _claude() uses the anthropic SDK, not
    requests.post directly, so the invalid key is simulated there. The fake
    requests.post stays in place to show that the Ollama fallback (had it
    slipped through) would answer fine and mask the failure."""
    import anthropic

    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(url)
        return _FakeResp(200, {"message": {"content": "OK"}})

    monkeypatch.setattr(refine.requests, "post", fake_post)

    class _ClienteQueFalla:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise Exception("401 invalid x-api-key")

    monkeypatch.setattr(anthropic, "Anthropic", lambda: _ClienteQueFalla())

    sel = ai_settings.Selection(
        provider=providers.get("claude"),
        base_url=providers.get("claude").base_url,
        model="claude-sonnet-5",
    )
    ok, msg = refine.validate(sel, "clave-invalida", timeout=5.0)
    assert ok is False
    # No call to requests.post: had the Ollama fallback slipped through,
    # there would be one (and it would even answer "OK", masking the failure).
    assert llamadas == []


def test_live_dictation_still_falls_back_to_ollama_if_openai_fails(monkeypatch):
    """The normal Refiner (the one app.py uses to dictate) is NOT strict: if
    the remote backend fails mid-dictation, the user must keep receiving
    text (unrefined) rather than nothing."""
    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(url)
        if "api.openai.com" in url:
            raise Exception("network fail")
        return _FakeResp(200, {"message": {"content": "texto refinado por ollama"}})

    monkeypatch.setattr(refine.requests, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key")

    r = refine.Refiner(_FakeCfg({"llm.backend": "openai"}))
    assert r.strict is False
    salida = r._openai("system", "user")
    assert salida == "texto refinado por ollama"
    assert len(llamadas) == 2


# --- Finding 5: _ollama also had to honor strict mode ---
#
# _claude and _openai already re-raised in strict mode instead of masking the
# failure, but _ollama was left out: its generic except always returned `user`
# (the input transcription/prompt) as if it were the model's answer. For real
# dictation that is the right call (no network must not lose the text), but
# _probe(kind="ollama") calls _ollama() directly, and validate() only checks
# that the output is non-empty — a completely unreachable Ollama returned the
# "ping" prompt as-is and validate() read it as success.


def test_unreachable_ollama_in_probe_mode_does_not_report_success(monkeypatch):
    """Exact reproduction from the reviewer: with requests.post raising
    ConnectionError, validate() must return (False, ...), not (True,
    "Connected to Ollama...")."""
    import requests

    def sin_red(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    sel = ai_settings.Selection(
        provider=providers.get("ollama"),
        base_url="http://broken-host:11434",
        model="llama3.2",
    )
    ok, msg = refine.validate(sel, None)
    assert ok is False


def test_ollama_with_timeout_in_probe_mode_does_not_report_success(monkeypatch):
    """Same finding, with a timeout instead of a refused connection."""
    import requests

    def se_cuelga(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(refine.requests, "post", se_cuelga)

    sel = ai_settings.Selection(
        provider=providers.get("ollama"),
        base_url="http://broken-host:11434",
        model="llama3.2",
    )
    ok, msg = refine.validate(sel, None)
    assert ok is False


def test_live_dictation_still_returns_transcription_if_ollama_fails(monkeypatch):
    """The normal Refiner (the one app.py uses to dictate) is NOT strict: if
    Ollama fails mid-dictation, the user must keep receiving their raw
    transcription, exactly as before this fix."""
    import requests

    def sin_red(*a, **k):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    r = refine.Refiner(_FakeCfg())
    assert r.strict is False
    salida = r._ollama("system", "transcripción cruda del usuario")
    assert salida == "transcripción cruda del usuario"


# --- Finding 6: a rejected key cannot linger in os.environ ---
#
# _probe() calls export_key(selection, api_key) BEFORE generating, because
# _openai()/_claude() read the key from the environment. If validation failed,
# nothing removed it: detect_backend() only checks the PRESENCE of the
# variable, so a freshly rejected key biased the next auto-detection toward
# the provider that had just failed.


def _sel_openai(model="gpt-4o-mini"):
    prov = providers.get("openai")
    return ai_settings.Selection(provider=prov, base_url=prov.base_url, model=model)


def test_falla_restaura_ausencia_previa_de_la_env_var(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def sin_red(*a, **k):
        raise refine.requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    ok, _ = refine.validate(_sel_openai(), "sk-new-bad-key")

    assert ok is False
    assert "OPENAI_API_KEY" not in os.environ


def test_falla_restaura_el_valor_previo_de_la_env_var(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-old-working")

    def sin_red(*a, **k):
        raise refine.requests.ConnectionError("nope")

    monkeypatch.setattr(refine.requests, "post", sin_red)

    ok, _ = refine.validate(_sel_openai(), "sk-new-bad-key")

    assert ok is False
    assert os.environ.get("OPENAI_API_KEY") == "sk-old-working"


def test_success_leaves_new_key_in_place(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = _FakeResp(200, {"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(refine.requests, "post", lambda *a, **k: resp)

    ok, _ = refine.validate(_sel_openai(), "sk-new-working")

    assert ok is True
    assert os.environ.get("OPENAI_API_KEY") == "sk-new-working"
