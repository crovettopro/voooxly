# tests/test_i18n.py
"""t() translates the UI without touching persisted keys or breaking on odd languages."""
import ast
from pathlib import Path

from voooxly import i18n


def test_resolve_lang_detecta_espanol():
    assert i18n.resolve_lang(["es-ES", "en"]) == "es"
    assert i18n.resolve_lang(["es-419"]) == "es"


def test_resolve_lang_cae_a_ingles():
    assert i18n.resolve_lang(["en-US"]) == "en"
    assert i18n.resolve_lang(["fr-FR", "de"]) == "en"
    assert i18n.resolve_lang([]) == "en"
    assert i18n.resolve_lang(None) == "en"


def test_t_es_identidad_en_ingles():
    i18n.set_lang("en")
    assert i18n.t("Quit Voooxly") == "Quit Voooxly"


def test_t_traduce_en_espanol():
    i18n.set_lang("es")
    try:
        assert i18n.t("Quit Voooxly") == "Salir de Voooxly"
        assert i18n.t("Recent") == "Recientes"
    finally:
        i18n.set_lang("en")


def test_t_devuelve_la_clave_si_no_hay_traduccion():
    i18n.set_lang("es")
    try:
        assert i18n.t("String sin traducir 12345") == "String sin traducir 12345"
    finally:
        i18n.set_lang("en")


def test_las_traducciones_cubren_el_menu_principal():
    # Menu strings the user sees must ALWAYS have a translation: if someone
    # adds an item and forgets to translate it, this test catches it.
    for s in i18n.MENU_STRINGS:
        assert s in i18n.ES, f"Falta traducción de: {s!r}"


def test_translates_menu_bar_state():
    # _refresh_title composes "Mode: <label> · <state>" — the prefix and the
    # state words must go through t() (review finding #1).
    i18n.set_lang("es")
    try:
        assert i18n.t("Mode") == "Modo"
        assert i18n.t("ready") == "listo"
        assert i18n.t("recording") == "grabando"
        assert i18n.t("processing") == "procesando"
    finally:
        i18n.set_lang("en")


def test_translates_language_submenu():
    # The dictation language submenu (langlock auto-lock) comes out translated.
    i18n.set_lang("es")
    try:
        assert i18n.t("Dictation language") == "Idioma de dictado"
        assert i18n.t("Auto") == "Automático"
    finally:
        i18n.set_lang("en")


def test_traduce_el_aviso_de_auto_learn():
    # The auto-learn HUD is the deliberate exception to "HUDs in English":
    # it is the feature's transparency notice.
    i18n.set_lang("es")
    try:
        assert i18n.t("Learn from my corrections") == "Aprender de mis correcciones"
        assert i18n.t("✨ Learned") == "✨ Aprendido"
        assert i18n.t("Turn off in Settings if you prefer.") == "Desactívalo en Ajustes si lo prefieres."
    finally:
        i18n.set_lang("en")


def test_traduce_botones_de_quit_to_install():
    # _offer_quit_to_install passed ok/cancel raw (review finding #3).
    i18n.set_lang("es")
    try:
        assert i18n.t("Quit now") == "Salir ahora"
        assert i18n.t("Not yet") == "Todavía no"
    finally:
        i18n.set_lang("en")


def test_traduce_dialogo_de_correct_last():
    # _correct_last passed the dialog body raw (final review finding #2):
    # the title was already translated, the message was not.
    i18n.set_lang("es")
    try:
        assert i18n.t(
            "Fix any misheard words — Voooxly learns the right "
            "spelling for next time:"
        ) == "Corrige lo que haya oído mal — Voooxly aprende la grafía correcta para la próxima:"
    finally:
        i18n.set_lang("en")


def test_traduce_dialogos_de_search_history():
    # _search_history mixed Spanish (the submenu title) with English (the
    # window and its alerts) — final review finding #2.
    i18n.set_lang("es")
    try:
        assert i18n.t("Search history") == "Buscar en el historial"
        assert i18n.t("Find past dictations containing:") == "Busca dictados anteriores que contengan:"
        assert i18n.t("Search") == "Buscar"
        assert i18n.t("History is off") == "Historial desactivado"
        assert i18n.t("Set app.save_history: true in config.yaml to keep dictations.") == (
            "Activa app.save_history: true en config.yaml para guardar los dictados."
        )
        assert i18n.t("No matches") == "Sin resultados"
        assert i18n.t('Nothing matches "{query}".').format(query="foo") == 'Nada coincide con "foo".'
        assert i18n.t("{n} match(es)").format(n=3) == "3 resultado(s)"
        assert i18n.t("They're in the Recent submenu — click one to copy it.") == (
            "Están en el submenú Recientes — haz clic en uno para copiarlo."
        )
    finally:
        i18n.set_lang("en")


def test_traduce_not_added_y_updates():
    # Final review finding #3: "Not added", check_now_message() and the
    # dynamic menu item "Update to {ver} →" stayed in English.
    i18n.set_lang("es")
    try:
        assert i18n.t("Not added") == "No añadido"
        assert i18n.t("Up to date") == "Actualizado"
        assert i18n.t("Couldn't check") == "No se pudo comprobar"
        assert i18n.t("Voooxly {ver} is available.").format(ver="1.9.0") == "Voooxly 1.9.0 está disponible."
        assert i18n.t("You're running the latest version (Voooxly {local}).").format(local="1.8.0") == (
            "Tienes la última versión (Voooxly 1.8.0)."
        )
        assert i18n.t("Couldn't reach the update server. Try again later.") == (
            "No se pudo contactar con el servidor de actualizaciones. Inténtalo más tarde."
        )
        assert i18n.t("Check for updates…") == "Comprobar actualizaciones…"
        assert i18n.t("Update to {ver} →").format(ver="1.9.0") == "Actualizar a 1.9.0 →"
    finally:
        i18n.set_lang("en")


def test_el_literal_de_ES_no_tiene_claves_duplicadas():
    # A repeated key in the dict literal does not break at runtime (the
    # last assignment silently wins) but it hides a dead translation or,
    # worse, two different values where only one applies (review finding
    # #3). The .py is parsed with ast instead of reading i18n.ES in memory
    # because the already-deduplicated object cannot give it away.
    src = Path(i18n.__file__).read_text()
    tree = ast.parse(src)
    es_dict = next(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "ES" for target in node.targets)
    )
    keys = [k.value for k in es_dict.keys if isinstance(k, ast.Constant)]
    dupes = {k for k in keys if keys.count(k) > 1}
    assert not dupes, f"claves duplicadas en ES: {dupes}"
