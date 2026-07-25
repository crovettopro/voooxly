"""apply_ai_selection(): the LIVE config left after choosing/restoring an
AI provider. It lives at module level (just like ai_menu_labels/
ai_engine_title) precisely so it can be tested without instantiating
VoooxlyApp (AppKit does not run under pytest)."""

from voooxly import ai_settings, app, providers


class _FakeCfg:
    """Fake config that only records the _set_path calls, without writing
    anything for real."""

    def __init__(self):
        self.escrituras: dict[str, object] = {}

    def _set_path(self, path, value):
        self.escrituras[path] = value


def test_claude_no_pisa_llm_openai_base_url():
    """Finding 1: Claude has base_url == "" by design (the anthropic SDK
    manages its own endpoint). Connecting Claude cannot leave
    llm.openai.base_url = "" in the live config, or it breaks the
    OpenAI-compatible path until the next openai-kind provider is connected."""
    sel = ai_settings.Selection(providers.get("claude"), "", "claude-sonnet-5")
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, sel)

    assert "llm.openai.base_url" not in cfg.escrituras
    assert cfg.escrituras["llm.backend"] == "claude"
    assert cfg.escrituras["llm.claude.model"] == "claude-sonnet-5"


def test_ollama_escribe_su_propio_host_nunca_openai_base_url():
    sel = ai_settings.Selection(providers.get("ollama"), "http://localhost:11434", "llama3.2")
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, sel)

    assert cfg.escrituras["llm.ollama.host"] == "http://localhost:11434"
    assert cfg.escrituras["llm.ollama.model"] == "llama3.2"
    assert "llm.openai.base_url" not in cfg.escrituras


def test_groq_openai_kind_with_real_base_url_writes_through():
    """Groq is kind="openai" with a real base_url (not empty like
    Claude): that one MUST reach llm.openai.base_url, exactly as-is."""
    sel = ai_settings.Selection(
        providers.get("groq"), "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"
    )
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, sel)

    assert cfg.escrituras["llm.openai.base_url"] == "https://api.groq.com/openai/v1"
    assert cfg.escrituras["llm.openai.model"] == "llama-3.3-70b-versatile"
    assert cfg.escrituras["llm.backend"] == "openai"


def test_sel_none_writes_nothing():
    cfg = _FakeCfg()

    app.apply_ai_selection(cfg, None)

    assert cfg.escrituras == {}
