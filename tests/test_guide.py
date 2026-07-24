"""La guía de uso (feedback v1.6): sections() es pura y no puede mentir.

La ventana solo pinta lo que sections() decide, así que aquí se prueba lo que
importa: que la guía enseña las teclas REALES del usuario y todos los modos
del registro — no un texto congelado que se queda viejo en silencio.
"""
from voooxly import guide, modes, shortcuts


def _cuerpo(secciones, titulo_parcial):
    for titulo, cuerpo in secciones:
        if titulo_parcial in titulo:
            return cuerpo
    raise AssertionError(f"sección {titulo_parcial!r} no encontrada")


def test_la_guia_ensena_la_tecla_de_dictado_de_fabrica():
    secciones = guide.sections(None)
    dictar = _cuerpo(secciones, "Dictate")
    assert "⌘ (right)" in dictar
    assert dictar.startswith("Hold")          # estilo de fábrica: hold


def test_la_guia_ensena_la_tecla_del_usuario_no_la_de_fabrica():
    estado = {"dictation": {"keys": ["fn"], "delay_ms": 0, "style": "hold"}}
    dictar = _cuerpo(guide.sections(estado), "Dictate")
    assert "fn" in dictar
    assert "⌘" not in dictar


def test_la_guia_explica_el_estilo_toggle_si_es_el_del_usuario():
    estado = {"dictation": {"keys": ["cmd_r"], "delay_ms": 0, "style": "toggle"}}
    dictar = _cuerpo(guide.sections(estado), "Dictate")
    assert dictar.startswith("Press")
    assert "press it again" in dictar


def test_la_guia_cuenta_todos_los_modos_del_registro():
    """El "8 modes" del onboarding se quedó viejo en silencio al llegar el
    noveno: la guía saca la cuenta Y la lista del registro real."""
    secciones = guide.sections(None)
    n = len(modes.modes_by_key())
    titulo, cuerpo = next((t, c) for t, c in secciones if "modes" in t)
    assert str(n) in titulo
    for info in modes.modes_by_key().values():
        assert info["label"] in cuerpo


def test_la_guia_cubre_cancel_y_hands_free_con_sus_teclas():
    secciones = guide.sections(None)
    assert "esc" in _cuerpo(secciones, "Cancel")
    assert "⇧" in _cuerpo(secciones, "Hands-free")


def test_los_atajos_de_la_guia_pasan_por_la_tabla_unica():
    """Misma leyenda que el submenú y la ventana: si key_label cambia, la guía
    cambia con él — nunca dos formas de escribir la misma tecla."""
    estado = {"cancel": {"keys": ["esc"]}}
    assert shortcuts.key_label(["esc"]) in _cuerpo(guide.sections(estado), "Cancel")
