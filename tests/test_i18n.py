# tests/test_i18n.py
"""t() traduce la UI sin tocar claves persistidas ni romper con idiomas raros."""
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
    # Las cadenas del menú que el usuario ve SIEMPRE deben tener traducción:
    # si alguien añade un ítem y olvida traducirlo, este test lo caza.
    for s in i18n.MENU_STRINGS:
        assert s in i18n.ES, f"Falta traducción de: {s!r}"


def test_traduce_estado_de_la_barra_de_menu():
    # _refresh_title compone "Mode: <label> · <state>" — el prefijo y las
    # palabras de estado deben pasar por t() (hallazgo de revisión #1).
    i18n.set_lang("es")
    try:
        assert i18n.t("Mode") == "Modo"
        assert i18n.t("ready") == "listo"
        assert i18n.t("recording") == "grabando"
        assert i18n.t("processing") == "procesando"
    finally:
        i18n.set_lang("en")


def test_traduce_botones_de_quit_to_install():
    # _offer_quit_to_install pasaba ok/cancel en crudo (hallazgo de revisión #3).
    i18n.set_lang("es")
    try:
        assert i18n.t("Quit now") == "Salir ahora"
        assert i18n.t("Not yet") == "Todavía no"
    finally:
        i18n.set_lang("en")


def test_traduce_dialogo_de_correct_last():
    # _correct_last pasaba el cuerpo del diálogo en crudo (hallazgo de
    # revisión final #2): el título ya se traducía, el mensaje no.
    i18n.set_lang("es")
    try:
        assert i18n.t(
            "Fix any misheard words — Voooxly learns the right "
            "spelling for next time:"
        ) == "Corrige lo que haya oído mal — Voooxly aprende la grafía correcta para la próxima:"
    finally:
        i18n.set_lang("en")


def test_traduce_dialogos_de_search_history():
    # _search_history mezclaba español (título del submenú) con inglés (la
    # ventana y sus alerts) — hallazgo de revisión final #2.
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
    # Hallazgo de revisión final #3: "Not added", check_now_message() y el
    # ítem dinámico de menú "Update to {ver} →" quedaban en inglés.
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
    # Una clave repetida en el dict literal no rompe en tiempo de ejecución
    # (la última asignación gana en silencio) pero esconde una traducción
    # muerta o, peor, dos valores distintos donde solo uno se aplica
    # (hallazgo de revisión #3). Se parsea el .py con ast en vez de leer
    # i18n.ES en memoria porque el objeto ya deduplicado no puede delatarlo.
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
