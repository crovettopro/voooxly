"""Provider choice persisted in prefs.json."""

from voooxly import ai_settings, providers


def test_sin_eleccion_previa_devuelve_none():
    assert ai_settings.load({}) is None


def test_save_and_restore_choice():
    prefs = ai_settings.save({}, "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
    sel = ai_settings.load(prefs)
    assert sel.provider.key == "groq"
    assert sel.model == "llama-3.3-70b-versatile"
    assert sel.base_url == "https://api.groq.com/openai/v1"


def test_guardar_no_pisa_otras_preferencias():
    prefs = ai_settings.save({"sounds": False}, "openai", "https://api.openai.com/v1", "gpt-4o-mini")
    assert prefs["sounds"] is False


def test_guardar_no_modifica_el_dict_del_llamador():
    """save() must not mutate the caller's original dict."""
    original = {"sounds": False, "other": "value"}
    ai_settings.save(original, "openai", "https://api.openai.com/v1", "gpt-4o-mini")
    # The original dict must not contain the provider keys
    assert ai_settings.CLAVE_PROVEEDOR not in original
    assert ai_settings.CLAVE_BASE_URL not in original
    assert ai_settings.CLAVE_MODELO not in original
    # But it keeps its own keys
    assert original["sounds"] is False
    assert original["other"] == "value"


def test_al_guardar_sin_url_ni_modelo_se_usan_los_del_preset():
    prefs = ai_settings.save({}, "openai", "", "")
    sel = ai_settings.load(prefs)
    assert sel.base_url == "https://api.openai.com/v1"
    # The preset's default, whatever the current model revision is: what
    # this test watches is the FALLBACK to the preset, not a specific model.
    assert sel.model == providers.get("openai").default_model


def test_saved_provider_that_no_longer_exists_is_ignored():
    """If a future version retires a preset, the app cannot blow up at launch."""
    assert ai_settings.load({"ai_provider": "proveedor-retirado"}) is None


def test_saving_unknown_provider_raises():
    import pytest

    with pytest.raises(ValueError):
        ai_settings.save({}, "no-existe", "", "")


def test_cargar_con_proveedor_no_string_devuelve_none():
    """If prefs.json gets corrupted and ai_provider is a list or another type, load() returns None.

    This prevents the app from dying at launch because of a corrupt file.
    """
    # Prefs with ai_provider as a list (simulated corruption)
    prefs = {"ai_provider": ["ollama"], "other": "data"}
    assert ai_settings.load(prefs) is None
    # But it does not damage the dict
    assert prefs == {"ai_provider": ["ollama"], "other": "data"}


def test_cargar_con_proveedor_dict_devuelve_none():
    """Another corrupt non-string type is tolerated too."""
    prefs = {"ai_provider": {"nested": "dict"}}
    assert ai_settings.load(prefs) is None


def test_save_solo_persiste_la_whitelist_y_nunca_material_de_key():
    """Lock on the spec criterion: no API key in any file under
    ~/.voooxly/. save() is the provider choice's only gateway into
    prefs.json: its output must be EXACTLY the known whitelist (the three
    CLAVE_*) plus whatever already came in the input dict, and no value may
    be key material — in fact save()'s signature cannot even receive it,
    which is what this test documents with the sentinel.
    """
    SECRETO_CENTINELA = "sk-CENTINELA-que-jamas-se-pasa-a-save"
    prefs = ai_settings.save({}, "groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile")
    assert set(prefs) == {
        ai_settings.CLAVE_PROVEEDOR,
        ai_settings.CLAVE_BASE_URL,
        ai_settings.CLAVE_MODELO,
    }
    assert all(v != SECRETO_CENTINELA for v in prefs.values())
