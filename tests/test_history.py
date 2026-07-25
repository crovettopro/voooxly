"""The persistent history stores sensitive text: 0600 permissions, rotation
that does not grow unbounded, and reads that survive corrupt lines (crash
mid-write) without losing the rest.
"""
import json
import stat

from voooxly import history


def test_append_and_load_return_latest_first(tmp_path):
    p = tmp_path / "h.jsonl"
    for t in ("uno", "dos", "tres"):
        history.append(t, "ordenar", p)
    assert history.load(10, p) == ["tres", "dos", "uno"]
    assert history.load(2, p) == ["tres", "dos"]


def test_el_fichero_va_con_permisos_0600(tmp_path):
    p = tmp_path / "h.jsonl"
    history.append("privado", "ordenar", p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_load_without_file_returns_empty(tmp_path):
    assert history.load(10, tmp_path / "no-existe.jsonl") == []


def test_one_corrupt_line_does_not_lose_the_rest(tmp_path):
    p = tmp_path / "h.jsonl"
    history.append("antes", "ordenar", p)
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"ts": "2026-01-01", "mode": "orden\n')  # crash mid-write
    history.append("después", "ordenar", p)
    assert history.load(10, p) == ["después", "antes"]


def test_search_ignores_case_and_returns_recent_first(tmp_path):
    p = tmp_path / "h.jsonl"
    for t in ("Reunión con Marta", "comprar pan", "marta me debe una llamada"):
        history.append(t, "ordenar", p)
    assert history.search("MARTA", 10, p) == [
        "marta me debe una llamada",
        "Reunión con Marta",
    ]
    assert history.search("nada-de-esto", 10, p) == []
    assert history.search("   ", 10, p) == []  # empty query does not return everything


def test_rotacion_conserva_solo_las_ultimas_entradas(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "MAX_ENTRIES", 5)
    p = tmp_path / "h.jsonl"
    for i in range(11):  # 11 > MAX*2 → rotates
        history.append(f"dictado {i}", "ordenar", p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 6  # 5 kept + the append after the rotation
    assert history.load(1, p) == ["dictado 10"]  # the newest is never lost


def test_las_entradas_guardan_modo_y_timestamp(tmp_path):
    p = tmp_path / "h.jsonl"
    history.append("hola", "notas", p)
    e = json.loads(p.read_text(encoding="utf-8").strip())
    assert e["mode"] == "notas"
    assert e["text"] == "hola"
    assert e["ts"]  # iso8601 UTC


def test_search_encuentra_con_y_sin_tildes_en_los_dos_sentidos():
    # You dictate "póker" and then search typing fast, with no accent. And the
    # reverse. Search has to be symmetric or it only works half the time.
    from voooxly import history as h
    assert h._fold("Póker") == h._fold("poker")
    assert h._fold("ARTÍCULO") == h._fold("articulo")


def test_search_sin_tildes_encuentra_el_texto_con_tildes(tmp_path):
    p = tmp_path / "h.jsonl"
    for t in ("partida de póker el jueves", "comprar pan"):
        history.append(t, "ordenar", p)
    assert history.search("poker", 10, p) == ["partida de póker el jueves"]


def test_search_con_tildes_encuentra_el_texto_sin_tildes(tmp_path):
    p = tmp_path / "h.jsonl"
    history.append("partida de poker el jueves", "ordenar", p)
    assert history.search("póker", 10, p) == ["partida de poker el jueves"]


def test_search_tambien_pliega_la_ene(tmp_path):
    # Explicit decision: 'año' and 'ano' are the same search. It is the
    # standard in a Spanish-language search box and the declared goal was
    # for searching to be easier, not more exact.
    p = tmp_path / "h.jsonl"
    history.append("resumen del año", "ordenar", p)
    assert history.search("ano", 10, p) == ["resumen del año"]


def test_folding_does_not_touch_saved_text(tmp_path):
    # Folding is for COMPARING, never for storing or returning: whatever gets
    # copied to the clipboard has to come out with its accents intact.
    p = tmp_path / "h.jsonl"
    history.append("Reunión con Íñigo", "ordenar", p)
    assert history.search("inigo", 10, p) == ["Reunión con Íñigo"]
