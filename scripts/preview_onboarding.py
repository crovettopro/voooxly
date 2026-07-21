"""Vista previa interactiva del onboarding (sin arrancar toda la app).

    ~/.voooxly/venv/bin/python scripts/preview_onboarding.py

Se abre la ventana real de bienvenida: prueba los botones (Microphone,
Accessibility, Continue → …), el botón amarillo de MINIMIZAR y cerrar con la
cruz roja. Al cerrar, la app vuelve a policy Accessory y termina.

Nota: lanzado desde la terminal, macOS ya deja la ventana activa; el bug de
'botones muertos' era específico del .app empaquetado bajo rumps en macOS 26,
que es justo lo que arreglan setActivationPolicy(Regular) + la re-activación.
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
