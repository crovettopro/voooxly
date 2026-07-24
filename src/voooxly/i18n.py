# src/voooxly/i18n.py
"""UI en español (frente B del plan): tabla EN→ES y t() de gettext-de-bolsillo.

El inglés ES la clave: el código sigue legible, el fallback es automático
(cadena sin traducir sale en inglés, jamás rompe) y no hay ficheros .po.
Sin AppKit a nivel de módulo: el idioma lo inyecta app.py al arrancar con
set_lang(resolve_lang(NSLocale.preferredLanguages())).

Las claves persistidas (ids de modos, shortcuts, prefs) NO pasan por aquí.
"""
from __future__ import annotations

_lang = "en"


def resolve_lang(preferred) -> str:
    """'es' si el primer idioma preferido es español; 'en' para todo lo demás."""
    try:
        first = str((preferred or ["en"])[0]).lower()
    except Exception:
        return "en"
    return "es" if first.startswith("es") else "en"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in ("en", "es") else "en"


def t(s: str) -> str:
    if _lang == "es":
        return ES.get(s, s)
    return s


# Cadenas del menú que test_i18n exige tener traducidas.
MENU_STRINGS = [
    "Ready", "AI engine", "Detect automatically", "Test connection",
    "Usage stats…", "Quit Voooxly", "Update available", "About Voooxly",
    "Recent", "(empty)", "Settings", "Start at login", "Sounds",
    "Add to dictionary…", "Shortcuts", "Customize…", "Search history…",
    "How to use Voooxly…", "Correct last dictation…",
    # --- estado de la barra de menú (_refresh_title) ---
    "Mode", "ready", "recording", "processing",
    # --- botones del diálogo de quit-to-install ---
    "Quit now", "Not yet",
]

ES = {
    # --- menú ---
    "Ready": "Listo",
    "AI engine": "Motor de IA",
    "Detect automatically": "Detectar automáticamente",
    "Test connection": "Probar conexión",
    "Usage stats…": "Estadísticas de uso…",
    "Quit Voooxly": "Salir de Voooxly",
    "Update available": "Actualización disponible",
    "About Voooxly": "Acerca de Voooxly",
    "Recent": "Recientes",
    "(empty)": "(vacío)",
    "Settings": "Ajustes",
    "Start at login": "Abrir al iniciar sesión",
    "Sounds": "Sonidos",
    "Add to dictionary…": "Añadir al diccionario…",
    "Shortcuts": "Atajos",
    "Customize…": "Personalizar…",
    "Search history…": "Buscar en el historial…",
    "How to use Voooxly…": "Cómo usar Voooxly…",
    "Correct last dictation…": "Corregir el último dictado…",
    # --- estado de la barra de menú (_refresh_title) ---
    "Mode": "Modo",
    "ready": "listo",
    "recording": "grabando",
    "processing": "procesando",
    # --- updates ---
    "Update downloaded": "Actualización descargada",
    "Install and relaunch": "Instalar y reabrir",
    "Later": "Más tarde",
    "Download now": "Descargar ahora",
    "Quit now": "Salir ahora",
    "Not yet": "Todavía no",
    "Correct last dictation": "Corregir el último dictado",
    "Learn & copy": "Aprender y copiar",
    "Cancel": "Cancelar",
    # "What's new" en run(): prefijo del título, la versión va aparte.
    "What's new in Voooxly": "Novedades de Voooxly",
    # --- diálogos frecuentes ---
    "Nothing to correct": "Nada que corregir",
    "Dictate something first.": "Dicta algo primero.",
    "Add to dictionary": "Añadir al diccionario",
    "Add": "Añadir",
}
