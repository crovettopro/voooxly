"""Cumulative stats: they never raise, never lose what was accumulated, and
the summary tells a useful story ("typing saved") instead of raw numbers.
"""
from voooxly import stats


def test_bump_acumula(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump(10, 4.0, p)
    stats.bump(5, 2.5, p)
    s = stats.load(p)
    assert s["dictations"] == 2
    assert s["words"] == 15
    assert s["seconds_recorded"] == 6.5


def test_corrupt_file_resets_without_raising(tmp_path):
    p = tmp_path / "stats.json"
    p.write_text("{roto", encoding="utf-8")
    assert stats.load(p)["dictations"] == 0
    stats.bump(3, 1.0, p)  # and bump repairs it
    assert stats.load(p) == {
        "dictations": 1,
        "words": 3,
        "seconds_recorded": 1.0,
        "tokens": 0,
        "token_provider": "",
    }


def test_empty_summary_invites_to_dictate(tmp_path):
    assert "No dictations yet" in stats.summary(tmp_path / "no-existe.json")


def test_summary_en_minutos_y_en_horas(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump(400, 60.0, p)  # 400 words → ~7 min saved
    assert "min of typing saved" in stats.summary(p)
    stats.bump(20000, 600.0, p)  # now in hours
    out = stats.summary(p)
    assert "h of typing saved" in out
    assert "2 dictations" in out
    assert "20,400 words" in out


def test_valores_negativos_no_corrompen(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump(-5, -1.0, p)
    s = stats.load(p)
    assert s["dictations"] == 1 and s["words"] == 0 and s["seconds_recorded"] == 0.0


def test_bump_tokens_accumulates_and_remembers_provider(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump_tokens(700, "Groq", p)
    stats.bump_tokens(300, "Groq", p)
    s = stats.load(p)
    assert s["tokens"] == 1000
    assert s["token_provider"] == "Groq"


def test_los_tokens_conviven_con_el_resto_de_contadores(tmp_path):
    # bump and bump_tokens write the same file: one cannot clobber the other.
    p = tmp_path / "stats.json"
    stats.bump(10, 4.0, p)
    stats.bump_tokens(700, "Groq", p)
    stats.bump(5, 2.0, p)
    s = stats.load(p)
    assert s["words"] == 15
    assert s["tokens"] == 700


def test_el_resumen_muestra_los_tokens_cuando_los_hay(tmp_path):
    p = tmp_path / "stats.json"
    stats.bump(10, 4.0, p)
    stats.bump_tokens(198_000, "Groq", p)
    out = stats.summary(p)
    assert "198k tokens" in out
    assert "Groq" in out


def test_el_resumen_calla_los_tokens_si_no_hay(tmp_path):
    # With Ollama nothing is counted: a "0 tokens" next to a free tier
    # only confuses.
    p = tmp_path / "stats.json"
    stats.bump(10, 4.0, p)
    assert "tokens" not in stats.summary(p)


def test_el_resumen_muestra_los_tokens_en_millones(tmp_path):
    # Finding 4: 5,000,000 cannot read as "5000k tokens" — it has to switch
    # to the M scale above one million.
    p = tmp_path / "stats.json"
    stats.bump(10, 4.0, p)
    stats.bump_tokens(5_000_000, "Groq", p)
    out = stats.summary(p)
    assert "5.0M tokens" in out
    assert "5000k" not in out


def test_el_resumen_no_redondea_a_1000k_cerca_del_millon(tmp_path):
    # Finding 4: 999,500 with .0f over thousands rounds to "1000k", which is
    # not a valid scale — it must be promoted to "1.0M".
    p = tmp_path / "stats.json"
    stats.bump(10, 4.0, p)
    stats.bump_tokens(999_500, "Groq", p)
    out = stats.summary(p)
    assert "1000k" not in out
    assert "1.0M tokens" in out


def test_un_fichero_viejo_sin_tokens_se_lee_sin_romper(tmp_path):
    # Anyone with a stats.json from a previous version cannot lose their stats.
    import json
    p = tmp_path / "stats.json"
    p.write_text(json.dumps({"dictations": 3, "words": 100, "seconds_recorded": 20.0}))
    s = stats.load(p)
    assert s["words"] == 100
    assert s["tokens"] == 0
