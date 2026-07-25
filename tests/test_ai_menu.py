"""Labels for the AI engine submenu."""

from voooxly import ai_settings, app, providers


def test_without_choice_none_is_marked():
    filas = app.ai_menu_labels(None)
    assert all(activo is False for _, activo in filas)


def test_chosen_is_marked_and_only_it():
    sel = ai_settings.Selection(providers.get("groq"), "https://api.groq.com/openai/v1", "m")
    filas = app.ai_menu_labels(sel)
    activos = [etq for etq, activo in filas if activo]
    assert len(activos) == 1
    assert "Groq" in activos[0]


def test_all_providers_are_present():
    filas = app.ai_menu_labels(None)
    assert len(filas) == len(providers.PROVIDERS)


def test_no_entry_has_ellipsis():
    """The short list is understandable without '…'; putting it on all five
    rows looked noisy. Guard so the suffix does not sneak back in."""
    for etq, _ in app.ai_menu_labels(None):
        assert not etq.endswith("…"), etq


def test_title_with_explicit_choice_shows_provider():
    """With an explicit selection the title names the provider and does NOT
    say '(auto)': the user's choice is not a detection."""
    sel = ai_settings.Selection(providers.get("groq"), "https://api.groq.com/openai/v1", "m")
    titulo = app.ai_engine_title(sel, "")
    assert "Groq" in titulo
    assert "(auto)" not in titulo


def test_title_without_choice_with_detected_backend_says_auto():
    titulo = app.ai_engine_title(None, "ollama")
    assert "Ollama" in titulo
    assert "(auto)" in titulo


def test_title_without_choice_and_without_detected_backend():
    """With no provider detected, the exact title warns that raw text gets
    pasted: it is the only passive indicator of this state in the whole menu."""
    assert app.ai_engine_title(None, "none") == "AI engine — none (raw text)"


def test_title_always_starts_with_ai_engine():
    """No matter what, the title starts the same way: this keeps the menu
    recognizable even when the active provider changes."""
    casos = [
        (None, "none"),
        (None, "ollama"),
        (ai_settings.Selection(providers.get("claude"), "", "m"), ""),
    ]
    for sel, detected in casos:
        assert app.ai_engine_title(sel, detected).startswith("AI engine")


# --- The parent's title: the only hint of whether AI is connected ---

def test_title_has_bare_name_without_note():
    # provider.label is "Groq — free" (the submenu row). Dropped as-is into
    # the title it came out as "AI engine — Groq — free": two em dashes in a
    # row, which reads as if "free" were another field. The parent uses .name.
    sel = ai_settings.Selection(providers.get("groq"), "https://api.groq.com/openai/v1", "m")
    assert app.ai_engine_title(sel, "") == "AI engine — Groq"


def test_submenu_row_keeps_the_note():
    # The "free" must remain visible where the provider is chosen: it is the
    # reason Groq goes first.
    assert providers.get("groq").label == "Groq — free"
    assert providers.get("claude").label == "Claude"


def test_without_ai_title_says_so():
    assert "none" in app.ai_engine_title(None, "none")
