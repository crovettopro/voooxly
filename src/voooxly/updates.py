"""Updates: queries an appcast.json, compares versions, downloads the DMG
and installs it by itself.

If there's a new version, the app notifies; on accepting, the DMG is downloaded
to ~/Downloads, mounted with hdiutil and a script OUTSIDE the bundle waits for
the app to die, replaces the .app (with a backup and rollback if ditto fails
halfway) and relaunches. The user no longer drags anything to Applications
(Jeff's v1.6 feedback). It isn't Sparkle: it's ~30 lines of bash over a DMG
that Gatekeeper already verified (notarized and downloaded over HTTPS). If any
step of the mount fails, it falls back to the old flow — open the mounted DMG
and let the user drag.

Any failure (no network, broken JSON, missing fields) is silent except in the
log: a broken update checker must never get in the way of dictation.
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

# CAREFUL: voooxly.vercel.app belongs to ANOTHER Vercel user; our production
# domain is voooxly.com (crovettopro's "voooxly" project).
APPCAST_URL = "https://voooxly.com/appcast.json"
# Outside the .app (running from the repo) there's no Info.plist to read from.
FALLBACK_VERSION = "1.9.2"

# Periodic re-check: the app queries again every CHECK_INTERVAL seconds
# while it's open (besides the startup check). 24 h covers whoever leaves it
# open for days/weeks without hammering.
CHECK_INTERVAL = 24 * 3600

# check_status() states: check() collapses "nothing new" and "error" into None,
# which is enough for the silent periodic check. The manual button needs to
# tell them apart to inform the user which of the two happened.
UPDATE_AVAILABLE = "available"
UP_TO_DATE = "up_to_date"
UPDATE_ERROR = "error"


def _parse(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in str(v).strip().split("."))
    except (ValueError, AttributeError):
        return None


def is_newer(remote: str, local: str) -> bool:
    """True if `remote` is a version later than `local`.

    Compares by numeric components: "1.10.0" is greater than "1.9.0", which
    a string comparison would get wrong.
    """
    r, l = _parse(remote), _parse(local)
    if r is None or l is None:
        return False
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


def current_version() -> str:
    """Bundle version read from Info.plist; FALLBACK_VERSION outside the .app."""
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


def _notes(data: dict) -> str:
    """Release notes in the UI language, English as the fallback.

    These are the only user-facing strings the app does NOT own — they come
    from the appcast — so they cannot go through i18n.t(). The server ships
    each language already written and this picks one; an appcast without
    "notes_es" (every one before 1.9.0) simply falls back, it never blanks.
    """
    from . import i18n

    if i18n.current_lang() == "es":
        traducidas = str(data.get("notes_es", "") or "").strip()
        if traducidas:
            return traducidas
    return str(data.get("notes", ""))


def check(url: str = APPCAST_URL, local: str | None = None) -> dict | None:
    """Returns {version, url, notes} if there's a newer version; None if not.

    Thin wrapper over check_status() for the periodic check, which reacts
    only to "there's news" and treats error and "you're up to date" the same
    (silence). The manual button uses check_status() to tell them apart.
    """
    status, info = check_status(url, local)
    return info if status == UPDATE_AVAILABLE else None


def check_status(
    url: str = APPCAST_URL, local: str | None = None
) -> tuple[str, dict | None]:
    """Like check() but distinguishes "nothing new" from "network error".

    Returns (status, info); info only when status == UPDATE_AVAILABLE.
    Any failure (no network, broken JSON, missing fields, HTTP error) is
    UPDATE_ERROR, it never raises — a broken checker must not get in the way.
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
            log.info("Update available: %s (installed: %s)", remote, local)
            return UPDATE_AVAILABLE, {
                "version": str(remote),
                "url": str(dmg),
                "notes": _notes(data),
            }
        return UP_TO_DATE, None
    except Exception as e:
        log.debug("Update check failed (ignored): %s", e)
        return UPDATE_ERROR, None


def download(
    url: str,
    version: str,
    dest_dir: Path | None = None,
    progress_cb=None,
) -> Path | None:
    """Downloads the DMG to `dest_dir` (~/Downloads by default). Path or None.

    It downloads to a .part and renames on finishing: a half-done DMG is never
    left with the final name. Any failure returns None and cleans the .part.
    `progress_cb(pct)` receives 0-100 if the server sends Content-Length.
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
        log.info("Update downloaded: %s", dest)
        return dest
    except Exception as e:
        log.warning("Update download failed: %s", e)
        try:
            part.unlink(missing_ok=True)
        except Exception:
            pass
        return None


# ---------- automatic install ----------

def _mount_point(plist_bytes: bytes) -> Path | None:
    """Mount point from the plist of `hdiutil attach -plist`. None if there's none.

    A DMG can list several system-entities (EFI partitions, etc.); only
    one carries mount-point and that's the one Finder would show.
    """
    try:
        data = plistlib.loads(plist_bytes)
        for ent in data.get("system-entities", []):
            mp = ent.get("mount-point")
            if mp:
                return Path(mp)
    except Exception as e:
        log.warning("Couldn't parse hdiutil output: %s", e)
    return None


def mount_dmg(dmg: Path) -> Path | None:
    """Mounts the DMG without opening a Finder window. Mount point or None."""
    try:
        r = subprocess.run(
            ["hdiutil", "attach", str(dmg), "-nobrowse", "-plist"],
            capture_output=True, timeout=120,
        )
        if r.returncode != 0:
            log.warning("hdiutil attach failed (%s): %s", r.returncode,
                        r.stderr.decode(errors="replace")[:300])
            return None
        return _mount_point(r.stdout)
    except Exception as e:
        log.warning("Couldn't mount %s: %s", dmg, e)
        return None


def find_app(mount: Path) -> Path | None:
    """The .app inside the mounted DMG (at the root, next to the /Applications alias)."""
    try:
        for child in sorted(Path(mount).iterdir()):
            if child.suffix == ".app" and child.is_dir():
                return child
    except Exception as e:
        log.warning("Couldn't list %s: %s", mount, e)
    return None


def installer_script(src_app: Path, target_app: Path, mount: Path, dmg: Path,
                     pid: int, script_path: Path,
                     open_cmd: str = "/usr/bin/open") -> str:
    """The bash that does the swap. Pure function (text) so it can be tested.

    Runs as its OWN process, outside the bundle: the bundle is exactly what
    gets deleted. It waits for the app to die (it closes itself after
    launching it), replaces the .app with a backup — if ditto fails halfway
    the backup comes back and the user is never left without an app — and
    relaunches. The DMG is only deleted if the copy went well: if anything
    failed, it stays in ~/Downloads as plan B.

    `open_cmd` exists for the tests, which RUN this script over fake folders
    and don't want /usr/bin/open to actually try opening a .app that isn't
    one.
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
  # The app never finished closing: impossible to replace it live. Show
  # the mounted DMG to install by hand, like always.
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
    """Mounts the DMG and writes out the swap script. Its path, or None.

    None means "couldn't be prepared" and the caller falls back to the manual
    flow (open the DMG and drag). target_app is the CURRENT bundle — in dev
    (python -m, no .app) there's nothing to replace and None is returned.
    """
    if not target_app or not str(target_app).endswith(".app"):
        return None
    mount = mount_dmg(dmg)
    if not mount:
        return None
    src = find_app(mount)
    if not src:
        # Odd DMG (no .app at the root): unmount and let the human decide.
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
        log.warning("Couldn't write the install script: %s", e)
        subprocess.run(["hdiutil", "detach", str(mount), "-force"],
                       capture_output=True, check=False)
        return None


# ---------- "What's new" after updating ----------

# What the post-update pop-up tells. Refreshed ON EVERY RELEASE together with
# FALLBACK_VERSION (same commit): it describes the version the user just
# started using, not the one to come.
# Refresh this in the SAME commit that bumps the version: it is the pop-up
# shown right after installing, and describing the previous version's
# behaviour is worse than saying nothing. test_updates pins the one claim
# this release retired.
WHATS_NEW = """\
• New AI engine: Grok (xAI). Pick it under AI engine › and the endpoint and
  model come filled in — you only paste your key.
• The "Detect automatically" button is gone. It read like a way back to
  automatic and was really a way to lose the engine you had connected.
• Your engine and your key stay exactly where they were: nothing to reconnect."""


def should_show_whats_new(prefs: dict | None, current: str) -> bool:
    """True if this launch premieres a version AND it isn't a fresh install.

    The marker is last_run_version in prefs.json (app.run() writes it after
    consulting this). An empty prefs = the first launch ever: there, the
    onboarding already introduces the app and the pop-up would only be in the
    way. Whoever comes from a version without this feature lacks the key but
    does have other prefs, so the first update after its premiere also shows
    its notes.
    """
    if not isinstance(prefs, dict) or not prefs:
        return False
    return prefs.get("last_run_version") != current


def should_notify(info: dict | None, already_notified: str | None) -> bool:
    """True if there's news AND we didn't already notify for this version.

    The periodic re-check's notice comes out once per version: if the app has
    been open 5 days and 1.3.0 comes out on day 1, it isn't announced again
    every 24 h. When it bumps to 1.4.0, it is.
    """
    return bool(info) and info["version"] != already_notified


def should_prompt(info: dict | None, prompted_version: str | None) -> bool:
    """True if there's news AND that version's pop-up wasn't already shown.

    Same arithmetic as should_notify but with another lifetime: here
    `prompted_version` comes from prefs.json, so the "Update
    available" alert doesn't repeat on every launch while the user decides
    to wait. When a newer version comes out, it asks again.
    """
    return bool(info) and info["version"] != prompted_version
