from pathlib import Path
from unittest.mock import MagicMock, patch

from voooxly import updates


def test_is_newer_compara_numericamente_no_alfabeticamente():
    assert updates.is_newer("1.10.0", "1.9.0") is True  # alfabéticamente "1.10" < "1.9"
    assert updates.is_newer("1.0.1", "1.0.0") is True
    assert updates.is_newer("1.0.0", "1.0.0") is False
    assert updates.is_newer("0.9.0", "1.0.0") is False


def test_is_newer_tolera_versiones_raras():
    assert updates.is_newer("1.2", "1.1.9") is True
    assert updates.is_newer("1.0", "1.0.0") is False
    assert updates.is_newer("basura", "1.0.0") is False
    assert updates.is_newer("1.0.0", "basura") is False


def test_check_devuelve_info_si_hay_version_nueva():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0", "url": "https://x/y.dmg", "notes": "Nuevo"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        got = updates.check("https://voooxly/appcast.json", "1.0.0")
    assert got["version"] == "2.0.0"
    assert got["url"] == "https://x/y.dmg"
    assert got["notes"] == "Nuevo"


def test_check_devuelve_none_si_estamos_al_dia():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "1.0.0", "url": "https://x/y.dmg"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


def test_check_devuelve_none_si_falta_la_url():
    """Un appcast a medio publicar no debe abrir un menú que no lleva a ningún sitio."""
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


def test_check_nunca_lanza_si_no_hay_red():
    with patch("voooxly.updates.requests.get", side_effect=OSError("sin red")):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


def test_check_nunca_lanza_con_json_invalido():
    resp = MagicMock(ok=True)
    resp.json.side_effect = ValueError("no es json")
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


def test_check_devuelve_none_si_el_servidor_responde_error():
    resp = MagicMock(ok=False)
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


# --- download ---

def _resp_con_bytes(data: bytes, with_length: bool = True):
    """Mock de requests.get(stream=True) usable como context manager."""
    resp = MagicMock()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    resp.raise_for_status = MagicMock()
    resp.headers = {"Content-Length": str(len(data))} if with_length else {}
    resp.iter_content = MagicMock(return_value=[data[:3], data[3:]])
    return resp


def test_download_escribe_el_dmg_y_reporta_progreso(tmp_path):
    data = b"dmg-bytes"
    seen = []
    with patch("voooxly.updates.requests.get", return_value=_resp_con_bytes(data)):
        path = updates.download("https://x/y.dmg", "1.0.1", tmp_path, seen.append)
    assert path == tmp_path / "Voooxly-1.0.1.dmg"
    assert path.read_bytes() == data
    assert seen[-1] == 100
    assert not (tmp_path / "Voooxly-1.0.1.dmg.part").exists()


def test_download_devuelve_none_y_limpia_el_part_si_falla(tmp_path):
    resp = _resp_con_bytes(b"xx")
    resp.iter_content = MagicMock(side_effect=OSError("conexión cortada"))
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.download("https://x/y.dmg", "1.0.1", tmp_path) is None
    assert list(tmp_path.iterdir()) == []  # ni DMG ni .part huérfano


def test_download_sin_content_length_no_rompe_el_progreso(tmp_path):
    """GitHub a veces sirve sin Content-Length: sin él no hay pct, pero sí DMG."""
    seen = []
    with patch(
        "voooxly.updates.requests.get",
        return_value=_resp_con_bytes(b"dmg-bytes", with_length=False),
    ):
        path = updates.download("https://x/y.dmg", "1.0.1", tmp_path, seen.append)
    assert path is not None and path.read_bytes() == b"dmg-bytes"
    assert seen == [100]  # solo el 100 final


# --- check_status: distingue "sin novedad" de "error" ---

def test_check_status_available_devuelve_info():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0", "url": "https://x/y.dmg", "notes": "Nuevo"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        status, info = updates.check_status("https://u", "1.0.0")
    assert status == updates.UPDATE_AVAILABLE
    assert info == {"version": "2.0.0", "url": "https://x/y.dmg", "notes": "Nuevo"}


def test_check_status_up_to_date_sin_info():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "1.0.0", "url": "https://x/y.dmg"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        status, info = updates.check_status("https://u", "1.0.0")
    assert status == updates.UP_TO_DATE
    assert info is None


def test_check_status_error_si_no_hay_red():
    with patch("voooxly.updates.requests.get", side_effect=OSError("sin red")):
        status, info = updates.check_status("https://u", "1.0.0")
    assert status == updates.UPDATE_ERROR
    assert info is None


def test_check_status_error_si_falta_la_url():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        status, info = updates.check_status("https://u", "1.0.0")
    assert status == updates.UPDATE_ERROR
    assert info is None


def test_check_status_error_si_http_falla():
    resp = MagicMock(ok=False)
    with patch("voooxly.updates.requests.get", return_value=resp):
        status, info = updates.check_status("https://u", "1.0.0")
    assert status == updates.UPDATE_ERROR


# --- check() intacto tras refactor (regression) ---

def test_check_sigue_devolviendo_info_solo_si_hay_novedad():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0", "url": "https://x/y.dmg"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://u", "1.0.0")["version"] == "2.0.0"
    resp2 = MagicMock(ok=True)
    resp2.json.return_value = {"version": "1.0.0", "url": "https://x/y.dmg"}
    with patch("voooxly.updates.requests.get", return_value=resp2):
        assert updates.check("https://u", "1.0.0") is None


# --- should_notify: HUD una sola vez por versión ---

def test_should_notify_avisa_para_version_nueva():
    info = {"version": "1.3.0", "url": "u", "notes": ""}
    assert updates.should_notify(info, None) is True
    assert updates.should_notify(info, "1.2.0") is True


def test_should_notify_no_repite_para_misma_version():
    info = {"version": "1.3.0", "url": "u", "notes": ""}
    assert updates.should_notify(info, "1.3.0") is False


def test_should_notify_false_si_no_hay_novedad():
    assert updates.should_notify(None, None) is False


def test_check_interval_es_24_horas():
    assert updates.CHECK_INTERVAL == 24 * 3600


# --- should_prompt: el pop-up sale UNA vez por versión, entre arranques ---

def test_should_prompt_pregunta_para_version_nueva():
    info = {"version": "1.5.0", "url": "u", "notes": ""}
    assert updates.should_prompt(info, None) is True
    assert updates.should_prompt(info, "1.4.0") is True


def test_should_prompt_no_repite_la_version_ya_preguntada():
    """El usuario eligió "Later": el siguiente arranque no puede volver a
    interrumpirle con el mismo alert. prefs persiste la versión preguntada."""
    info = {"version": "1.5.0", "url": "u", "notes": ""}
    assert updates.should_prompt(info, "1.5.0") is False


def test_should_prompt_false_sin_novedad():
    assert updates.should_prompt(None, None) is False
    assert updates.should_prompt(None, "1.5.0") is False


# --- instalación automática: el DMG se instala solo (feedback v1.6) ---

def test_mount_point_parsea_el_plist_de_hdiutil():
    import plistlib

    plist = plistlib.dumps({"system-entities": [
        {"content-hint": "EFI"},                      # partición sin montar
        {"mount-point": "/Volumes/Voooxly"},
    ]})
    assert updates._mount_point(plist) == Path("/Volumes/Voooxly")


def test_mount_point_none_con_basura():
    assert updates._mount_point(b"esto no es un plist") is None
    assert updates._mount_point(b"") is None


def test_find_app_localiza_el_bundle(tmp_path):
    (tmp_path / "Voooxly.app").mkdir()
    (tmp_path / ".background").mkdir()               # decorado típico de un DMG
    assert updates.find_app(tmp_path) == tmp_path / "Voooxly.app"


def test_find_app_none_sin_bundle(tmp_path):
    assert updates.find_app(tmp_path) is None


def test_installer_script_cita_rutas_con_espacios():
    txt = updates.installer_script(
        Path("/Volumes/Voooxly 1.7/Voooxly.app"),
        Path("/Applications/Voooxly.app"),
        Path("/Volumes/Voooxly 1.7"),
        Path("/Users/x/Downloads/Voooxly-1.7.0.dmg"),
        1234,
        Path("/tmp/instalar.sh"),
    )
    assert "'/Volumes/Voooxly 1.7/Voooxly.app'" in txt
    assert "kill -0 1234" in txt
    assert "ditto" in txt
    assert "hdiutil detach" in txt


def _correr_instalador(tmp_path, src_existe: bool):
    """Ejecuta el script del instalador de verdad sobre carpetas de mentira.

    Devuelve (target, dmg, script) ya ejecutado. El pid es el de un proceso
    que YA murió (el instalador no debe esperar 30 s) y open_cmd es
    /usr/bin/true para no abrir nada."""
    import subprocess

    mount = tmp_path / "mount"
    mount.mkdir()
    src = mount / "Voooxly.app"
    if src_existe:
        src.mkdir()
        (src / "nuevo.txt").write_text("v2")
    target = tmp_path / "Applications" / "Voooxly.app"
    target.parent.mkdir()
    target.mkdir()
    (target / "viejo.txt").write_text("v1")
    dmg = tmp_path / "Voooxly.dmg"
    dmg.write_text("dmg")
    script = tmp_path / "instalar.sh"

    p = subprocess.Popen(["/usr/bin/true"])
    p.wait()   # pid muerto: el bucle de espera del script sale a la primera

    script.write_text(updates.installer_script(
        src, target, mount, dmg, p.pid, script, open_cmd="/usr/bin/true"))
    subprocess.run(["/bin/bash", str(script)], capture_output=True, timeout=60)
    return target, dmg, script


def test_el_instalador_reemplaza_el_app_y_limpia(tmp_path):
    target, dmg, script = _correr_instalador(tmp_path, src_existe=True)
    assert (target / "nuevo.txt").exists()           # el bundle nuevo está
    assert not (target / "viejo.txt").exists()       # el viejo se fue entero
    assert not dmg.exists()                          # DMG borrado tras el éxito
    assert not script.exists()                       # el script se recoge solo


def test_el_instalador_restaura_el_backup_si_la_copia_falla(tmp_path):
    """Si ditto falla (aquí: el src no existe), el usuario NUNCA se queda sin
    app: el backup vuelve a su sitio y el DMG se conserva como plan B."""
    target, dmg, script = _correr_instalador(tmp_path, src_existe=False)
    assert (target / "viejo.txt").exists()           # la app de antes, intacta
    assert dmg.exists()                              # el DMG sigue en Downloads


def test_stage_install_devuelve_none_fuera_de_un_bundle(tmp_path):
    """En dev (python -m, sin .app) no hay nada que reemplazar: None y el que
    llama cae al flujo manual. No debe ni intentar montar."""
    with patch("voooxly.updates.mount_dmg", side_effect=AssertionError("no montar")):
        assert updates.stage_install(tmp_path / "x.dmg", None, 1) is None


def test_stage_install_devuelve_none_si_el_montaje_falla(tmp_path):
    with patch("voooxly.updates.mount_dmg", return_value=None):
        got = updates.stage_install(
            tmp_path / "x.dmg", Path("/Applications/Voooxly.app"), 1)
    assert got is None


def test_stage_install_desmonta_si_el_dmg_no_trae_app(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    with patch("voooxly.updates.mount_dmg", return_value=mount), \
         patch("voooxly.updates.subprocess.run") as run:
        got = updates.stage_install(
            tmp_path / "x.dmg", Path("/Applications/Voooxly.app"), 1)
    assert got is None
    assert any("detach" in str(c) for c in run.call_args_list)


def test_stage_install_escribe_el_script_con_todo_dentro(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    (mount / "Voooxly.app").mkdir()
    with patch("voooxly.updates.mount_dmg", return_value=mount):
        script = updates.stage_install(
            tmp_path / "x.dmg", Path("/Applications/Voooxly.app"), 42)
    assert script is not None and script.exists()
    txt = script.read_text()
    assert "/Applications/Voooxly.app" in txt
    assert "kill -0 42" in txt
    script.unlink()


# --- "What's new": el pop-up post-update (feedback v1.6) ---

def test_whats_new_no_sale_en_instalacion_fresca():
    """Prefs vacío = primer arranque de la vida: el onboarding ya presenta la
    app y este pop-up solo estorbaría."""
    assert updates.should_show_whats_new({}, "1.7.0") is False
    assert updates.should_show_whats_new(None, "1.7.0") is False


def test_whats_new_sale_al_estrenar_version():
    prefs = {"last_run_version": "1.6.1", "sounds": True}
    assert updates.should_show_whats_new(prefs, "1.7.0") is True


def test_whats_new_sale_al_venir_de_una_version_sin_la_feature():
    """Quien actualiza desde 1.6.x no tiene last_run_version pero sí otras
    prefs: su primer arranque nuevo también debe contar qué cambió."""
    prefs = {"sounds": True, "update_prompted_version": "1.7.0"}
    assert updates.should_show_whats_new(prefs, "1.7.0") is True


def test_whats_new_no_se_repite_en_cada_arranque():
    prefs = {"last_run_version": "1.7.0"}
    assert updates.should_show_whats_new(prefs, "1.7.0") is False


def test_whats_new_tiene_notas_que_ensenar():
    assert updates.WHATS_NEW.strip()
