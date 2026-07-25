"""axfield debe poder importarse y llamarse en cualquier entorno (CI incluido):
sin sesión gráfica devuelve None, jamás lanza."""
from voooxly import axfield


def test_importable_y_contrato():
    out = axfield.read_focused_text()
    assert out is None or isinstance(out, str)
