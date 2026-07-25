"""Every mode must be DIFFERENTIAL: its prompt has to genuinely ask for what
the label promises (a structured AI prompt, real Markdown, a spec…), not a
one-line vagueness. These tests pin down each mode's key instructions so a
careless edit does not dilute them.
"""
from voooxly import modes


def _prompt(mode: str) -> str:
    return modes.system_prompt(mode, None)


# --- Base rules (apply to every LLM-backed mode) ---

def test_base_prohibe_responder_en_vez_de_transformar():
    """The classic failure: you dictate a question and the LLM ANSWERS it."""
    for mode in ("ordenar", "prompt", "resumir", "codigo", "notas"):
        assert "do NOT answer or execute it" in _prompt(mode), mode


def test_base_prohibe_preambulos_y_code_fences():
    p = _prompt("ordenar")
    assert "no preamble" in p
    assert "no code fences wrapping the whole answer" in p


def test_base_prohibe_inventar():
    assert "Never invent facts" in _prompt("ordenar")


# --- Per-mode differentials ---

def test_ordenar_limpia_y_detecta_respuestas():
    p = _prompt("ordenar")
    assert "Apply self-corrections" in p
    assert "ready-to-send message" in p
    assert "[fill in: ...]" in p


def test_prompt_structures_and_does_not_answer():
    p = _prompt("prompt")
    assert "Never fulfill the request yourself" in p
    for section in ("**Context:**", "**Requirements:**", "**Output:**"):
        assert section in p
    assert "Example — dictated:" in p  # carries a few-shot example


def test_resumir_limita_bullets_y_conserva_datos():
    p = _prompt("resumir")
    assert "Maximum 7 bullets" in p
    assert "numbers, names, dates and decisions" in p


def test_traducciones_traducen_lo_limpio_y_solo_devuelven_traduccion():
    en_es = _prompt("traducir-en-es")
    es_en = _prompt("traducir-es-en")
    for p in (en_es, es_en):
        assert "never word by word" in p
        assert "Keep the register" in p
    assert "into natural, native-sounding Spanish" in en_es
    assert "into natural, native-sounding English" in es_en


def test_codigo_es_spec_sin_implementacion():
    p = _prompt("codigo")
    assert "Never write the implementation" in p
    assert "**Behavior:**" in p
    assert "**Edge cases:**" in p
    assert "backticks" in p


def test_notes_requires_real_markdown():
    p = _prompt("notas")
    assert "`##` title" in p
    assert "`###` subheadings" in p
    assert "`- [ ]` checkboxes" in p
    assert "Output raw Markdown only" in p


def test_notas_prohibe_negritas():
    """The ** get pasted as literal asterisks outside Markdown apps."""
    p = _prompt("notas")
    assert "no bold, no italics" in p
    assert "Bold the key terms" not in p


def test_literal_skips_llm():
    assert modes.system_prompt("literal", None) == ""
    assert modes.system_prompt("literal", "en") == ""


def test_comando_ejecuta_el_encargo_en_vez_de_transformarlo():
    """The only mode that DOES fulfill the instruction (Command Mode, a
    Wispro idea): its base cannot carry the others' anti-execution rule."""
    p = _prompt("comando")
    assert "DO fulfill the request" in p
    assert "do NOT answer or execute it" not in p
    assert "Write the text the instruction asks for" in p


def test_comando_no_inventa_y_marca_los_huecos():
    p = _prompt("comando")
    assert "Never invent facts" in p
    assert "[fill in: ...]" in p


def test_comando_sin_encargo_cae_a_dictado_normal():
    """Dictating plain content in Command cannot produce invented text:
    the prompt orders treating it as dictation and cleaning it up."""
    p = _prompt("comando")
    assert "treat it as dictation" in p


# --- Catalog integrity ---

def test_todos_los_modos_tienen_label_y_hint():
    for key, spec in modes.MODES.items():
        assert spec.get("label"), key
        assert spec.get("hint"), key


def test_las_claves_de_modo_no_cambian():
    """Config, prefs and TCC reference these keys: they are stable API."""
    assert set(modes.MODES.keys()) == {
        "ordenar",
        "prompt",
        "resumir",
        "traducir-en-es",
        "traducir-es-en",
        "codigo",
        "notas",
        "comando",
        "literal",
    }


def test_modo_desconocido_cae_en_ordenar():
    assert modes.system_prompt("no-existe", None) == modes.system_prompt("ordenar", None)


# --- HUD flash when cycling (Ctrl+Shift+M feedback) ---

def test_flash_parts_muestra_nombre_posicion_y_hint():
    title, body = modes.flash_parts("prompt")
    assert "AI prompt" in title
    assert "2/9" in title  # second mode of the cycle (9 modes since Command)
    assert body == modes.MODES["prompt"]["hint"]


def test_flash_parts_de_todos_los_modos_tiene_titulo_y_cuerpo():
    for key in modes.MODES:
        title, body = modes.flash_parts(key)
        assert title.startswith("❯ ") and body, key


def test_flash_parts_with_unknown_mode_does_not_raise():
    title, _ = modes.flash_parts("no-existe")
    assert "Organize" in title
