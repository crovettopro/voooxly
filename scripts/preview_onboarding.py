"""Interactive preview of the onboarding (without starting the whole app).

    ~/.voooxly/venv/bin/python scripts/preview_onboarding.py

The real welcome window opens: try the buttons (Microphone,
Accessibility, Continue → …), the yellow MINIMIZE button and closing via the
red cross. On close, the app returns to the Accessory policy and exits.

Note: launched from the terminal, macOS already leaves the window active; the
'dead buttons' bug was specific to the packaged .app under rumps on macOS 26,
which is exactly what setActivationPolicy(Regular) + the re-activation fix.
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
sys.path.insert(0, "src")

from AppKit import NSApplication  # noqa: E402

from voooxly import onboarding  # noqa: E402


def _done():
    NSApplication.sharedApplication().terminate_(None)


app = NSApplication.sharedApplication()
ctrl = onboarding.OnboardingController.alloc().initWithFinish_(_done)
ctrl.show()
app.run()
