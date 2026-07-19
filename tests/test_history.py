"""El historial persistente guarda texto sensible: permisos 0600, rotación que
no crece sin límite, y lecturas que sobreviven a líneas corruptas (crash a
media escritura) sin perder el resto.
"""
import json
import stat

from dictador import history


def test_append_y_load_devuelven_lo_ultimo_primero(tmp_path):
    p = tmp_path / "h.jsonl"
    for t in ("uno", "dos", "tres"):
        history.append(t, "ordenar", p)
    assert history.load(10, p) == ["tres", "dos", "uno"]
    assert history.load(2, p) == ["tres", "dos"]


def test_el_fichero_va_con_permisos_0600(tmp_path):
    p = tmp_path / "h.jsonl"
    history.append("privado", "ordenar", p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_load_sin_fichero_devuelve_vacio(tmp_path):
    assert history.load(10, tmp_path / "no-existe.jsonl") == []


def test_una_linea_corrupta_no_pierde_el_resto(tmp_path):
    p = tmp_path / "h.jsonl"
    history.append("antes", "ordenar", p)
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"ts": "2026-01-01", "mode": "orden\n')  # crash a media escritura
    history.append("después", "ordenar", p)
    assert history.load(10, p) == ["después", "antes"]


def test_search_ignora_mayusculas_y_devuelve_recientes_primero(tmp_path):
    p = tmp_path / "h.jsonl"
    for t in ("Reunión con Marta", "comprar pan", "marta me debe una llamada"):
        history.append(t, "ordenar", p)
    assert history.search("MARTA", 10, p) == [
        "marta me debe una llamada",
        "Reunión con Marta",
    ]
    assert history.search("nada-de-esto", 10, p) == []
    assert history.search("   ", 10, p) == []  # query vacía no devuelve todo


def test_rotacion_conserva_solo_las_ultimas_entradas(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "MAX_ENTRIES", 5)
    p = tmp_path / "h.jsonl"
    for i in range(11):  # 11 > MAX*2 → rota
        history.append(f"dictado {i}", "ordenar", p)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 6  # 5 conservadas + el append posterior a la rotación
    assert history.load(1, p) == ["dictado 10"]  # lo más nuevo nunca se pierde


def test_las_entradas_guardan_modo_y_timestamp(tmp_path):
    p = tmp_path / "h.jsonl"
    history.append("hola", "notas", p)
    e = json.loads(p.read_text(encoding="utf-8").strip())
    assert e["mode"] == "notas"
    assert e["text"] == "hola"
    assert e["ts"]  # iso8601 UTC
