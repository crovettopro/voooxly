"""The shortcut registry: what exists, how it resolves, what happens if broken.

A pure data module, like keys.py and for the same reason: instantiating the
Shortcuts window builds AppKit and that does not run in a test. All the
verifiable logic lives here; settings_window.py only paints what this decides.

What gets tested most fiercely is resolution with corrupt input.
~/.voooxly/prefs.json and config.yaml get hand-edited by people, and neither
of the two sources may leave the app without shortcuts.
"""
from voooxly import shortcuts


class _Cfg:
    """Fake cfg with the same interface as config.load(): .get(path, default)."""

    def __init__(self, data=None):
        self._data = data or {}

    def get(self, path, default=None):
        return self._data.get(path, default)


def test_existen_los_cuatro_atajos_y_solo_esos():
    assert set(shortcuts.SHORTCUTS) == {"dictation", "cycle_mode", "latch", "cancel"}


def test_only_dictation_has_delay():
    # D4 of the design: the disambiguation window protects against combos like ⌘C.
    # On esc or on ⌃⇧M it protects against nothing and would be free latency.
    assert shortcuts.SHORTCUTS["dictation"].has_delay is True
    for sid in ("cycle_mode", "latch", "cancel"):
        assert shortcuts.SHORTCUTS[sid].has_delay is False, sid


def test_sin_prefs_ni_yaml_salen_los_defaults():
    r = shortcuts.resolve({}, _Cfg())
    assert r["dictation"]["keys"] == ["cmd_r"]
    assert r["dictation"]["style"] == "hold"
    assert r["dictation"]["delay_ms"] == 0      # cmd_r needs no guard
    assert r["cycle_mode"]["keys"] == ["ctrl", "shift", "m"]
    assert r["latch"]["keys"] == ["shift"]
    assert r["cancel"]["keys"] == ["esc"]


def test_prefs_take_precedence_over_yaml():
    cfg = _Cfg({"hotkeys.toggle": ["alt_r"]})
    prefs = {"shortcuts": {"dictation": {"keys": ["ctrl_r"], "style": "hold", "delay_ms": 0}}}
    assert shortcuts.resolve(prefs, cfg)["dictation"]["keys"] == ["ctrl_r"]


def test_corrupt_prefs_do_not_leave_app_without_shortcut():
    # A list where a dict should go, a number where a list should go:
    # prefs.json is written by the app but anyone can edit it.
    for basura in ([], 7, "cmd_r", {"dictation": 3}, {"dictation": {"keys": "cmd_r"}}):
        r = shortcuts.resolve({"shortcuts": basura}, _Cfg())
        assert r["dictation"]["keys"] == ["cmd_r"], basura


def test_una_tecla_invalida_en_prefs_cae_al_default():
    # "a" would cripple the keyboard; validate_custom rejects it and resolve
    # does not let it through even if it is written in the json.
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["a"]}}}, _Cfg())
    assert r["dictation"]["keys"] == ["cmd_r"]


def test_el_delay_se_recorta_al_rango():
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_r"], "delay_ms": 5000}}}, _Cfg())
    assert r["dictation"]["delay_ms"] == shortcuts.MAX_DELAY_MS
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_r"], "delay_ms": -3}}}, _Cfg())
    assert r["dictation"]["delay_ms"] == 0


def test_un_delay_no_numerico_cae_al_valor_seguro():
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_l"], "delay_ms": "mucho"}}}, _Cfg())
    # cmd_l needs a guard: without a usable delay, the safe value is the default,
    # NEVER 0 (with 0 every ⌘C would start a recording).
    assert r["dictation"]["delay_ms"] == shortcuts.DEFAULT_DELAY_MS


def test_unknown_style_falls_back_to_hold():
    r = shortcuts.resolve({"shortcuts": {"dictation": {"keys": ["cmd_r"], "style": "bailar"}}}, _Cfg())
    assert r["dictation"]["style"] == "hold"


def test_wrong_type_in_hotkeys_toggle_mode_does_not_break_all_shortcuts():
    # A typo in config.yaml like `toggle_mode: [hold]` instead of
    # `toggle_mode: hold` can happen: it is a hand-edited file. That typo
    # must not leave the app without shortcuts: the second type guard must be
    # as strong as the first.
    cfg = _Cfg({"hotkeys.toggle_mode": ["hold"]})  # A list instead of a str
    r = shortcuts.resolve({"shortcuts": {}}, cfg)
    # The style must fall back to the default without raising TypeError
    assert r["dictation"]["style"] == "hold"
    # Critical: all four shortcuts must resolve, not just "dictation"
    assert "cycle_mode" in r
    assert "latch" in r
    assert "cancel" in r
    assert r["cycle_mode"]["keys"] == ["ctrl", "shift", "m"]
    assert r["latch"]["keys"] == ["shift"]
    assert r["cancel"]["keys"] == ["esc"]


def test_non_finite_delay_does_not_break_all_shortcuts():
    # json.dump writes Infinity and NaN for non-finite floats: a prefs.json value
    # with delay_ms: Infinity or delay_ms: NaN is possible without anyone hand-editing.
    # float('inf') and float('nan') are float instances, so they pass the current
    # type guards and cause OverflowError / ValueError in int(valor).
    # A non-finite delay must not leave the app without shortcuts: it is a bug in the
    # serialization stack, not a user mistake.
    for delay_invalido in (float('inf'), float('nan')):
        r = shortcuts.resolve(
            {"shortcuts": {"dictation": {"keys": ["cmd_l"], "delay_ms": delay_invalido}}},
            _Cfg()
        )
        # The delay must fall back to the default without raising OverflowError / ValueError
        # cmd_l needs a guard, so the default is DEFAULT_DELAY_MS, not 0
        assert r["dictation"]["delay_ms"] == shortcuts.DEFAULT_DELAY_MS, f"delay_invalido={delay_invalido}"
        # Critical: all four shortcuts must resolve, not just "dictation"
        assert "cycle_mode" in r
        assert "latch" in r
        assert "cancel" in r
        assert r["cycle_mode"]["keys"] == ["ctrl", "shift", "m"], f"delay_invalido={delay_invalido}"
        assert r["latch"]["keys"] == ["shift"], f"delay_invalido={delay_invalido}"
        assert r["cancel"]["keys"] == ["esc"], f"delay_invalido={delay_invalido}"


def test_side_hint_de_una_tecla_de_lado_unico():
    # dictation and cancel match by exact equality (hotkey.py:397 and :432): a
    # sided name always matches only that side, no ambiguity possible.
    assert shortcuts.side_hint("dictation", ["cmd_r"]) == "right"
    assert shortcuts.side_hint("dictation", ["cmd_l"]) == "left"
    assert shortcuts.side_hint("cancel", ["esc"]) == ""


def test_side_hint_of_combo_has_no_side():
    # A three-key combo is not "one-sided": ctrl+shift+m does not distinguish
    # the left ctrl from the right one, and claiming either of them would lie
    # about what the binding actually requires.
    assert shortcuts.side_hint("cycle_mode", ["ctrl", "shift", "m"]) == ""


def test_side_hint_del_latch_de_fabrica_casa_las_dos_manos():
    # hotkey.py:497 matches "shift" AND "shift_r" (PREFIX matching, documented
    # at hotkey.py:203: "shift" also matches shift_r). With the factory shift,
    # saying "left" would be false: the right shift also latches the recording.
    assert shortcuts.side_hint("latch", ["shift"]) == "either side"


def test_side_hint_de_latch_reasignado_a_una_tecla_con_lado_ya_no_ensancha():
    # If latch moves to cmd_r, the widening prefix would be "cmd_r_" — nothing
    # starts like that, so only the right Cmd matches at runtime. The
    # widening in hotkey.py is exclusive to the side-less modifiers
    # ("shift", "cmd", "alt", "ctrl"), not a general property of the latch
    # shortcut: rebinding to a key with its own side is side-specific again.
    assert shortcuts.side_hint("latch", ["cmd_r"]) == "right"


def test_matched_keys_del_latch_de_fabrica_incluye_las_dos_manos():
    # The raw fact behind side_hint("latch", ["shift"]) == "either side":
    # hotkey.py:421 matches "shift" (equality) AND "shift_r" (prefix). Both
    # must appear in the set, canonicalized.
    assert shortcuts.matched_keys("latch", ["shift"]) == {"shift", "shift_r"}


def test_matched_keys_de_latch_con_lado_propio_no_ensancha():
    assert shortcuts.matched_keys("latch", ["cmd_r"]) == {"cmd_r"}


def test_matched_keys_fuera_de_latch_nunca_ensancha():
    # dictation/cancel/cycle_mode match by exact equality (hotkey.py:397 and
    # :432): a side-less modifier there is ONLY the left one, never both.
    assert shortcuts.matched_keys("dictation", ["cmd"]) == {"cmd"}
    assert shortcuts.matched_keys("cancel", ["esc"]) == {"esc"}


def test_matched_keys_de_un_combo_canonicaliza_cada_tecla_sin_ensanchar():
    # ctrl+shift+m: hotkey.py:439 compares the pressed set by EQUALITY
    # against the whole combo, so each key matches only its own side.
    assert shortcuts.matched_keys("cycle_mode", ["ctrl", "shift", "m"]) == {"ctrl", "shift", "m"}


def test_matched_keys_canonicaliza_cmd_l_a_cmd():
    # cmd_l and cmd are the same physical key (pynput collapses the left one).
    assert shortcuts.matched_keys("dictation", ["cmd_l"]) == {"cmd"}


def test_los_atajos_llevan_las_claves_exactas_esperadas():
    # Later tasks read this shape: dictation carries delay_ms and style, the
    # other three only "keys". This test locks down that contractual shape.
    r = shortcuts.resolve({}, _Cfg())
    assert set(r["dictation"].keys()) == {"keys", "delay_ms", "style"}
    assert set(r["cycle_mode"].keys()) == {"keys"}
    assert set(r["latch"].keys()) == {"keys"}
    assert set(r["cancel"].keys()) == {"keys"}
