"""LLM refinement: turns the raw transcription into the final text per the mode.

Backends:
- ollama: local endpoint http://localhost:11434 (local model or routed cloud model)
- claude: Anthropic API (if ANTHROPIC_API_KEY)
- openai: any OpenAI-compatible endpoint

Each mode (modes.system_prompt) defines the system prompt. The "literal" mode
skips the LLM and returns the transcription as-is.
"""
from __future__ import annotations

import logging
import os

import requests

from . import modes

log = logging.getLogger("voooxly.refine")

# Cached result of the auto-detection (backend "auto"). Refreshed with
# detect_backend(force=True) — the "AI engine" menu and the keepalive do it.
_detected: str | None = None


def detect_backend(cfg=None, force: bool = False) -> str:
    """Auto-detection cascade for the available LLM engine.

    ollama running → claude (ANTHROPIC_API_KEY) → openai (key) → "none".
    With "none" Voooxly pastes the raw transcription: works with no AI installed.
    """
    global _detected
    if _detected is not None and not force:
        return _detected
    if cfg is None:
        from .config import get_config

        cfg = get_config()
    try:
        r = requests.get(
            f"{cfg.get('llm.ollama.host', 'http://localhost:11434')}/api/tags",
            timeout=1.5,
        )
        # A reachable Ollama WITHOUT a configured model is NOT a provider:
        # Ollama.app auto-starts its server, and claiming it here with
        # llm.ollama.model empty doomed every dictation to a 400 + an
        # "AI didn't answer" warning forever (and the cascade never reached an
        # environment key further down that did work). The user connects
        # Ollama explicitly from the menu; until then the raw paste
        # must stay clean and warning-free.
        if r.ok and cfg.get("llm.ollama.model", ""):
            _detected = "ollama"
            return _detected
    except Exception:
        pass
    if os.environ.get("ANTHROPIC_API_KEY"):
        _detected = "claude"
        return _detected
    if os.environ.get(cfg.get("llm.openai.api_key_env", "OPENAI_API_KEY")):
        _detected = "openai"
        return _detected
    _detected = "none"
    log.info("No LLM engine detected: dictations are pasted unrefined.")
    return _detected


# OpenAI families that ONLY accept the default temperature: sending them any
# other is a flat 400 Bad Request (the actual failure with gpt-5-mini while
# gpt-4.1-mini connected). Matched by prefix with a separator ("-" or ".") so
# that "gpt-5.6-luna" counts and "gpt-4o" or "olmo-7b" don't.
# Whoever adds a provider here: check its temperature first. Moonshot (Kimi)
# fixes it per family and answers 400 to any other value, so it can't ride
# this path unchanged — it was left out of the launch for exactly that.
_RAZONADORES = ("gpt-5", "o1", "o3", "o4")


def _es_razonador(model: str) -> bool:
    m = (model or "").lower()
    return any(
        m == p or m.startswith(p + "-") or m.startswith(p + ".")
        for p in _RAZONADORES
    )


def openai_payload(model: str, system: str, user: str, temp) -> dict:
    """Body of the POST /chat/completions. Pure module-level function so the
    contract stays nailed down in tests: reasoning models get the temperature
    omitted; the rest (gpt-4*, llama, gemini, grok) keep receiving it,
    because taking it away would silently change their output."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if not _es_razonador(model):
        body["temperature"] = temp
    return body


def list_ollama_models(host: str, timeout: float = 3.0) -> list[str]:
    """Models the user's Ollama says it has. Never raises.

    Used to offer THEIR models instead of presuming which one they have. Any
    failure returns an empty list: the caller is building a dialog and an
    exception here would break the menu.
    """
    try:
        r = requests.get(f"{host.rstrip('/')}/api/tags", timeout=timeout)
        if not r.ok:
            return []
        modelos = (r.json() or {}).get("models") or []
        if not isinstance(modelos, list):
            return []
        return [n for m in modelos if isinstance(m, dict) and (n := m.get("name"))]
    except Exception:
        log.debug("Couldn't list Ollama models at %s", host, exc_info=True)
        return []


class Refiner:
    def __init__(self, cfg):
        self.cfg = cfg
        self.backend = cfg.get("llm.backend", "auto")
        # Strict mode: only _probe turns it on (see below). With strict=False
        # (always in real dictation, via app.py), _openai/_claude keep their
        # fallback to Ollama if the remote backend fails — so the user is
        # never left without text mid-dictation. In strict mode that
        # fallback is disabled and the real error is re-raised, because _probe
        # needs to know whether THE CANDIDATE answers, not whether Ollama
        # answers in its place (otherwise validate() could report success for
        # a provider that never replied — the already-configured Ollama itself
        # masked the failure).
        self.strict = False
        # None if refine() finished fine (or needed no LLM); text with the
        # cause if the final result was the raw transcription DUE TO A FAILURE.
        # The deliberate paths (literal, backend "none") don't touch it.
        self.last_fallback: str | None = None
        # Tokens of the last call to the remote LLM, or None if there was none
        # (fast-lane, literal mode, backend "none", Ollama). app.py reads it
        # for the stats. Ollama doesn't count: it's local and burns no quota.
        self.last_usage: int | None = None

    def refine(self, transcript: str, mode: str, language: str | None) -> str:
        transcript = (transcript or "").strip()
        self.last_fallback = None
        self.last_usage = None
        if not transcript:
            return ""
        sys_prompt = modes.system_prompt(mode, language)
        if not sys_prompt:  # literal mode
            return transcript
        # The user's personal rules (llm.custom_rules): appended AT THE END
        # so they can qualify any mode ("never use semicolons",
        # "my name is spelled Eduardo"...). Empty by default.
        custom = str(self.cfg.get("llm.custom_rules", "") or "").strip()
        if custom:
            sys_prompt += "\n\nPersonal rules from the user — always follow them:\n" + custom

        backend = self.backend
        if backend == "auto":
            backend = detect_backend(self.cfg)
        if backend == "none":
            return transcript
        if backend == "claude":
            # Not conditioned on ANTHROPIC_API_KEY being in the environment: if
            # the user chose Claude explicitly, dispatch ALWAYS goes to
            # _claude. Before, with the variable absent (e.g. a failed keychain
            # read at startup), it silently fell to _ollama with the
            # menu saying Claude: refined by the wrong engine or failures
            # misattributed. _claude already does the right thing without a
            # key: strict re-raises; otherwise, fallback to _ollama, whose own
            # failure sets last_fallback.
            return self._claude(sys_prompt, transcript)
        if backend == "openai":
            return self._openai(sys_prompt, transcript)
        # default + fallback
        return self._ollama(sys_prompt, transcript)

    # --- Ollama ---
    def _ollama(self, system: str, user: str) -> str:
        host = self.cfg.get("llm.ollama.host", "http://localhost:11434")
        model = self.cfg.get("llm.ollama.model", "")
        temp = self.cfg.get("llm.ollama.temperature", 0.3)
        timeout = self.cfg.get("llm.ollama.timeout", 30)
        try:
            r = requests.post(
                f"{host}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    # reasoning models (GLM, qwen, deepseek) burn 200-4700
                    # tokens "thinking" before answering: 1.6-40s of extra latency
                    # that adds nothing for cleaning up a dictation
                    "think": False,
                    "options": {"temperature": temp},
                },
                timeout=timeout,
            )
            if r.status_code >= 400:
                # CAREFUL: only here, with a real error response. Before,
                # r.text (the raw body) was checked WITHOUT looking at the
                # status, so a 200 whose generated text contained "not found"
                # (e.g. "The file was not found...") triggered ModelNotAvailable
                # and the dictation was lost. A 2xx can never reach here.
                error_detail = ""
                try:
                    body = r.json()
                    if isinstance(body, dict):
                        error_detail = str(body.get("error", ""))
                except ValueError:
                    pass  # non-JSON error body: falls to the generic raise_for_status
                if "not found" in error_detail.lower():
                    raise ModelNotAvailable(f"model '{model}' not found on the Ollama host")
                r.raise_for_status()
            data = r.json()
            return (data.get("message", {}).get("content", "") or "").strip()
        except ModelNotAvailable:
            # This case has to reach validate(): it is exactly what tells
            # "server up, model missing" apart from any other failure. If it
            # fell into the except below, it would be indistinguishable and
            # validate() would never see it (the glm-5.2:cloud bug that
            # originated this task).
            raise
        except Exception as e:
            if self.strict:
                # Same reason as in _claude/_openai: in probe mode, returning
                # the transcription as-is as if it were the model's
                # response is indistinguishable from a real success for
                # validate() (it only checks the output isn't empty). Without
                # this, a completely unreachable Ollama reported "Connected" —
                # the very false-positive bug the strict flag exists to avoid.
                raise
            log.error("Ollama failed (%s). Returning unrefined transcription.", e)
            self.last_fallback = f"Ollama: {e}"
            return user

    # --- Claude ---
    def _claude(self, system: str, user: str) -> str:
        try:
            # The import, the client construction and the config reads live
            # INSIDE the try on purpose: a broken install, a badly set
            # env or a config value of an invalid type are just as much
            # "Claude failed" as an API error, and must follow the same path
            # (strict re-raises; otherwise, fallback to Ollama). Outside the
            # try they escaped refine() without setting last_fallback.
            import anthropic

            client = anthropic.Anthropic()
            model = self.cfg.get("llm.claude.model", "claude-sonnet-5")
            max_tokens = self.cfg.get("llm.claude.max_tokens", 1200)
            timeout = self.cfg.get("llm.claude.timeout", 30)
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                timeout=timeout,
            )
            texto = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
            # The counting runs AFTER `texto` is built, and in its
            # OWN try/except — not the outer one. "getattr can't
            # raise" was a lie: getattr only swallows AttributeError, so
            # an SDK changing the shape of `usage`, or non-numeric
            # input/output (schema drift), raised anyway and escaped to
            # the outer except, retrying against Ollama a call to
            # Claude that had ALREADY answered fine. With this, a failure here
            # only loses its own count — never the already-built text, and
            # it can never be left holding tokens from a response a later
            # fallback discards (last_usage is assigned only if `texto` exists).
            try:
                usage = getattr(resp, "usage", None)
                entrada = getattr(usage, "input_tokens", 0) or 0
                salida = getattr(usage, "output_tokens", 0) or 0
                self.last_usage = (entrada + salida) or None
            except Exception:
                log.debug("Couldn't read Claude usage; skipping token count", exc_info=True)
            return texto
        except Exception as e:
            if self.strict:
                raise
            log.error("Claude failed (%s). Falling back to Ollama.", e)
            return self._ollama(system, user)

    # --- OpenAI-compatible ---
    def _openai(self, system: str, user: str) -> str:
        base = self.cfg.get("llm.openai.base_url", "https://api.openai.com/v1")
        model = self.cfg.get("llm.openai.model", "gpt-5.6-luna")
        env_key = self.cfg.get("llm.openai.api_key_env", "OPENAI_API_KEY")
        key = os.environ.get(env_key, "")
        temp = self.cfg.get("llm.openai.temperature", 0.3)
        timeout = self.cfg.get("llm.openai.timeout", 30)
        if not key:
            if self.strict:
                # Same reason as in the except below: in probe mode, "no
                # key" is a failure of the candidate, not a signal to plug the
                # gap with Ollama.
                raise RuntimeError(f"missing {env_key}")
            log.warning("Missing %s. Falling back to Ollama.", env_key)
            return self._ollama(system, user)
        try:
            r = requests.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=openai_payload(model, system, user, temp),
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
            texto = (data["choices"][0]["message"]["content"] or "").strip()
            # Same order and same reason as in _claude: the counting runs
            # AFTER `texto` exists, and in its own try/except. `usage` is
            # optional in the protocol and its shape isn't guaranteed — a
            # provider sending a truthy non-dict value (schema drift)
            # can't throw overboard a response that did answer fine;
            # it just goes without counting its tokens.
            try:
                usage = data.get("usage") or {}
                self.last_usage = usage.get("total_tokens") or None
            except Exception:
                log.debug("Couldn't read OpenAI usage; skipping token count", exc_info=True)
            return texto
        except Exception as e:
            if self.strict:
                raise
            log.error("OpenAI failed (%s). Falling back to Ollama.", e)
            return self._ollama(system, user)


def health() -> dict:
    """Checks each backend's availability (for the menu)."""
    from .config import get_config

    cfg = get_config()
    out = {}
    # ollama
    try:
        r = requests.get(f"{cfg.get('llm.ollama.host','http://localhost:11434')}/api/tags", timeout=3)
        out["ollama"] = r.ok
    except Exception:
        out["ollama"] = False
    out["claude"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    out["openai"] = bool(os.environ.get(cfg.get("llm.openai.api_key_env", "OPENAI_API_KEY")))
    return out


class ModelNotAvailable(Exception):
    """The server responds, but the requested model isn't there."""


def export_key(selection, api_key: str | None) -> None:
    """Puts the key where the backends look for it: os.environ.

    _openai() and _claude() read the key from the environment
    (os.environ.get(env_key)), which is how it worked when it came from
    ~/.voooxly/.env. With the key in the keychain it has to be bridged here,
    or the backend never sees it and the whole flow sits there looking
    nice without working.
    """
    if not api_key:
        return
    if selection.provider.kind == "claude":
        os.environ["ANTHROPIC_API_KEY"] = api_key
    else:
        from .config import get_config

        env_key = get_config().get("llm.openai.api_key_env", "OPENAI_API_KEY")
        os.environ[env_key] = api_key


class _CandidateConfig:
    """Read-only view: real config + the values of the candidate under probe.

    Refiner only reads config via self.cfg.get(path, default), so it's enough
    to intercept here the keys the candidate changes and delegate the rest to
    the real Config. Nothing is ever written to the singleton — a failed,
    cancelled or successful validation cannot leave a trace in the running app.
    """

    def __init__(self, base_cfg, overrides: dict):
        self._base = base_cfg
        self._overrides = overrides

    def get(self, path: str, default=None):
        if path in self._overrides:
            return self._overrides[path]
        return self._base.get(path, default)


def _probe(selection, api_key: str | None, timeout: float) -> str:
    """A minimal generation through the SAME route a dictation uses.

    Doesn't touch the real config: the throwaway Refiner gets a
    _CandidateConfig that overlays only THIS candidate's keys on top of the
    real config. Also, each "kind" has its own host/base_url path: the
    openai/groq/openrouter/custom presets share kind="openai" and therefore
    llm.openai.*, while ollama has its own llm.ollama.host. Always writing
    llm.openai.base_url (as before) made an Ollama probe ignore the
    candidate's host and probe whichever one was already in config, and made
    validating ANY openai-compatible preset stomp on the config of the other
    three.
    """
    export_key(selection, api_key)
    from .config import get_config

    kind = selection.provider.kind
    overrides = {
        f"llm.{kind}.model": selection.model,
        # The user is staring at a modal dialog while this runs: the
        # requested timeout has to actually reach the backend. All three
        # backends read their timeout from config (not as a parameter).
        f"llm.{kind}.timeout": timeout,
    }
    if kind == "ollama":
        overrides["llm.ollama.host"] = selection.base_url
    elif selection.base_url:
        # Same guard as in apply_ai_selection: Claude has no base_url of its
        # own (base_url == "" by design in providers.py) and overlaying
        # llm.openai.base_url = "" here is the exact pattern that already
        # produced three bugs in this branch.
        overrides["llm.openai.base_url"] = selection.base_url

    r = Refiner.__new__(Refiner)
    r.cfg = _CandidateConfig(get_config(), overrides)
    r.backend = kind
    # Without this, a broken openai/claude candidate falls to the Ollama
    # fallback of _openai()/_claude() and, if the Ollama ALREADY CONFIGURED on
    # the user's machine answers fine (the usual case), validate() reports
    # success naming a provider that actually never replied.
    r.strict = True
    if kind == "ollama":
        return r._ollama("Reply with the single word OK.", "ping")
    if kind == "claude":
        return r._claude("Reply with the single word OK.", "ping")
    return r._openai("Reply with the single word OK.", "ping")


def _env_key_for(selection) -> str | None:
    """Environment variable that _probe (via export_key) touches for this kind.

    None for ollama: no key involved, nothing to restore.
    """
    kind = selection.provider.kind
    if kind == "claude":
        return "ANTHROPIC_API_KEY"
    if kind == "ollama":
        return None
    from .config import get_config

    return get_config().get("llm.openai.api_key_env", "OPENAI_API_KEY")


def validate(selection, api_key: str | None, timeout: float = 12.0) -> tuple[bool, str]:
    """Actually checks that the provider refines. Returns (ok, message)."""
    if selection.provider.needs_key and not api_key:
        return False, f"{selection.provider.name} needs an API key."
    if not selection.model:
        return False, f"Pick a model for {selection.provider.name}."
    # _probe() exports the candidate key to os.environ BEFORE generating (the
    # backends read it from there). If validation fails, that rejected key
    # stays in the environment and biases the next detect_backend() (its
    # cascade only checks PRESENCE of the variable, not whether the key
    # works). Snapshot + restore leaves the environment as it was on any
    # failure; on success we leave it set, because it just proved it works.
    env_key = _env_key_for(selection)
    prev = os.environ.get(env_key) if env_key else None
    had_prev = env_key is not None and env_key in os.environ

    def _restore_env():
        if not env_key:
            return
        if had_prev:
            os.environ[env_key] = prev
        else:
            os.environ.pop(env_key, None)

    try:
        salida = _probe(selection, api_key, timeout)
    except ModelNotAvailable as e:
        _restore_env()
        return False, f"Model “{selection.model}” isn't available: {e}"
    except Exception as e:
        _restore_env()
        return False, f"Couldn't reach {selection.provider.name}: {e}"
    if not (salida or "").strip():
        _restore_env()
        return False, f"{selection.provider.name} answered, but with nothing usable."
    return True, f"Connected to {selection.provider.name} using {selection.model}."
