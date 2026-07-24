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
