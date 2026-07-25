"""The usage guide (v1.6 feedback): sections() is pure and cannot lie.

The window only renders what sections() decides, so what matters is tested
here: that the guide shows the user's REAL keys and every mode in the
registry — not a frozen text that silently goes stale.
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
    assert dictar.startswith("Hold")          # factory style: hold


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
    """The onboarding's "8 modes" silently went stale when the ninth
    arrived: the guide takes the count AND the list from the real registry."""
    secciones = guide.sections(None)
    n = len(modes.modes_by_key())
    titulo, cuerpo = next((t, c) for t, c in secciones if "modes" in t)
    assert str(n) in titulo
    for info in modes.modes_by_key().values():
        assert info["label"] in cuerpo


def test_guide_covers_cancel_and_hands_free_with_their_keys():
    secciones = guide.sections(None)
    assert "esc" in _cuerpo(secciones, "Cancel")
    assert "⇧" in _cuerpo(secciones, "Hands-free")


def test_los_atajos_de_la_guia_pasan_por_la_tabla_unica():
    """Same legend as the submenu and the window: if key_label changes, the
    guide changes with it — never two ways of writing the same key."""
    estado = {"cancel": {"keys": ["esc"]}}
    assert shortcuts.key_label(["esc"]) in _cuerpo(guide.sections(estado), "Cancel")


def test_guide_shows_in_spanish_when_appropriate():
    from voooxly import i18n

    i18n.set_lang("es")
    try:
        titulos = [t for t, _ in guide.sections(None)]
        assert "Dicta en cualquier sitio" in titulos
    finally:
        i18n.set_lang("en")


def test_the_guide_explains_that_corrections_are_read_and_learned():
    """The window reads the focused field for seconds after pasting. The guide
    is where the user finds out, in their own language, without opening the
    README — and where the opt-out is named."""
    from voooxly import i18n

    i18n.set_lang("es")
    try:
        cuerpos = {t: c for t, c in guide.sections(None)}
        cuerpo = cuerpos["Aprende de tus correcciones"]
        assert "Ajustes" in cuerpo
    finally:
        i18n.set_lang("en")


def test_la_guia_sale_en_espanol_los_nueve_titulos():
    """Not just the first title (review finding #2): if a new title sneaks
    in without going through t(), or an old one loses its translation, this
    catches it. '{n} modos' is built the same way as sections(): with the
    registry's dynamic count, not a frozen number."""
    from voooxly import i18n

    i18n.set_lang("es")
    try:
        n = len(modes.modes_by_key())
        titulos = [t for t, _ in guide.sections(None)]
        assert titulos == [
            "Dicta en cualquier sitio",
            "Manos libres",
            "Cancelar",
            f"{n} modos",
            "Motor de IA",
            "Historial",
            "Diccionario personal",
            "Aprende de tus correcciones",
            "Hazla tuya",
            "Actualizaciones",
        ]
    finally:
        i18n.set_lang("en")
