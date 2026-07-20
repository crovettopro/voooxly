"""Etiquetas del submenú AI engine."""

from voooxly import ai_settings, app, providers


def test_sin_eleccion_ninguno_sale_marcado():
    filas = app.ai_menu_labels(None)
    assert all(activo is False for _, activo in filas)


def test_el_elegido_sale_marcado_y_solo_el():
    sel = ai_settings.Selection(providers.get("groq"), "https://api.groq.com/openai/v1", "m")
    filas = app.ai_menu_labels(sel)
    activos = [etq for etq, activo in filas if activo]
    assert len(activos) == 1
    assert "Groq" in activos[0]


def test_estan_todos_los_proveedores():
    filas = app.ai_menu_labels(None)
    assert len(filas) == len(providers.PROVIDERS)


def test_todas_las_entradas_llevan_puntos_suspensivos():
    """Convención de macOS: '…' = el clic abre un diálogo. TODAS lo hacen:
    los de pago piden la key, custom pide URL/modelo, y Ollama abre el
    selector de modelos instalados."""
    for etq, _ in app.ai_menu_labels(None):
        assert etq.endswith("…"), etq


def test_titulo_con_eleccion_explicita_muestra_el_proveedor():
    """Con selección explícita el título nombra al proveedor y NO dice
    '(auto)': la elección del usuario no es una detección."""
    sel = ai_settings.Selection(providers.get("groq"), "https://api.groq.com/openai/v1", "m")
    titulo = app.ai_engine_title(sel, "")
    assert "Groq" in titulo
    assert "(auto)" not in titulo


def test_titulo_sin_eleccion_con_backend_detectado_dice_auto():
    titulo = app.ai_engine_title(None, "ollama")
    assert "Ollama" in titulo
    assert "(auto)" in titulo


def test_titulo_sin_eleccion_y_sin_backend_detectado():
    """Sin proveedor detectado, el título exacto avisa que se pega texto
    crudo: es el único indicador pasivo de este estado en todo el menú."""
    assert app.ai_engine_title(None, "none") == "AI engine — none (raw text)"


def test_titulo_siempre_empieza_por_ai_engine():
    """Pase lo que pase, el título arranca igual: así el menú sigue siendo
    reconocible aunque cambie el proveedor activo."""
    casos = [
        (None, "none"),
        (None, "ollama"),
        (ai_settings.Selection(providers.get("claude"), "", "m"), ""),
    ]
    for sel, detected in casos:
        assert app.ai_engine_title(sel, detected).startswith("AI engine")
