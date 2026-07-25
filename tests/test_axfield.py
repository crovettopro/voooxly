"""axfield must be importable and callable in any environment (CI included):
without a graphical session it returns None, it never raises."""
from voooxly import axfield


def test_importable_y_contrato():
    out = axfield.read_focused_text()
    assert out is None or isinstance(out, str)
