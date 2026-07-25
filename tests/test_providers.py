"""Provider catalog: pure data, no network."""

from voooxly import providers

# Curated MVP list: five providers, not one more.
ESPERADOS = ("claude", "openai", "gemini", "groq", "ollama")
# Retired on purpose when simplifying the menu: they must not reappear.
RETIRADOS = ("openrouter", "deepseek", "mistral", "together", "xai", "custom")


def test_los_presets_esperados_existen():
    for key in ESPERADOS:
        assert providers.get(key) is not None, key


def test_la_lista_esta_curada_a_cinco():
    assert set(providers.PROVIDERS) == set(ESPERADOS)


def test_los_retirados_ya_no_estan():
    for key in RETIRADOS:
        assert providers.get(key) is None, f"{key} debía quedar fuera del MVP"


def test_ollama_local_no_pide_key():
    assert providers.get("ollama").needs_key is False


def test_los_de_pago_piden_key():
    for key in ("claude", "openai", "gemini", "groq"):
        assert providers.get(key).needs_key is True, key


def test_todo_lo_que_no_es_ollama_ni_claude_usa_el_camino_openai():
    for key in ("openai", "gemini", "groq"):
        assert providers.get(key).kind == "openai", key
    assert providers.get("ollama").kind == "ollama"
    assert providers.get("claude").kind == "claude"


def test_los_presets_con_url_fija_la_traen_rellena():
    # Providers with a non-empty base_url: spell out the exact URL.
    urls = {
        "ollama": "http://localhost:11434",
        "openai": "https://api.openai.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "groq": "https://api.groq.com/openai/v1",
    }
    for key, expected in urls.items():
        assert providers.get(key).base_url == expected, key
    # Claude manages its endpoint through the anthropic SDK: empty base_url by design.
    assert providers.get("claude").base_url == ""


def test_ollama_is_last_to_emphasize_it_in_menu():
    # Insertion order IS the menu order: the free one first, Ollama last.
    orden = list(providers.PROVIDERS)
    assert orden[0] == "groq"
    assert orden[-1] == "ollama"


# --- curated models per provider (v1.4 feedback: pick model on connect) ---

def test_each_cloud_provider_brings_curated_models_and_default_is_first():
    for key in ("claude", "openai", "gemini", "groq"):
        prov = providers.get(key)
        assert len(prov.models) >= 2, key
        assert prov.default_model == prov.models[0], key
        assert len(prov.models) == len(set(prov.models)), key  # no duplicates


def test_ollama_no_presupone_modelos():
    # Its models are asked of ITS server (list_ollama_models), never taken
    # from a fixed list: fixing one would presume what the user has installed.
    prov = providers.get("ollama")
    assert prov.models == ()
    assert prov.default_model == ""


def test_los_defaults_son_los_modelos_excelentes_de_la_v15():
    """Anti-regression from the model review (2026-07): an accidental
    downgrade of the default would silently degrade every mode."""
    assert providers.get("claude").default_model == "claude-sonnet-5"
    assert providers.get("openai").default_model == "gpt-5.6-luna"
    assert providers.get("gemini").default_model == "gemini-3.6-flash"
    assert providers.get("groq").default_model == "llama-3.3-70b-versatile"


def test_proveedor_desconocido_da_none():
    assert providers.get("no-existe") is None


def test_todas_las_etiquetas_son_distintas():
    labels = [p.label for p in providers.PROVIDERS.values()]
    assert len(labels) == len(set(labels))


def test_groq_va_primero_y_dice_que_es_gratis():
    # It is the only free one on the list: putting it behind three paid ones
    # meant nobody found it, and it is precisely the fastest way to try the
    # AI without pulling out a card.
    from voooxly import providers
    assert list(providers.PROVIDERS)[0] == "groq"
    assert providers.PROVIDERS["groq"].note == "free"
    assert "free" in providers.PROVIDERS["groq"].label.lower()


def test_ollama_sigue_siendo_el_ultimo():
    from voooxly import providers
    assert list(providers.PROVIDERS)[-1] == "ollama"


def test_los_demas_proveedores_no_dicen_que_son_gratis():
    from voooxly import providers
    for k, p in providers.PROVIDERS.items():
        if k != "groq":
            assert p.note == "", f"{k} no es gratis"
