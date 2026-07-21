"""Catálogo de teclas de dictado y su validación.

Un módulo de datos, sin AppKit, por el mismo motivo que existe ai_settings.py:
instanciar VoooxlyApp construye menús y no se puede hacer en un test. Aquí vive
toda la lógica que se puede verificar; app.py solo cablea el menú.

La validación es la parte importante. Elegir mal la tecla de dictado no es un
detalle de configuración: inutiliza el teclado. Con "a" de tecla de dictado
dejas de poder escribir la letra a en todo el sistema, y para arreglarlo hay
que editar prefs.json a mano — cosa que el usuario que necesita este menú no
sabe hacer.

GUARDA (guard=True): los modificadores IZQUIERDOS se usan constantemente en
combos (⌘C, ⌘V, ⌘S, ⌘Tab). En modo hold, hotkey.py dispara on_start() al caer
la tecla, así que sin guarda cada ⌘C arrancaría una grabación. Con guarda, la
grabación solo empieza si mantienes la tecla SOLA ~300ms. Las derechas no la
llevan: casi nadie hace combos con ellas, la ruta actual ya está en producción
y dársela costaría 300ms de latencia a todo el mundo para arreglar un problema
que solo tienen las izquierdas.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_KEY = "cmd_r"
DEFAULT_MODE = "hold"

# Modo del botón de dictado. El texto es el que se ve en el menú.
MODES: dict[str, str] = {
    "hold": "Hold to talk",
    "toggle": "Press to start / stop",
}

# Prefijos de los modificadores: se usan en combos, así que necesitan guarda.
_MODIFICADORES = ("cmd", "alt", "ctrl")

# Los modificadores con lado que pynput conoce de verdad. Se listan enteros en
# vez de deducirlos con un sufijo "_l"/"_r" porque alt_gr no lo cumple y la
# deducción generaba mensajes de error absurdos ("prueba alt__r").
_MODIFICADORES_CON_LADO = {
    "cmd_l", "cmd_r", "alt_l", "alt_r", "alt_gr", "ctrl_l", "ctrl_r",
}

# Teclas con dueño: no se pueden reasignar a dictado sin dejar la app coja.
_RESERVADAS = {"esc", "shift", "shift_l", "shift_r"}

# Nombres de pynput que aceptamos fuera del catálogo (entrada "Custom…").
# Las funciones llegan hasta f20 en pynput.
_FUNCIONES = {f"f{i}" for i in range(1, 21)}


@dataclass(frozen=True)
class DictationKey:
    name: str    # nombre pynput
    label: str   # etiqueta del menú
    guard: bool  # ¿necesita ventana de decisión?


# El orden es el del menú (orden de inserción): las derechas primero porque son
# las recomendadas, las izquierdas después con el retardo escrito en la propia
# etiqueta, y las funciones al final para quien tenga un teclado grande.
DICTATION_KEYS: dict[str, DictationKey] = {
    "cmd_r": DictationKey("cmd_r", "Right ⌘ (Command)", False),
    "alt_r": DictationKey("alt_r", "Right ⌥ (Option)", False),
    "ctrl_r": DictationKey("ctrl_r", "Right ⌃ (Control)", False),
    "cmd_l": DictationKey("cmd_l", "Left ⌘ (Command) — 300 ms delay", True),
    "alt_l": DictationKey("alt_l", "Left ⌥ (Option) — 300 ms delay", True),
    "ctrl_l": DictationKey("ctrl_l", "Left ⌃ (Control) — 300 ms delay", True),
    "f6": DictationKey("f6", "F6", False),
    "f13": DictationKey("f13", "F13", False),
    "f14": DictationKey("f14", "F14", False),
    "f15": DictationKey("f15", "F15", False),
}


def get(name: str) -> DictationKey | None:
    return DICTATION_KEYS.get(name)


def needs_guard(name: str) -> bool:
    """¿Esta tecla necesita ventana de decisión antes de empezar a grabar?

    Las del catálogo lo llevan escrito. Una custom la necesita si es un
    modificador (se usa en combos); una función o una multimedia, no.
    """
    k = get(name)
    if k is not None:
        return k.guard
    return _es_modificador(name)


def _es_modificador(name: str) -> bool:
    return any(name.startswith(p) for p in _MODIFICADORES)


def validate_custom(name: str) -> tuple[bool, str]:
    """¿Sirve `name` como tecla de dictado? Devuelve (ok, mensaje).

    El mensaje de error dice qué está mal Y cómo arreglarlo: quien llega aquí
    es justo el usuario que no sabe qué es un "nombre de tecla de pynput".
    """
    name = (name or "").strip().lower()
    if not name:
        return False, "Type a key name, for example f13 or alt_r."
    if name in DICTATION_KEYS:
        return True, ""
    if len(name) == 1:
        return False, (
            f'"{name}" is a single character — using it for dictation would stop '
            f'you typing "{name}" anywhere on your Mac. Try f13 or alt_r.'
        )
    if name in _RESERVADAS:
        dueno = "cancel a dictation" if name.startswith("esc") else "latch a long dictation"
        return False, f'"{name}" is already used to {dueno}. Pick another key.'
    if name in _MODIFICADORES:
        return False, (
            f'"{name}" would match both the left and the right key. '
            f"Pick a side: {name}_l or {name}_r."
        )
    if name in _MODIFICADORES_CON_LADO or name in _FUNCIONES:
        return True, ""
    return False, (
        f'"{name}" isn\'t a key pynput knows, so it would never fire. '
        f"Try f13, f18 or alt_r."
    )


def resolve(prefs: dict, cfg) -> tuple[str, str, bool]:
    """(tecla, modo, guarda) efectivos: prefs del usuario por encima del YAML.

    Mismo patrón que `sounds` en app.py — config.yaml es el valor de fábrica y
    lo que eligió el usuario manda. Unos prefs corruptos (una lista, un número,
    una tecla retirada en una versión posterior) no pueden dejar la app sin
    hotkey: se ignoran y se cae al YAML.
    """
    del_yaml = cfg.get("hotkeys.toggle", [DEFAULT_KEY]) or [DEFAULT_KEY]
    tecla = del_yaml[0]
    guardada = prefs.get("dictation_key")
    if isinstance(guardada, str) and validate_custom(guardada)[0]:
        tecla = guardada

    modo = cfg.get("hotkeys.toggle_mode", DEFAULT_MODE)
    modo_guardado = prefs.get("dictation_mode")
    if isinstance(modo_guardado, str) and modo_guardado in MODES:
        modo = modo_guardado
    if modo not in MODES:
        modo = DEFAULT_MODE

    return tecla, modo, needs_guard(tecla)
