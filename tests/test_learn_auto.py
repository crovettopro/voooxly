"""Guards for the automatic path: es-aware phonetics + common words.

A style edit ("envía"→"manda") is NOT a mishearing and must never
be learned: the phonetic filter is what separates auto-learn from
auto-corrupting the dictionary.
"""
from voooxly import dictionary
from voooxly.learn import (
    _is_common,
    auto_corrections,
    auto_learn_from,
    locate_pasted,
    normalize_phonetic,
    sounds_alike,
)

PEGADO = "hola equipo, el informe de wisperflow llega mañana por la tarde"


def test_normaliza_grafias_espanolas_equivalentes():
    assert normalize_phonetic("valla") == normalize_phonetic("baya")
    assert normalize_phonetic("hola") == normalize_phonetic("ola")
    assert normalize_phonetic("quiosco") == normalize_phonetic("kiosco")


def test_errores_de_oido_suenan_parecido():
    assert sounds_alike("wisperflow", "Wispr Flow")
    assert sounds_alike("ucademi", "Ucademy")
    assert sounds_alike("boxli", "Voooxly")


def test_ediciones_de_estilo_no_suenan_parecido():
    assert not sounds_alike("envía", "manda")
    assert not sounds_alike("informe", "documento")
    assert not sounds_alike("hola", "buenas")


def test_entradas_vacias_no_suenan_parecido():
    assert not sounds_alike("", "algo")
    assert not sounds_alike("algo", "")
    assert not sounds_alike("!!!", "???")


def test_palabras_comunes_es_y_en():
    assert _is_common("que") and _is_common("the")
    assert not _is_common("Voooxly") and not _is_common("Ucademy")


def test_locates_pasted_text_inside_a_long_document():
    doc = "Notas del lunes.\n\n" + PEGADO + "\n\nOtras cosas sin relación que ya estaban."
    assert locate_pasted(PEGADO, doc) == " ".join(PEGADO.split())


def test_localiza_aunque_este_corregido():
    doc = "Intro previa. " + PEGADO.replace("wisperflow", "Wispr Flow") + " Y un cierre."
    region = locate_pasted(PEGADO, doc)
    assert region is not None and "Wispr Flow" in region


def test_does_not_locate_if_field_is_different():
    assert locate_pasted(PEGADO, "totalmente otra cosa escrita aquí sin relación alguna") is None


def test_no_localiza_si_lo_pegado_fue_borrado_o_reescrito():
    assert locate_pasted(PEGADO, "al final lo reescribí entero con distintas palabras nuevas") is None
    assert locate_pasted(PEGADO, "") is None
    assert locate_pasted("", "algo") is None


def test_auto_aprende_solo_la_grafia_corregida():
    campo = "Contexto. " + PEGADO.replace("wisperflow", "Wispr Flow") + " Despedida."
    assert auto_corrections(PEGADO, campo) == [("wisperflow", "Wispr Flow")]


def test_auto_ignores_style_edits():
    campo = PEGADO.replace("llega", "aterriza")  # synonym: style, not mishearing
    assert auto_corrections(PEGADO, campo) == []


def test_auto_ignora_correcciones_a_palabras_comunes():
    campo = PEGADO.replace("por", "para")  # common and doesn't sound alike: double rejection
    assert auto_corrections(PEGADO, campo) == []


def test_auto_without_changes_learns_nothing():
    assert auto_corrections(PEGADO, "x " + PEGADO + " y") == []


def test_auto_learn_from_persists_to_dictionary(tmp_path):
    dic = tmp_path / "dictionary.json"
    campo = PEGADO.replace("wisperflow", "Wispr Flow")
    out = auto_learn_from(PEGADO, campo, path=dic)
    assert len(out) == 1
    data = dictionary.load(dic)
    assert data["replacements"].get("wisperflow") == "Wispr Flow"


def test_auto_learn_from_with_illegible_field_does_not_touch_dictionary(tmp_path):
    dic = tmp_path / "dictionary.json"
    assert auto_learn_from(PEGADO, "", path=dic) == []
    assert not dic.exists()


# --- Inflection guard ------------------------------------------------------
# A correction that only adds or drops the tail of a word ("email" → "emails")
# is how the sentence is built, not how the word is spelled. Learning it turns
# a one-off edit into a permanent global replacement — and there is no way to
# undo one from the app.

FRASE = "Le mandé el email al client y adjunté el prompt del informe"


def test_adding_a_trailing_letter_is_not_learned():
    for singular, plural in (("email", "emails"), ("client", "clients"),
                             ("prompt", "prompts")):
        campo = FRASE.replace(singular, plural)
        assert auto_corrections(FRASE, campo) == [], f"{singular} → {plural}"


def test_dropping_a_trailing_letter_is_not_learned_either():
    # The user dictates the plural and fixes it to the singular: same edit,
    # opposite direction, equally fatal as a global replacement.
    plural_frase = FRASE.replace("email", "emails")
    assert auto_corrections(plural_frase, FRASE) == []


def test_a_two_letter_plural_ending_is_not_learned():
    # "es" is the plural for consonant endings in both languages.
    for singular, plural in (("client", "clientes"), ("prompt", "promptes")):
        campo = FRASE.replace(singular, plural)
        assert auto_corrections(FRASE, campo) == [], f"{singular} → {plural}"


def test_a_spanish_cognate_typed_over_an_english_word_is_not_learned():
    # "Deploy" → "Deploya" is the same shape: the word plus a tail.
    pegado = "Vamos a Deploy el viernes por la tarde sin prisas"
    assert auto_corrections(pegado, pegado.replace("Deploy", "Deploya")) == []


def test_the_names_it_exists_for_are_still_learned():
    # The guard must not cost the feature its actual job. None of these is a
    # word plus a tail: the letters change inside.
    casos = (
        ("Quedé con Krobeto para revisar el informe", "Krobeto", "Crovetto"),
        ("Se lo mandé a Ana esta misma mañana temprano", "Ana", "Anna"),
        ("El informe de wisperflow llega mañana por la tarde", "wisperflow", "Wispr Flow"),
    )
    for pegado, mal, bien in casos:
        assert auto_corrections(pegado, pegado.replace(mal, bien)) == [(mal, bien)]


def test_a_long_tail_is_still_a_real_correction():
    # "Vixi" → "Vixiees" adds three letters: a mishearing, not an inflection.
    pegado = "Hablé con Vixi sobre el presupuesto del año que viene"
    assert auto_corrections(pegado, pegado.replace("Vixi", "Vixiees")) == [("Vixi", "Vixiees")]
