"""El sabor public.html del portapapeles DEBE declarar charset.

NSPasteboard guarda el string, pero la app receptora lee bytes: sin
`<meta charset>` el estándar HTML manda decodificar como Windows-1252 y cada
tilde UTF-8 se rompe ("ó" → "Ã³"). Pasó de verdad: un dictado en modo notas
pegado en un editor web salió con todas las tildes rotas.
"""
from voooxly import output


def test_el_sabor_html_declara_utf8_al_principio():
    flavor = output.html_flavor("<p>Micrófono</p>")
    assert flavor.startswith('<meta charset="utf-8">')
    assert "<p>Micrófono</p>" in flavor


def test_no_duplica_la_declaracion_si_ya_viene():
    ya = '<meta charset="utf-8"><p>hola</p>'
    assert output.html_flavor(ya) == ya


def test_html_vacio_se_queda_vacio():
    # copy_to_clipboard solo añade el sabor si hay html: "" debe seguir
    # siendo falsy para no escribir un sabor que solo contiene la meta.
    assert output.html_flavor("") == ""
    assert output.html_flavor(None) is None
