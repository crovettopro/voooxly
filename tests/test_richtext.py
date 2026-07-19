"""markdown_to_html cubre EXACTAMENTE lo que emiten los modos: ##/###, bullets,
numeradas, checkboxes, `code` y ** residual. Y nunca deja HTML sin escapar.
"""
from dictador import modes, richtext


def test_titulos_y_bullets():
    html = richtext.markdown_to_html(
        "## Organización\n\n### Calendario\n- Sprint: lunes\n- Review: viernes"
    )
    assert "<h2>Organización</h2>" in html
    assert "<h3>Calendario</h3>" in html
    assert "<ul>" in html and "<li>Sprint: lunes</li>" in html
    assert html.index("<h3>") < html.index("<ul>")


def test_lista_numerada_y_cierre():
    html = richtext.markdown_to_html("1. uno\n2. dos\n\npárrafo")
    assert "<ol>" in html and "</ol>" in html
    assert "<li>dos</li>" in html
    assert "<p>párrafo</p>" in html
    assert html.index("</ol>") < html.index("<p>")


def test_checkboxes():
    html = richtext.markdown_to_html("- [ ] pendiente\n- [x] hecha")
    assert "☐ pendiente" in html
    assert "☑ hecha" in html


def test_inline_bold_y_code():
    html = richtext.markdown_to_html("usa **ESLAC** y `git push`")
    assert "<b>ESLAC</b>" in html
    assert "<code>git push</code>" in html


def test_escapa_html():
    html = richtext.markdown_to_html("- riesgo <script>alert(1)</script> & más")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp; más" in html


def test_prosa_sin_markdown_sale_como_parrafos():
    html = richtext.markdown_to_html("Hola equipo.\n\nNos vemos el lunes.")
    assert html == "<p>Hola equipo.</p>\n<p>Nos vemos el lunes.</p>"


def test_cambio_de_ul_a_ol_cierra_la_anterior():
    html = richtext.markdown_to_html("- a\n1. b")
    assert "</ul>" in html and "<ol>" in html
    assert html.index("</ul>") < html.index("<ol>")


def test_vacio_no_rompe():
    assert richtext.markdown_to_html("") == ""
    assert richtext.markdown_to_html(None) == ""


# --- qué modos pegan rico ---

def test_rich_paste_solo_en_modos_con_estructura():
    ricos = {k for k, v in modes.MODES.items() if v.get("rich_paste")}
    assert ricos == {"notas", "resumir"}
