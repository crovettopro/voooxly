from pathlib import Path
from unittest.mock import MagicMock, patch

from voooxly import updates


def test_is_newer_compara_numericamente_no_alfabeticamente():
    assert updates.is_newer("1.10.0", "1.9.0") is True  # alphabetically "1.10" < "1.9"
    assert updates.is_newer("1.0.1", "1.0.0") is True
    assert updates.is_newer("1.0.0", "1.0.0") is False
    assert updates.is_newer("0.9.0", "1.0.0") is False


def test_is_newer_tolera_versiones_raras():
    assert updates.is_newer("1.2", "1.1.9") is True
    assert updates.is_newer("1.0", "1.0.0") is False
    assert updates.is_newer("basura", "1.0.0") is False
    assert updates.is_newer("1.0.0", "basura") is False


def test_check_returns_info_if_new_version():
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
    """A half-published appcast must not open a menu that leads nowhere."""
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


def test_check_never_raises_if_no_network():
    with patch("voooxly.updates.requests.get", side_effect=OSError("sin red")):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


def test_check_nunca_lanza_con_json_invalido():
    resp = MagicMock(ok=True)
    resp.json.side_effect = ValueError("no es json")
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


def test_check_returns_none_if_server_responds_error():
    resp = MagicMock(ok=False)
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://voooxly/appcast.json", "1.0.0") is None


# --- download ---

def _resp_con_bytes(data: bytes, with_length: bool = True):
    """Mock of requests.get(stream=True) usable as a context manager."""
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


def test_download_returns_none_and_cleans_part_if_fails(tmp_path):
    resp = _resp_con_bytes(b"xx")
    resp.iter_content = MagicMock(side_effect=OSError("conexión cortada"))
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.download("https://x/y.dmg", "1.0.1", tmp_path) is None
    assert list(tmp_path.iterdir()) == []  # neither DMG nor orphan .part


def test_download_sin_content_length_no_rompe_el_progreso(tmp_path):
    """GitHub sometimes serves without Content-Length: no pct without it, but still a DMG."""
    seen = []
    with patch(
        "voooxly.updates.requests.get",
        return_value=_resp_con_bytes(b"dmg-bytes", with_length=False),
    ):
        path = updates.download("https://x/y.dmg", "1.0.1", tmp_path, seen.append)
    assert path is not None and path.read_bytes() == b"dmg-bytes"
    assert seen == [100]  # only the final 100


# --- check_status: tells "nothing new" apart from "error" ---

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


def test_check_status_error_if_no_network():
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


def test_check_status_error_if_http_fails():
    resp = MagicMock(ok=False)
    with patch("voooxly.updates.requests.get", return_value=resp):
        status, info = updates.check_status("https://u", "1.0.0")
    assert status == updates.UPDATE_ERROR


# --- check() intact after refactor (regression) ---

def test_check_sigue_devolviendo_info_solo_si_hay_novedad():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0", "url": "https://x/y.dmg"}
    with patch("voooxly.updates.requests.get", return_value=resp):
        assert updates.check("https://u", "1.0.0")["version"] == "2.0.0"
    resp2 = MagicMock(ok=True)
    resp2.json.return_value = {"version": "1.0.0", "url": "https://x/y.dmg"}
    with patch("voooxly.updates.requests.get", return_value=resp2):
        assert updates.check("https://u", "1.0.0") is None


# --- should_notify: HUD only once per version ---

def test_should_notify_alerts_for_new_version():
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


# --- should_prompt: the pop-up shows ONCE per version, across launches ---

def test_should_prompt_asks_for_new_version():
    info = {"version": "1.5.0", "url": "u", "notes": ""}
    assert updates.should_prompt(info, None) is True
    assert updates.should_prompt(info, "1.4.0") is True


def test_should_prompt_no_repite_la_version_ya_preguntada():
    """The user chose "Later": the next launch cannot interrupt them again
    with the same alert. prefs persists the version already asked about."""
    info = {"version": "1.5.0", "url": "u", "notes": ""}
    assert updates.should_prompt(info, "1.5.0") is False


def test_should_prompt_false_sin_novedad():
    assert updates.should_prompt(None, None) is False
    assert updates.should_prompt(None, "1.5.0") is False


# --- automatic install: the DMG installs itself (v1.6 feedback) ---

def test_mount_point_parsea_el_plist_de_hdiutil():
    import plistlib

    plist = plistlib.dumps({"system-entities": [
        {"content-hint": "EFI"},                      # unmounted partition
        {"mount-point": "/Volumes/Voooxly"},
    ]})
    assert updates._mount_point(plist) == Path("/Volumes/Voooxly")


def test_mount_point_none_con_basura():
    assert updates._mount_point(b"esto no es un plist") is None
    assert updates._mount_point(b"") is None


def test_find_app_localiza_el_bundle(tmp_path):
    (tmp_path / "Voooxly.app").mkdir()
    (tmp_path / ".background").mkdir()               # typical DMG decoration
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
    """Runs the real installer script over make-believe folders.

    Returns (target, dmg, script) already executed. The pid belongs to a
    process that ALREADY died (the installer must not wait 30 s) and open_cmd
    is /usr/bin/true so nothing gets opened."""
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
    p.wait()   # dead pid: the script's wait loop exits on the first check

    script.write_text(updates.installer_script(
        src, target, mount, dmg, p.pid, script, open_cmd="/usr/bin/true"))
    subprocess.run(["/bin/bash", str(script)], capture_output=True, timeout=60)
    return target, dmg, script


def test_el_instalador_reemplaza_el_app_y_limpia(tmp_path):
    target, dmg, script = _correr_instalador(tmp_path, src_existe=True)
    assert (target / "nuevo.txt").exists()           # the new bundle is there
    assert not (target / "viejo.txt").exists()       # the old one is fully gone
    assert not dmg.exists()                          # DMG deleted after success
    assert not script.exists()                       # the script cleans up after itself


def test_installer_restores_backup_if_copy_fails(tmp_path):
    """If ditto fails (here: the src does not exist), the user is NEVER left
    without an app: the backup goes back in place and the DMG is kept as plan B."""
    target, dmg, script = _correr_instalador(tmp_path, src_existe=False)
    assert (target / "viejo.txt").exists()           # the previous app, intact
    assert dmg.exists()                              # the DMG is still in Downloads


def test_stage_install_devuelve_none_fuera_de_un_bundle(tmp_path):
    """In dev (python -m, no .app) there is nothing to replace: None and the
    caller falls back to the manual flow. It must not even try to mount."""
    with patch("voooxly.updates.mount_dmg", side_effect=AssertionError("no montar")):
        assert updates.stage_install(tmp_path / "x.dmg", None, 1) is None


def test_stage_install_returns_none_if_mount_fails(tmp_path):
    with patch("voooxly.updates.mount_dmg", return_value=None):
        got = updates.stage_install(
            tmp_path / "x.dmg", Path("/Applications/Voooxly.app"), 1)
    assert got is None


def test_stage_install_unmounts_if_dmg_has_no_app(tmp_path):
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


# --- "What's new": the post-update pop-up (v1.6 feedback) ---

def test_whats_new_no_sale_en_instalacion_fresca():
    """Empty prefs = very first launch ever: the onboarding already introduces
    the app and this pop-up would only get in the way."""
    assert updates.should_show_whats_new({}, "1.7.0") is False
    assert updates.should_show_whats_new(None, "1.7.0") is False


def test_whats_new_sale_al_estrenar_version():
    prefs = {"last_run_version": "1.6.1", "sounds": True}
    assert updates.should_show_whats_new(prefs, "1.7.0") is True


def test_whats_new_sale_al_venir_de_una_version_sin_la_feature():
    """Whoever updates from 1.6.x has no last_run_version but does have other
    prefs: their first launch on the new version must also tell what changed."""
    prefs = {"sounds": True, "update_prompted_version": "1.7.0"}
    assert updates.should_show_whats_new(prefs, "1.7.0") is True


def test_whats_new_does_not_repeat_on_every_start():
    prefs = {"last_run_version": "1.7.0"}
    assert updates.should_show_whats_new(prefs, "1.7.0") is False


def test_whats_new_tiene_notas_que_ensenar():
    assert updates.WHATS_NEW.strip()


def test_whats_new_describes_this_version_not_the_superseded_behaviour():
    """The pop-up every user sees right after installing must not describe the
    behaviour this version replaced.

    It drifted once already: 1.9.0 was about to ship telling people their
    corrections are "learned on your next dictation", which is exactly what
    stopped being true. Nothing caught it — the only assertion here was that
    the string was non-empty.
    """
    texto = updates.WHATS_NEW.lower()

    assert "next dictation" not in texto
    assert "grok" in texto  # la cabecera de ESTA versión, no la de la anterior


def test_whats_new_is_shown_in_spanish_too():
    """The full Spanish interface is a headline claim; this pop-up is the first
    thing a Spanish user sees after updating.

    Asserted against i18n.ES rather than a word in the copy: the body is
    rewritten wholesale every release, so pinning vocabulary from one version
    makes this fail for the wrong reason on the next — which is what it did
    going from 1.9.0 to 1.9.1. What must hold every release is that whatever
    the copy currently says has a Spanish entry.
    """
    from voooxly import i18n

    assert updates.WHATS_NEW in i18n.ES, "the new WHATS_NEW has no Spanish translation"
    i18n.set_lang("es")
    try:
        traducido = i18n.t(updates.WHATS_NEW)
        assert traducido != updates.WHATS_NEW
        assert traducido.strip()
    finally:
        i18n.set_lang("en")


# --- release notes in the user's language ---------------------------------

def test_check_prefers_the_spanish_notes_when_the_ui_speaks_spanish():
    """The update pop-up is a headline surface for the Spanish interface: the
    lead sentence was already translated, the notes body was not."""
    from voooxly import i18n

    resp = MagicMock(ok=True)
    resp.json.return_value = {
        "version": "2.0.0", "url": "https://x/y.dmg",
        "notes": "What's new", "notes_es": "Novedades",
    }
    i18n.set_lang("es")
    try:
        with patch("voooxly.updates.requests.get", return_value=resp):
            got = updates.check("https://voooxly/appcast.json", "1.0.0")
    finally:
        i18n.set_lang("en")

    assert got["notes"] == "Novedades"


def test_check_falls_back_to_english_notes_when_there_is_no_translation():
    """An older appcast has no notes_es, and a missing translation must never
    blank out the notes — English is the fallback, as everywhere else."""
    from voooxly import i18n

    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0", "url": "https://x/y.dmg",
                              "notes": "What's new"}
    i18n.set_lang("es")
    try:
        with patch("voooxly.updates.requests.get", return_value=resp):
            got = updates.check("https://voooxly/appcast.json", "1.0.0")
    finally:
        i18n.set_lang("en")

    assert got["notes"] == "What's new"


def test_check_ignores_the_spanish_notes_in_english():
    resp = MagicMock(ok=True)
    resp.json.return_value = {
        "version": "2.0.0", "url": "https://x/y.dmg",
        "notes": "What's new", "notes_es": "Novedades",
    }
    with patch("voooxly.updates.requests.get", return_value=resp):
        got = updates.check("https://voooxly/appcast.json", "1.0.0")

    assert got["notes"] == "What's new"


def test_the_update_prompt_lead_sentence_is_translated_like_the_manual_check():
    """_notify_update built its body with a bare f-string while
    check_now_message translated the equivalent line — same dialog title,
    half of it in English."""
    from voooxly import i18n

    i18n.set_lang("es")
    try:
        assert i18n.t("Voooxly {ver} is ready to install.").format(ver="1.9.0") == (
            "Voooxly 1.9.0 está lista para instalar."
        )
    finally:
        i18n.set_lang("en")


def test_whats_new_describes_what_1_9_2_actually_changed():
    """1.9.2 adds an engine and REMOVES a menu item, so the pop-up has to say
    both — a button vanishing without explanation reads as a bug, and nobody
    goes looking for an engine they don't know is there.

    Same failure mode this file already guards for 1.9.0 and 1.9.1: the string
    survives a release unchanged and tells everyone about the previous version.
    """
    texto = updates.WHATS_NEW.lower()

    assert "grok" in texto
    assert "detect automatically" in texto or "detectar" in texto
    # Whoever updates keeps their engine: saying so is what stops the removal
    # from reading as "it lost my key".
    assert "reconnect" in texto or "key" in texto
