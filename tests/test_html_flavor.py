"""The public.html clipboard flavor MUST declare a charset.

NSPasteboard stores the string, but the receiving app reads bytes: without
`<meta charset>` the HTML standard mandates decoding as Windows-1252 and every
UTF-8 accent breaks ("ó" → "Ã³"). It really happened: a notes-mode dictation
pasted into a web editor came out with all its accents broken.
"""
from voooxly import output


def test_el_sabor_html_declara_utf8_al_principio():
    flavor = output.html_flavor("<p>Micrófono</p>")
    assert flavor.startswith('<meta charset="utf-8">')
    assert "<p>Micrófono</p>" in flavor


def test_no_duplica_la_declaracion_si_ya_viene():
    ya = '<meta charset="utf-8"><p>hola</p>'
    assert output.html_flavor(ya) == ya


def test_empty_html_stays_empty():
    # copy_to_clipboard only adds the flavor when there is html: "" must stay
    # falsy so we never write a flavor that only contains the meta.
    assert output.html_flavor("") == ""
    assert output.html_flavor(None) is None
