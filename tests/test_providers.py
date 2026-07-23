"""Catálogo de proveedores: datos puros, sin red."""

from voooxly import providers

# Lista curada del MVP: cinco proveedores, ni uno más.
ESPERADOS = ("claude", "openai", "gemini", "groq", "ollama")
# Retirados a propósito al simplificar el menú: no deben reaparecer.
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
    # Proveedores con base_url no vacía: pintar la URL exacta.
    urls = {
        "ollama": "http://localhost:11434",
        "openai": "https://api.openai.com/v1",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "groq": "https://api.groq.com/openai/v1",
    }
    for key, expected in urls.items():
        assert providers.get(key).base_url == expected, key
    # Claude gestiona su endpoint por el SDK de anthropic: base_url vacía por diseño.
    assert providers.get("claude").base_url == ""


def test_ollama_es_el_ultimo_para_de_enfatizarlo_en_el_menu():
    # El orden de inserción ES el del menú: el gratis primero, Ollama al final.
    orden = list(providers.PROVIDERS)
    assert orden[0] == "groq"
    assert orden[-1] == "ollama"


# --- modelos curados por proveedor (feedback v1.4: elegir modelo al conectar) ---

def test_cada_proveedor_cloud_trae_modelos_curados_y_el_default_es_el_primero():
    for key in ("claude", "openai", "gemini", "groq"):
        prov = providers.get(key)
        assert len(prov.models) >= 2, key
        assert prov.default_model == prov.models[0], key
        assert len(prov.models) == len(set(prov.models)), key  # sin repetidos


def test_ollama_no_presupone_modelos():
    # Sus modelos se le preguntan a SU servidor (list_ollama_models), nunca a
    # una lista fija: fijar una presupondría cuál tiene instalado el usuario.
    prov = providers.get("ollama")
    assert prov.models == ()
    assert prov.default_model == ""


def test_los_defaults_son_los_modelos_excelentes_de_la_v15():
    """Anti-regresión de la revisión de modelos (2026-07): un downgrade
    accidental del default degradaría todos los modos en silencio."""
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
    # Es el único gratis de la lista: ponerlo detrás de tres de pago hacía
    # que nadie lo encontrara, que es justo la vía más rápida para probar la
    # IA sin sacar la tarjeta.
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
