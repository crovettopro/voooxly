"""Entry point: `python -m voooxly`, or `voooxly` once installed."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import get_config


def _setup_logging(level: str):
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    # in .app bundle (console=False) stderr is lost -> also log to file
    try:
        import os
        from pathlib import Path

        log_dir = Path.home() / ".voooxly" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_dir / "voooxly.log", encoding="utf-8"))
    except Exception:
        pass
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
        force=True,
    )


def main():
    p = argparse.ArgumentParser(
        prog="voooxly", description="Pro-grade local dictation for macOS."
    )
    p.add_argument("--check", action="store_true", help="Check deps and backends, then exit.")
    p.add_argument("--devices", action="store_true", help="List input devices and exit.")
    p.add_argument("--onboarding", action="store_true",
                   help="Show the first-launch wizard and exit (to try it out).")
    p.add_argument("--log", default=None, help="Log level (DEBUG/INFO/WARNING)")
    args = p.parse_args()

    cfg = get_config()
    level = args.log or cfg.get("app.log_level", "INFO")
    _setup_logging(level)

    if args.devices:
        from . import audio

        for d in audio.list_input_devices():
            print(f"{d['index']}: {d['name']} ({d['channels']}ch)")
        return

    if args.check:
        from . import refine, stt

        print("Backends LLM:", refine.health())
        print("STT available (whisper.cpp):", stt.is_available())
        print("STT model cfg:", cfg.get("stt.model"))
        return

    if args.onboarding:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper

        from .onboarding import show_onboarding

        NSApplication.sharedApplication()
        show_onboarding(on_finish=AppHelper.stopEventLoop)
        AppHelper.runEventLoop()
        return

    # starts the menu-bar app
    from .app import VoooxlyApp

    VoooxlyApp().run()


if __name__ == "__main__":
    main()