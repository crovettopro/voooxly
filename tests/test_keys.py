"""The dictation key catalog and, above all, its validation.

Validation is not cosmetic: picking the wrong dictation key disables the
entire keyboard. With 'a' as the dictation key you can no longer type the
letter a anywhere in the system; with 'esc' you lose cancel; with bare 'cmd'
you capture both sides. These tests pin down each gate.
"""
from voooxly import keys


def test_el_default_es_la_tecla_que_ya_venia_de_fabrica():
    # Changing the default would silently migrate everyone already using the app.
    assert keys.DEFAULT_KEY == "cmd_r"
    assert keys.DEFAULT_MODE == "hold"


def test_las_derechas_no_llevan_guarda_y_las_izquierdas_si():
    # Right-side keys start instantly: that is the path already in production
    # and it is not touched. Left-side keys need it or every ⌘C records.
    assert keys.needs_guard("cmd_r") is False
    assert keys.needs_guard("alt_r") is False
    assert keys.needs_guard("f13") is False
    assert keys.needs_guard("cmd_l") is True
    assert keys.needs_guard("alt_l") is True
    assert keys.needs_guard("ctrl_l") is True


def test_el_menu_ofrece_las_seis_teclas_de_abajo_y_nada_mas():
    # Only the six bottom-row modifiers. The F keys left the menu because
    # half the catalog did not exist on the keyboard of whoever opened it:
    # laptops do not ship F13-F15 and a menu with four dead rows makes you
    # doubt the six that do work.
    assert set(keys.DICTATION_KEYS) == {
        "cmd_r", "alt_r", "ctrl_r",
        "cmd_l", "alt_l", "ctrl_l",
    }


def test_las_efes_siguen_valiendo_por_custom():
    # Removing them from the menu does not ban them: validate_custom is still
    # the gate for prefs.json and config.yaml, and they enter there unguarded.
    for f in ("f6", "f13", "f15", "f20"):
        assert keys.validate_custom(f)[0] is True, f
        assert keys.needs_guard(f) is False, f


def test_right_keys_come_first_in_menu():
    # The dict order is the menu order: the recommended ones on top.
    assert list(keys.DICTATION_KEYS)[:3] == ["cmd_r", "alt_r", "ctrl_r"]


def test_la_etiqueta_de_las_izquierdas_avisa_del_retardo():
    # The delay is a real consequence of choosing them. It shows BEFORE
    # choosing, not discovered later wondering why it feels slow.
    assert "300" in keys.DICTATION_KEYS["cmd_l"].label
    assert "300" not in keys.DICTATION_KEYS["cmd_r"].label


def test_una_letra_suelta_se_rechaza():
    ok, msg = keys.validate_custom("a")
    assert ok is False
    assert "a" in msg.lower()


def test_un_digito_suelto_se_rechaza():
    assert keys.validate_custom("7")[0] is False


def test_validate_custom_does_not_crash_with_a_truthy_int():
    # 7 is truthy: `(7 or "").strip()` blows up with AttributeError if the
    # type is not checked before touching it. validate_custom is public and a
    # later task wires it straight into the menu input, so a non-string
    # value cannot crash it — it has to be rejected like any other
    # invalid key.
    ok, msg = keys.validate_custom(7)
    assert ok is False
    assert isinstance(msg, str) and msg


def test_validate_custom_rechaza_cualquier_tipo_no_string_sin_reventar():
    # Falsy non-strings (0, [], None) already degraded without crashing because
    # `(name or "")` turned them into an empty string. This test pins that
    # truthy ones (7.5, True, non-empty lists) are also rejected instead of
    # raising an exception.
    for malo in (0, [], {}, None, 7.5, True, ["a"]):
        ok, msg = keys.validate_custom(malo)
        assert ok is False, f"{malo!r} debería rechazarse, no reventar"


def test_esc_y_shift_se_rechazan_porque_ya_tienen_dueno():
    assert keys.validate_custom("esc")[0] is False
    assert keys.validate_custom("shift")[0] is False
    assert keys.validate_custom("shift_r")[0] is False


def test_un_modificador_sin_lado_se_rechaza():
    for n in ("cmd", "ctrl", "alt"):
        ok, msg = keys.validate_custom(n)
        assert ok is False, f"{n} debería exigir lado"
        assert "_l" in msg or "_r" in msg, "el error tiene que decir cómo arreglarlo"


def test_no_side_modifier_message_does_not_assert_falsely():
    # On macOS bare "cmd" ONLY matches the left key (pynput collapses
    # Key.cmd_l into Key.cmd), never both. The previous message said it
    # "would match both" — false — and on top of that recommended "cmd_l" as
    # the fix, which hotkey._canon canonicalizes back to "cmd". The message
    # has to give direction without claiming behavior that does not exist.
    for n in ("cmd", "ctrl", "alt"):
        _, msg = keys.validate_custom(n)
        bajo = msg.lower()
        assert "both" not in bajo, f'el mensaje de "{n}" sigue afirmando que casa con las dos'
        assert f"{n}_l" in msg and f"{n}_r" in msg


def test_un_nombre_que_pynput_no_conoce_se_rechaza():
    # Accepting it would give a key that never fires: silent failure, the worst.
    assert keys.validate_custom("tecla_inventada")[0] is False


def test_una_funcion_alta_se_acepta_sin_guarda():
    ok, _ = keys.validate_custom("f18")
    assert ok is True
    assert keys.needs_guard("f18") is False


def test_alt_gr_se_acepta_y_no_lleva_guarda_porque_es_alt_r():
    # alt_gr is not in the menu but pynput collapses it into the same enum
    # member as alt_r (Key.alt_gr is Key.alt_r on macOS: there is no physical
    # AltGr key distinct from the right Option). Treating it as "just any
    # modifier" and putting a guard on it would be inconsistent with the
    # catalog already treating right-side keys — which is what alt_gr truly
    # IS — without a guard.
    ok, _ = keys.validate_custom("alt_gr")
    assert ok is True
    assert keys.needs_guard("alt_gr") is False


def test_fn_se_acepta_sin_guarda():
    # Wispr Flow's star key: dictate while holding fn/🌐. No guard: nobody
    # does ⌘C combos with it, so the trigger is instantaneous, like the
    # right-side keys.
    ok, _ = keys.validate_custom("fn")
    assert ok is True
    assert keys.needs_guard("fn") is False


def test_resolve_uses_prefs_over_yaml():
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    prefs = {"dictation_key": "alt_r", "dictation_mode": "toggle"}
    assert keys.resolve(prefs, _FakeCfg(cfg)) == ("alt_r", "toggle", False)


def test_resolve_falls_back_to_yaml_without_prefs():
    cfg = {"hotkeys.toggle": ["f13"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg)) == ("f13", "hold", False)


def test_resolve_ignores_corrupt_prefs():
    # prefs.json may bring a list, a number, or a key retired in a later
    # version. None of those cases may leave the app without a hotkey.
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    for malo in ([], 7, "tecla_inventada", None):
        assert keys.resolve({"dictation_key": malo}, _FakeCfg(cfg))[0] == "cmd_r"


def test_resolve_ignora_un_modo_invalido():
    cfg = {"hotkeys.toggle": ["cmd_r"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({"dictation_mode": "bailando"}, _FakeCfg(cfg))[1] == "hold"


def test_resolve_cae_al_default_si_el_yaml_trae_un_string_suelto():
    # "toggle: cmd_r" instead of "toggle: [cmd_r]" is an easy YAML mistake to
    # make. Without checking the shape before indexing, "alt_r"[0] sneaks "a"
    # in as the dictation key and silently breaks the keyboard.
    cfg = {"hotkeys.toggle": "alt_r", "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


def test_resolve_cae_al_default_si_el_yaml_no_es_subscriptable():
    # An integer (or any type without __getitem__) in hotkeys.toggle cannot
    # take the whole app down with a TypeError: ignore it, fall back to default.
    cfg = {"hotkeys.toggle": 42, "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


def test_resolve_cae_al_default_si_la_lista_del_yaml_esta_vacia():
    cfg = {"hotkeys.toggle": [], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


def test_resolve_cae_al_default_si_la_tecla_del_yaml_no_pasa_validate_custom():
    # The prefs key goes through validate_custom before being accepted; the
    # YAML one had a shortcut that skipped it. With a well-formed list but
    # an invalid key inside (a bare letter), it has to be rejected just
    # like it would be coming from prefs.
    cfg = {"hotkeys.toggle": ["a"], "hotkeys.toggle_mode": "hold"}
    assert keys.resolve({}, _FakeCfg(cfg))[0] == keys.DEFAULT_KEY


def test_canon_translates_catalog_name_to_what_pynput_reports():
    # On macOS Key.cmd_l IS Key.cmd (same virtual keycode, enum.Enum collapses
    # them), so _norm() never returns "cmd_l". Without this translation the
    # configured key would never match and no dictation would ever start.
    assert keys.canon("cmd_l") == "cmd"
    assert keys.canon("alt_l") == "alt"
    assert keys.canon("ctrl_l") == "ctrl"
    assert keys.canon("shift_l") == "shift"


def test_canon_deja_las_derechas_como_estan():
    # Right-side keys are their own enum members and come out as-is.
    assert keys.canon("cmd_r") == "cmd_r"
    assert keys.canon("alt_r") == "alt_r"


def test_canon_colapsa_alt_gr_en_alt_r():
    # There is no physical AltGr distinct from the right Option on macOS.
    assert keys.canon("alt_gr") == "alt_r"


def test_canon_tolerates_none_and_uppercase():
    assert keys.canon(None) is None
    assert keys.canon("") == ""
    assert keys.canon("CMD_L") == "cmd"


class _FakeCfg:
    """The real config is only used via .get(path, default)."""

    def __init__(self, data):
        self._data = data

    def get(self, path, default=None):
        return self._data.get(path, default)
