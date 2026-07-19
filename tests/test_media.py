"""Pausar la música al dictar solo debe tocar lo que estaba SONANDO, y resume()
solo debe reanudar lo que pause_playing() pausó — nunca arrancar un reproductor
que el usuario tenía parado.
"""
from unittest.mock import MagicMock, patch

from voooxly import media


def _run_result(stdout: str):
    return MagicMock(stdout=stdout, returncode=0)


def test_pausa_solo_los_que_estan_sonando():
    # Spotify sonando, Music parado
    def fake_run(cmd, **kwargs):
        script = cmd[-1]
        return _run_result("paused" if "Spotify" in script else "no")

    with patch("voooxly.media.subprocess.run", side_effect=fake_run):
        assert media.pause_playing() == ["Spotify"]


def test_pausa_ninguno_si_nada_suena():
    with patch("voooxly.media.subprocess.run", return_value=_run_result("no")):
        assert media.pause_playing() == []


def test_un_reproductor_colgado_no_estorba_al_resto():
    def fake_run(cmd, **kwargs):
        script = cmd[-1]
        if "Spotify" in script:
            raise OSError("osascript colgado")
        return _run_result("paused")

    with patch("voooxly.media.subprocess.run", side_effect=fake_run):
        assert media.pause_playing() == ["Music"]


def test_resume_solo_reanuda_lo_pausado():
    with patch("voooxly.media.subprocess.run", return_value=_run_result("")) as run:
        media.resume(["Spotify"])
    scripts = [call.args[0][-1] for call in run.call_args_list]
    assert len(scripts) == 1
    assert "Spotify" in scripts[0] and "play" in scripts[0]
    assert not any("Music" in s for s in scripts)


def test_resume_con_lista_vacia_no_llama_a_osascript():
    with patch("voooxly.media.subprocess.run") as run:
        media.resume([])
    run.assert_not_called()


def test_el_script_de_pausa_comprueba_running_antes_del_tell():
    """Un tell a una app cerrada la LANZA: 'is running' tiene que ir primero."""
    assert media._PAUSE_IF_PLAYING.index("is running") < media._PAUSE_IF_PLAYING.index(
        "player state"
    )
    assert media._RESUME.index("is running") < media._RESUME.index("play")
