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

    # --- guía ("How to use Voooxly…") ---
    "How to use Voooxly": "Cómo usar Voooxly",
    "Everything the menu bar mic can do.": "Todo lo que puede hacer el micrófono de la barra de menú.",
    "Dictate anywhere": "Dicta en cualquier sitio",
    "Hold {key}, speak, then release — your words get typed right where "
    "the cursor is, in any app.":
        "Mantén pulsado {key}, habla y suelta — el texto aparece justo "
        "donde esté el cursor, en cualquier app.",
    "Press {key} to start, speak, then press it again — your words get "
    "typed right where the cursor is, in any app.":
        "Pulsa {key} para empezar, habla y vuelve a pulsarlo — el texto "
        "aparece justo donde esté el cursor, en cualquier app.",
    "Hands-free": "Manos libres",
    "While dictating, tap {latch} to lock the recording and let go. Talk "
    "as long as you like; tap {dic} to finish.":
        "Mientras dictas, toca {latch} para bloquear la grabación y "
        "soltar. Habla todo lo que quieras; toca {dic} para terminar.",
    "Press {key} while dictating to throw it away — nothing gets pasted.":
        "Pulsa {key} mientras dictas para descartarlo — no se pega nada.",
    "{n} modes": "{n} modos",
    "A mode decides how your speech is rewritten before it's typed. "
    "Press {key} to cycle modes, or pick one at the top of the menu:":
        "Un modo decide cómo se reescribe lo que dices antes de "
        "escribirlo. Pulsa {key} para cambiar de modo, o elige uno "
        "arriba del todo del menú:",
    "Connect Claude, ChatGPT, Gemini or a local Ollama (menu › AI engine) "
    "and Voooxly cleans up, formats and rewrites what you say. Without AI "
    "you still get accurate word-for-word dictation.":
        "Conecta Claude, ChatGPT, Gemini o un Ollama local (menú › Motor "
        "de IA) y Voooxly limpia, da formato y reescribe lo que dices. "
        "Sin IA sigues teniendo un dictado literal y preciso.",
    "History": "Historial",
    "Recent keeps your last dictations — click one to copy it again. "
    "Search history… finds anything you ever dictated.":
        "Recientes guarda tus últimos dictados — haz clic en uno para "
        "copiarlo de nuevo. Buscar en el historial… encuentra cualquier "
        "cosa que hayas dictado alguna vez.",
    "Personal dictionary": "Diccionario personal",
    "Add names, brands or jargon (menu › Settings › Add to dictionary…) "
    "and Voooxly learns to spell them your way.":
        "Añade nombres, marcas o jerga (menú › Ajustes › Añadir al "
        "diccionario…) y Voooxly aprende a escribirlos como tú quieres.",
    "Make it yours": "Hazla tuya",
    "Every shortcut above can be changed: menu › Shortcuts › Customize…. "
    "Start at login, sounds and the rest live under Settings.":
        "Todos los atajos de arriba se pueden cambiar: menú › Atajos › "
        "Personalizar…. Abrir al iniciar sesión, sonidos y el resto "
        "viven en Ajustes.",
    "Updates": "Actualizaciones",
    "Voooxly checks for updates daily and installs them itself — after "
    "each one, a What's new note tells you what changed.":
        "Voooxly busca actualizaciones a diario y las instala sola — "
        "después de cada una, una nota de Novedades te cuenta qué cambió.",

    # --- onboarding ---
    "Welcome to Voooxly": "Bienvenido a Voooxly",
    "Dictate anywhere — Voooxly types what you say.":
        "Dicta en cualquier sitio — Voooxly escribe lo que dices.",
    "A COUPLE OF ONE-TIME STEPS": "UN PAR DE PASOS, SOLO UNA VEZ",
    "Microphone": "Micrófono",
    "So Voooxly can hear you. Your voice never leaves this Mac.":
        "Para que Voooxly pueda oírte. Tu voz nunca sale de este Mac.",
    "Allow": "Permitir",
    "Accessibility": "Accesibilidad",
    "Lets Voooxly type into any app and use the dictation hotkey.":
        "Deja que Voooxly escriba en cualquier app y use el atajo de "
        "dictado.",
    "Open Settings": "Abrir Ajustes",
    "Speech model": "Modelo de voz",
    "One-time 547 MB download. Runs fully offline after that.":
        "Descarga única de 547 MB. Después funciona totalmente sin "
        "conexión.",
    "Download": "Descargar",
    "Downloading…": "Descargando…",
    "Optional": "Opcional",
    "Connect AI": "Conectar IA",
    "Optional, but it makes Voooxly more than a dictation tool: connect "
    "Claude, ChatGPT or Gemini and it cleans up, formats and rewrites "
    "what you say. You can also add it later from the menu bar.":
        "Opcional, pero convierte a Voooxly en algo más que una "
        "herramienta de dictado: conecta Claude, ChatGPT o Gemini y "
        "limpia, da formato y reescribe lo que dices. También puedes "
        "añadirlo más tarde desde la barra de menú.",
    "Takes about 2 minutes. You can change any of this later from the "
    "menu bar (🎙 icon).":
        "Lleva unos 2 minutos. Puedes cambiar todo esto más tarde desde "
        "la barra de menú (icono 🎙).",
    "Continue →": "Continuar →",
    "STEP 1 OF 2": "PASO 1 DE 2",
    "STEP 2 OF 2": "PASO 2 DE 2",
    "You're ready to dictate": "Listo para dictar",
    "Two keys are all you need.": "Solo necesitas dos teclas.",
    "Hold the RIGHT ⌘ key": "Mantén pulsada la tecla ⌘ derecha",
    "speak, then release — your words get typed where the cursor is.":
        "habla y suelta — el texto aparece donde esté el cursor.",
    "Change mode": "Cambiar de modo",
    "Toggle dictation on/off without holding.":
        "Activa o desactiva el dictado sin mantener pulsado.",
    "Cycle {n} modes (verbatim, email, code…).":
        "Recorre {n} modos (literal, email, código…).",
    "Throw away the dictation in progress.":
        "Descarta el dictado en curso.",
    "Prefer another key? Change it whenever you like from the menu bar "
    "icon › Shortcuts › Customize…":
        "¿Prefieres otra tecla? Cámbiala cuando quieras desde el icono "
        "de la barra de menú › Atajos › Personalizar…",
    "Start dictating": "Empezar a dictar",
}
