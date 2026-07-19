"""Pausa la música mientras dictas y la reanuda al terminar.

Solo se toca lo que estaba SONANDO: si Spotify estaba en pausa, en pausa se
queda; si no está abierto, no se abre (por eso el 'is running' va primero:
un tell a una app cerrada la lanzaría). AppleScript sobre Spotify y Music
cubre a casi todo el mundo sin frameworks privados (MediaRemote se rompe en
cada versión de macOS); la primera vez macOS pide permiso de Automatización
para cada reproductor, una sola vez.

Todo es best-effort: un reproductor que no responde jamás debe estorbar al
dictado.
"""
from __future__ import annotations

import logging
import subprocess

log = logging.getLogger("voooxly.media")

# Reproductores con diccionario AppleScript de "player state" + pause/play.
PLAYERS = ("Spotify", "Music")

_PAUSE_IF_PLAYING = """
if application "{app}" is running then
    tell application "{app}"
        if player state is playing then
            pause
            return "paused"
        end if
    end tell
end if
return "no"
"""

_RESUME = """
if application "{app}" is running then
    tell application "{app}" to play
end if
"""


def _osascript(script: str) -> str:
    out = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True, timeout=5
    )
    return (out.stdout or "").strip()


def pause_playing() -> list[str]:
    """Pausa los reproductores que estén sonando; devuelve cuáles, para resume()."""
    paused: list[str] = []
    for app in PLAYERS:
        try:
            if _osascript(_PAUSE_IF_PLAYING.format(app=app)) == "paused":
                paused.append(app)
        except Exception as e:
            log.debug("No pude pausar %s: %s", app, e)
    if paused:
        log.info("Música pausada durante el dictado: %s", ", ".join(paused))
    return paused


def resume(players: list[str]) -> None:
    """Reanuda SOLO los reproductores que pause_playing() pausó."""
    for app in players:
        try:
            _osascript(_RESUME.format(app=app))
        except Exception as e:
            log.debug("No pude reanudar %s: %s", app, e)
