"""Auto-lock de idioma de dictado (es/en) por observación.

El 99% de la gente dicta siempre en el mismo idioma; detectar idioma en cada
petición cuesta ~1,1s (medido). Mientras el ajuste está en Auto, detectamos el
idioma del RESULTADO por stopwords; tras LOCK_AFTER dictados consecutivos
iguales, fijamos language= en las peticiones. Módulo puro (sin AppKit), como
shortcuts.py: la lógica delicada se prueba en pytest.
"""
from __future__ import annotations

LOCK_AFTER = 3

COMMON_ES = frozenset(
    "que de la el en y a los se del las por un para con no una su es al lo mas más como pero sus le"
    " ya o este sí si porque esta entre cuando muy sin sobre también tambien hasta hay donde quien"
    " desde todo nos durante todos uno les ni contra otros ese eso ante ellos e esto mí mi antes"
    " algunos qué unos yo otro otras otra él tanto esa estos mucho quienes nada muchos cual poco"
    " ella estar estas algunas algo nosotros tu te ti gracias hola bien hacer puede tiene".split()
)
COMMON_EN = frozenset(
    "the be to of and a in that have i it for not on with he as you do at this but his by from they"
    " we say her she or an will my one all would there their what so up out if about who get which"
    " go me when make can like time no just him know take people into year your good some could"
    " them see other than then now look only come its over think also please send thanks hello".split()
)


def _words(text) -> list[str]:
    return [w.strip(".,;:!?¿¡\"'()«»").lower() for w in (text or "").split() if w.strip()]


def detect_lang_es_en(text) -> str | None:
    """'es' o 'en' solo con señal clara; None en la duda (la duda no bloquea nada)."""
    words = _words(text)
    if len(words) < 3:
        return None
    es = sum(1 for w in words if w in COMMON_ES)
    en = sum(1 for w in words if w in COMMON_EN)
    if es >= 2 and es > en * 2:
        return "es"
    if en >= 2 and en > es * 2:
        return "en"
    return None


def update_lock(streak: list[str], detected: str | None) -> tuple[list[str], str | None]:
    """Racha de detecciones consecutivas iguales → lock al llegar a LOCK_AFTER.

    Una detección ambigua (None) no rompe la racha: el silencio no es evidencia.
    """
    if detected not in ("es", "en"):
        return (list(streak), None)
    s = list(streak)
    if s and s[-1] != detected:
        s = []
    s = (s + [detected])[-LOCK_AFTER:]
    return (s, detected if len(s) >= LOCK_AFTER else None)
