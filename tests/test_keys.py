"""El catálogo de teclas de dictado y, sobre todo, su validación.

La validación no es cosmética: elegir mal la tecla de dictado inutiliza el
teclado entero. Con 'a' como tecla de dictado dejas de poder escribir la letra
a en todo el sistema; con 'esc' pierdes el cancelar; con 'cmd' a secas capturas
los dos lados. Estos tests fijan cada puerta.
"""
from voooxly import keys


def test_el_default_es_la_tecla_que_ya_venia_de_fabrica():
    # Cambiar el default migraría en silencio a todo el que ya usa la app.
    assert keys.DEFAULT_KEY == "cmd_r"
    assert keys.DEFAULT_MODE == "hold"


def test_las_derechas_no_llevan_guarda_y_las_izquierdas_si():
    # Las derechas arrancan al instante: es la ruta que ya está en producción
    # y no se toca. Las izquierdas la necesitan o cada ⌘C graba.
    assert keys.needs_guard("cmd_r") is False
    assert keys.needs_guard("alt_r") is False
    assert keys.needs_guard("f13") is False
    assert keys.needs_guard("cmd_l") is True
    assert keys.needs_guard("alt_l") is True
    assert keys.needs_guard("ctrl_l") is True


def test_el_menu_ofrece_las_dos_manos_y_las_efes():
    assert set(keys.DICTATION_KEYS) == {
        "cmd_r", "alt_r", "ctrl_r",
        "cmd_l", "alt_l", "ctrl_l",
        "f6", "f13", "f14", "f15",
    }


def test_las_derechas_van_primero_en_el_menu():
    # El orden del dict es el del menú: lo recomendado arriba.
    assert list(keys.DICTATION_KEYS)[:3] == ["cmd_r", "alt_r", "ctrl_r"]


def test_la_etiqueta_de_las_izquierdas_avisa_del_retardo():
    # El retardo es una consecuencia real de elegirlas. Se ve ANTES de elegir,
    # no se descubre después preguntándose por qué va lento.
    assert "300" in keys.DICTATION_KEYS["cmd_l"].label
    assert "300" not in keys.DICTATION_KEYS["cmd_r"].label


def test_una_letra_suelta_se_rechaza():
    ok, msg = keys.validate_custom("a")
    assert ok is False
    assert "a" in msg.lower()


def test_un_digito_suelto_se_rechaza():
    assert keys.validate_custom("7")[0] is False


def test_esc_y_shift_se_rechazan_porque_ya_tienen_dueno():
    assert keys.validate_custom("esc")[0] is False
    assert keys.validate_custom("shift")[0] is False
    assert keys.validate_custom("shift_r")[0] is False


def test_un_modificador_sin_lado_se_rechaza():
    for n in ("cmd", "ctrl", "alt"):
        ok, msg = keys.validate_custom(n)
        assert ok is False, f"{n} debería exigir lado"
        assert "_l" in msg or "_r" in msg, "el error tiene que decir cómo arreglarlo"


def test_un_nombre_que_pynput_no_conoce_se_rechaza():
    # Aceptarlo daría una tecla que no dispara nunca: fallo mudo, lo peor.
    assert keys.validate_custom("tecla_inventada")[0] is False


def test_una_funcion_alta_se_acepta_sin_guarda():
    ok, _ = keys.validate_custom("f18")
    assert ok is True
    assert keys.needs_guard("f18") is False


def test_un_modificador_fuera_del_catalogo_se_acepta_con_guarda():
    # alt_gr existe en pynput y no está en el menú, pero sigue siendo un
    # modificador: se usa en combos, así que necesita guarda igual.
    ok, _ = keys.validate_custom("alt_gr")
    assert ok is True
    assert keys.needs_guard("alt_gr") is True


def test_resolve_usa_prefs_por_encima_del_yaml():
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    prefs = {"dictation_key": "alt_r", "dictation_mode": "toggle"}
    assert keys.resolve(prefs, _FakeCfg(cfg)) == ("alt_r", "toggle", False)


def test_resolve_cae_al_yaml_sin_prefs():
    cfg = {"hotkeys.toggle": ["f13"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg)) == ("f13", "hold", False)


def test_resolve_ignora_unos_prefs_corruptos():
    # prefs.json puede traer una lista, un número o una tecla retirada en una
    # versión posterior. Ninguno de esos casos puede dejar la app sin hotkey.
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    for malo in ([], 7, "tecla_inventada", None):
        assert keys.resolve({"dictation_key": malo}, _FakeCfg(cfg))[0] == "cmd_r"


def test_resolve_ignora_un_modo_invalido():
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({"dictation_mode": "bailando"}, _FakeCfg(cfg))[1] == "hold"


class _FakeCfg:
    """La config real solo se usa vía .get(path, default)."""

    def __init__(self, data):
        self._data = data

    def get(self, path, default=None):
        return self._data.get(path, default)
