"""Actualizaciones: consulta un appcast.json, compara versiones, descarga el DMG
y lo instala solo.

Si hay versión nueva, la app avisa; al aceptar se descarga el DMG a ~/Downloads,
se monta con hdiutil y un script FUERA del bundle espera a que la app muera,
reemplaza el .app (con backup y vuelta atrás si ditto falla a medias) y relanza.
El usuario ya no arrastra nada a Applications (feedback v1.6 de Jeff). No es
Sparkle: son ~30 líneas de bash sobre un DMG que Gatekeeper ya verificó
(notarizado y descargado por HTTPS). Si cualquier paso del montaje falla, se
cae al flujo antiguo — abrir el DMG montado y que el usuario arrastre.

Cualquier fallo (sin red, JSON roto, campos ausentes) es silencioso salvo en el
log: un comprobador de updates roto jamás debe estorbar al dictado.
"""
from __future__ import annotations

import logging
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

log = logging.getLogger("voooxly.updates")

# OJO: voooxly.vercel.app pertenece a OTRO usuario de Vercel; nuestro dominio
# de producción es voooxly.com (proyecto "voooxly" de crovettopro).
APPCAST_URL = "https://voooxly.com/appcast.json"
# Fuera del .app (ejecutando desde el repo) no hay Info.plist del que leer.
FALLBACK_VERSION = "1.7.0"

# Re-chequeo periódico: la app vuelve a consultar cada CHECK_INTERVAL segundos
# mientras esté abierta (además del check al arranque). 24 h cubre a quien la
# deja abierta días/semanas sin martilleo.
CHECK_INTERVAL = 24 * 3600

# Estados de check_status(): check() colapsa "sin novedad" y "error" en None,
# que basta para el check periódico silencioso. El botón manual necesita
# distinguirlos para decirle al usuario cuál de las dos pasó.
UPDATE_AVAILABLE = "available"
UP_TO_DATE = "up_to_date"
UPDATE_ERROR = "error"


def _parse(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in str(v).strip().split("."))
    except (ValueError, AttributeError):
        return None


def is_newer(remote: str, local: str) -> bool:
    """True si `remote` es una versión posterior a `local`.

    Compara por componentes numéricos: "1.10.0" es mayor que "1.9.0", cosa que
    una comparación de cadenas se equivocaría.
    """
    r, l = _parse(remote), _parse(local)
    if r is None or l is None:
        return False
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


def current_version() -> str:
    """Versión del bundle leída del Info.plist; FALLBACK_VERSION fuera del .app."""
    try:
        exe = Path(sys.executable).resolve()
        for parent in exe.parents:
            plist = parent / "Info.plist"
            if plist.exists():
                data = plistlib.loads(plist.read_bytes())
                v = data.get("CFBundleShortVersionString")
                if v:
                    return str(v)
    except Exception:
        pass
    return FALLBACK_VERSION


def check(url: str = APPCAST_URL, local: str | None = None) -> dict | None:
    """Devuelve {version, url, notes} si hay una versión más nueva; None si no.

    Wrapper fino sobre check_status() para el check periódico, que reacciona
    solo a "hay novedad" y trata error y "estás al día" igual (silencio). El
    botón manual usa check_status() para poder distinguirlos.
    """
    status, info = check_status(url, local)
    return info if status == UPDATE_AVAILABLE else None


def check_status(
    url: str = APPCAST_URL, local: str | None = None
) -> tuple[str, dict | None]:
    """Como check() pero distingue "sin novedad" de "error de red".

    Devuelve (status, info); info solo cuando status == UPDATE_AVAILABLE.
    Cualquier fallo (sin red, JSON roto, campos ausentes, HTTP error) es
    UPDATE_ERROR, nunca lanza — un comprobador roto no debe estorbar.
    """
    local = local or current_version()
    try:
        r = requests.get(url, timeout=8)
        if not r.ok:
            return UPDATE_ERROR, None
        data = r.json()
        remote = data.get("version")
        dmg = data.get("url")
        if not remote or not dmg:
            return UPDATE_ERROR, None
        if is_newer(str(remote), local):
            log.info("Update disponible: %s (instalada: %s)", remote, local)
            return UPDATE_AVAILABLE, {
                "version": str(remote),
                "url": str(dmg),
                "notes": str(data.get("notes", "")),
            }
        return UP_TO_DATE, None
    except Exception as e:
        log.debug("Comprobación de updates falló (ignorado): %s", e)
        return UPDATE_ERROR, None


def download(
    url: str,
    version: str,
    dest_dir: Path | None = None,
    progress_cb=None,
) -> Path | None:
    """Descarga el DMG a `dest_dir` (~/Downloads por defecto). Ruta o None.

    Se baja a un .part y se renombra al terminar: nunca queda un DMG a medias
    con el nombre final. Cualquier fallo devuelve None y limpia el .part.
    `progress_cb(pct)` recibe 0-100 si el servidor manda Content-Length.
    """
    dest_dir = dest_dir or Path.home() / "Downloads"
    dest = dest_dir / f"Voooxly-{version}.dmg"
    part = dest_dir / (dest.name + ".part")
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(min(99, done * 100 // total))
        part.replace(dest)
        if progress_cb:
            progress_cb(100)
        log.info("Update descargada: %s", dest)
        return dest
    except Exception as e:
        log.warning("Descarga de update falló: %s", e)
        try:
            part.unlink(missing_ok=True)
        except Exception:
            pass
        return None


# ---------- instalación automática ----------

def _mount_point(plist_bytes: bytes) -> Path | None:
    """Punto de montaje del plist de `hdiutil attach -plist`. None si no hay.

    Un DMG puede listar varias system-entities (particiones EFI, etc.); solo
    una trae mount-point y esa es la que Finder enseñaría.
    """
    try:
        data = plistlib.loads(plist_bytes)
        for ent in data.get("system-entities", []):
            mp = ent.get("mount-point")
            if mp:
                return Path(mp)
    except Exception as e:
        log.warning("No pude parsear la salida de hdiutil: %s", e)
    return None


def mount_dmg(dmg: Path) -> Path | None:
    """Monta el DMG sin abrir ventana de Finder. Punto de montaje o None."""
    try:
        r = subprocess.run(
            ["hdiutil", "attach", str(dmg), "-nobrowse", "-plist"],
            capture_output=True, timeout=120,
        )
        if r.returncode != 0:
            log.warning("hdiutil attach falló (%s): %s", r.returncode,
                        r.stderr.decode(errors="replace")[:300])
            return None
        return _mount_point(r.stdout)
    except Exception as e:
        log.warning("No pude montar %s: %s", dmg, e)
        return None


def find_app(mount: Path) -> Path | None:
    """El .app dentro del DMG montado (en la raíz, junto al alias a /Applications)."""
    try:
        for child in sorted(Path(mount).iterdir()):
            if child.suffix == ".app" and child.is_dir():
                return child
    except Exception as e:
        log.warning("No pude listar %s: %s", mount, e)
    return None


def installer_script(src_app: Path, target_app: Path, mount: Path, dmg: Path,
                     pid: int, script_path: Path,
                     open_cmd: str = "/usr/bin/open") -> str:
    """El bash que hace el swap. Función pura (texto) para poder testearla.

    Corre como proceso PROPIO, fuera del bundle: el bundle es justo lo que se
    borra. Espera a que muera la app (que se cierra sola tras lanzarlo),
    reemplaza el .app con backup — si ditto falla a medias el backup vuelve y
    el usuario nunca se queda sin app — y relanza. El DMG solo se borra si la
    copia salió bien: si algo falló, sigue en ~/Downloads como plan B.

    `open_cmd` existe para los tests, que EJECUTAN este script sobre carpetas
    de mentira y no quieren que /usr/bin/open intente abrir de verdad un .app
    que no lo es.
    """
    q = shlex.quote
    src, target = q(str(src_app)), q(str(target_app))
    mnt, dmg_q = q(str(mount)), q(str(dmg))
    opn = q(open_cmd)
    pid = int(pid)
    return f"""#!/bin/bash
# Instalador de Voooxly — generado por updates.installer_script().
set -u
for _ in $(seq 1 150); do
  kill -0 {pid} 2>/dev/null || break
  sleep 0.2
done
if kill -0 {pid} 2>/dev/null; then
  # La app no llegó a cerrarse: imposible reemplazarla en caliente. Se enseña
  # el DMG montado para instalar a mano, como toda la vida.
  {opn} {mnt}
  exit 1
fi
BACKUP="$(/usr/bin/mktemp -d)/previous.app"
if [ -e {target} ]; then
  /bin/mv {target} "$BACKUP" || exit 1
fi
if /usr/bin/ditto {src} {target}; then
  /bin/rm -rf "$BACKUP"
  OK=1
else
  /bin/rm -rf {target}
  [ -e "$BACKUP" ] && /bin/mv "$BACKUP" {target}
  OK=0
fi
/usr/bin/hdiutil detach {mnt} -force >/dev/null 2>&1
if [ "$OK" = "1" ]; then
  /bin/rm -f {dmg_q}
fi
{opn} {target}
/bin/rm -f {q(str(script_path))}
"""


def stage_install(dmg: Path, target_app: Path | None, pid: int) -> Path | None:
    """Monta el DMG y deja escrito el script de swap. Su ruta, o None.

    None significa "no se pudo preparar" y el que llama cae al flujo manual
    (abrir el DMG y arrastrar). target_app es el bundle ACTUAL — en dev
    (python -m, sin .app) no hay nada que reemplazar y se devuelve None.
    """
    if not target_app or not str(target_app).endswith(".app"):
        return None
    mount = mount_dmg(dmg)
    if not mount:
        return None
    src = find_app(mount)
    if not src:
        # DMG raro (sin .app en la raíz): se desmonta y que decida el humano.
        subprocess.run(["hdiutil", "detach", str(mount), "-force"],
                       capture_output=True, check=False)
        return None
    try:
        fd, tmp = tempfile.mkstemp(prefix="voooxly-install-", suffix=".sh")
        path = Path(tmp)
        with os.fdopen(fd, "w") as f:
            f.write(installer_script(src, Path(target_app), mount, dmg, pid, path))
        log.info("Instalador preparado: %s (app: %s)", path, src)
        return path
    except Exception as e:
        log.warning("No pude escribir el script de instalación: %s", e)
        subprocess.run(["hdiutil", "detach", str(mount), "-force"],
                       capture_output=True, check=False)
        return None


# ---------- "What's new" tras actualizar ----------

# Lo que cuenta el pop-up post-update. Se refresca EN CADA RELEASE junto a
# FALLBACK_VERSION (mismo commit): describe la versión que el usuario acaba
# de estrenar, no la que viene.
WHATS_NEW = """\
• Updates now install themselves — no more dragging to Applications.
• This "What's new" note appears after every update.
• New guide: menu bar icon › How to use Voooxly.
• Your shortcuts are now visible right in the menu bar."""


def should_show_whats_new(prefs: dict | None, current: str) -> bool:
    """True si este arranque estrena versión Y no es una instalación fresca.

    La marca es last_run_version en prefs.json (la escribe app.run() después
    de consultar esto). Un prefs vacío = primer arranque de la vida: ahí el
    onboarding ya presenta la app y el pop-up solo estorbaría. Quien viene de
    una versión sin esta feature no tiene la clave pero sí otras prefs, así
    que el primer update tras estrenarla también enseña sus notas.
    """
    if not isinstance(prefs, dict) or not prefs:
        return False
    return prefs.get("last_run_version") != current


def should_notify(info: dict | None, already_notified: str | None) -> bool:
    """True si hay novedad Y no avisamos ya para esta versión.

    El aviso del re-chequeo periódico sale una sola vez por versión: si la app
    lleva abierta 5 días y la 1.3.0 sale el día 1, no se anuncia de nuevo cada
    24 h. Cuando suba a 1.4.0, sí.
    """
    return bool(info) and info["version"] != already_notified


def should_prompt(info: dict | None, prompted_version: str | None) -> bool:
    """True si hay novedad Y el pop-up de esa versión no se enseñó ya.

    Misma aritmética que should_notify pero con otra vida: aquí
    `prompted_version` viene de prefs.json, así que el alert de "Update
    available" no se repite en cada arranque mientras el usuario decide
    esperar. Cuando salga una versión más nueva, vuelve a preguntar.
    """
    return bool(info) and info["version"] != prompted_version
