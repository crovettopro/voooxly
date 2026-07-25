"""The palette and base widgets, shared between the two windows.

They are extracted from onboarding.py so settings_window.py does not duplicate
them: two copies of the palette drift apart at the first brand tweak and you
end up with two differently colored windows in the same app.

These tests build real AppKit objects, like the onboarding ones.
"""
from voooxly import theme


def test_la_paleta_de_marca_existe_entera():
    for nombre in (
        "TEAL", "TEAL_DARK", "INK", "INK_SOFT", "INK_MUTED", "INK_KEYCAP",
        "PAGE_BG", "HAIRLINE", "DIVIDER", "BTN_BORDER", "BTN_GHOST_TEXT",
        "KEYCAP_BG", "KEYCAP_BG2", "KEYCAP_EDGE",
    ):
        assert getattr(theme, nombre) is not None, nombre


def test_hex_parses_brand_teal():
    c = theme.hex_("#107A69")
    assert abs(c.redComponent() - 0x10 / 255.0) < 0.01
    assert abs(c.greenComponent() - 0x7A / 255.0) < 0.01


def test_label_construye_un_campo_no_editable():
    from Foundation import NSMakeRect

    f = theme.label(NSMakeRect(0, 0, 100, 20), "Dictation", theme.sf(13))
    assert f.stringValue() == "Dictation"
    assert not f.isEditable()


def test_onboarding_sigue_usando_la_misma_paleta():
    # The refactor's goal: a single source of color. If onboarding kept
    # a copy of its own, this test catches it.
    from voooxly import onboarding

    assert onboarding.TEAL is theme.TEAL
    assert onboarding.PAGE_BG is theme.PAGE_BG
