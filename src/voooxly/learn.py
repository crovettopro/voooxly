"""Aprender del usuario: qué corrigió sobre un dictado y qué merece el diccionario.

Módulo puro (sin AppKit) por el mismo motivo que shortcuts.py: la lógica
delicada se prueba en pytest; app.py solo pega la ventana.

El sesgo es deliberado: PRECISIÓN sobre exhaustividad. Un reemplazo
aprendido de más corrompe todos los dictados futuros (dictionary.apply es
global y case-insensitive); uno aprendido de menos solo cuesta repetir la
corrección a mano. Por eso solo se aprende de sustituciones cortas
(1 palabra mal → 1-2 bien) y nunca de borrados, inserciones o reescrituras.
"""
from __future__ import annotations

import difflib
import re

# Máx. palabras a cada lado de una sustitución para considerarla "grafía
# corregida" y no "frase reescrita". 1→2 cubre "wisperflow" → "Wispr Flow".
_MAX_WRONG = 1
_MAX_RIGHT = 2


def _words(text: str) -> list[str]:
    return [w for w in (text or "").split() if w]


def _strip_punct(w: str) -> str:
    return re.sub(r"^\W+|\W+$", "", w, flags=re.UNICODE)


def corrections(original: str, corrected: str) -> list[tuple[str, str]]:
    """Pares (mal, bien) que el usuario corrigió, aptos como reemplazos.

    Solo opcodes 'replace' cortos del SequenceMatcher sobre palabras; los
    bordes de puntuación se recortan para que "hola," vs "hola" no cuente.
    """
    a, b = _words(original), _words(corrected)
    if not a or not b:
        return []
    fuera: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag != "replace":
            continue
        if (i2 - i1) > _MAX_WRONG or (j2 - j1) > _MAX_RIGHT:
            continue
        wrong = _strip_punct(" ".join(a[i1:i2]))
        right = _strip_punct(" ".join(b[j1:j2]))
        if not wrong or not right:
            continue
        # Cambio solo de puntuación: tras recortar bordes quedan iguales.
        if wrong == right:
            continue
        fuera.append((wrong, right))
    return fuera
