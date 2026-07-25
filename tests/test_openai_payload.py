"""The body of the POST to /chat/completions depending on the model.

Eduardo's real-world failure: gpt-5-mini returned 400 Bad Request while
gpt-4.1-mini connected. OpenAI's reasoner models (gpt-5*, o1*, o3*, o4*)
only accept the default temperature: sending them any other is a 400. The
payload lives in a pure function so this contract stays pinned here.
"""
from voooxly import refine


def _body(model):
    return refine.openai_payload(model, "sys", "user", 0.3)


def test_los_razonadores_no_llevan_temperature():
    for m in ("gpt-5-mini", "gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.4-mini",
              "o3-mini", "o4-mini", "o1"):
        assert "temperature" not in _body(m), m


def test_el_resto_conserva_su_temperature():
    for m in ("gpt-4.1-mini", "gpt-4o-mini", "llama-3.3-70b-versatile",
              "gemini-3.6-flash", "gemini-2.5-flash"):
        assert _body(m)["temperature"] == 0.3, m


def test_el_payload_lleva_modelo_y_mensajes_en_orden():
    body = _body("gpt-4.1-mini")
    assert body["model"] == "gpt-4.1-mini"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == "sys"
    assert body["messages"][1]["content"] == "user"


def test_un_modelo_que_solo_empieza_parecido_no_se_confunde():
    # "o1" is a dangerous prefix: "olmo-7b" is not an OpenAI reasoner and
    # stripping its temperature would silently change its output.
    assert "temperature" in _body("olmo-7b")
    assert "temperature" in _body("gpt-4o")
