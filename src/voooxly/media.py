"""Pauses the music while you dictate and resumes it when done.

Only what was actually PLAYING is touched: if Spotify was paused, it stays
paused; if it isn't open, it isn't launched (that's why the 'is running' check
goes first: a tell to a closed app would launch it). AppleScript over Spotify
and Music covers almost everyone without private frameworks (MediaRemote breaks
on every macOS release); the first time, macOS asks for Automation permission
for each player, once.

Everything is best-effort: a player that doesn't respond must never get in the
way of dictation.
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
    """Pauses the players that are currently sounding; returns which ones, for resume()."""
    paused: list[str] = []
    for app in PLAYERS:
        try:
            if _osascript(_PAUSE_IF_PLAYING.format(app=app)) == "paused":
                paused.append(app)
        except Exception as e:
            log.debug("Couldn't pause %s: %s", app, e)
    if paused:
        log.info("Music paused during dictation: %s", ", ".join(paused))
    return paused


def resume(players: list[str]) -> None:
    """Resumes ONLY the players that pause_playing() paused."""
    for app in players:
        try:
            _osascript(_RESUME.format(app=app))
        except Exception as e:
            log.debug("Couldn't resume %s: %s", app, e)
