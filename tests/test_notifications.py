"""Delivery of notices to the user.

Context: on macOS 26 the legacy NSUserNotification API (the one
rumps.notification uses) delivers NOTHING. Voooxly does not even appear in
com.apple.ncprefs.plist, so notices were silently discarded —
"Backend status" and "Usage stats" did nothing because the notice WAS the
entire feature. These tests keep the dead API from sneaking back in.
"""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "voooxly"


def test_no_rumps_notification_left_in_code():
    """rumps.notification does not deliver on macOS 26: any use is a lost notice."""
    culpables = []
    for py in SRC.rglob("*.py"):
        for n, linea in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            codigo = linea.split("#", 1)[0]  # comments MAY mention it
            if re.search(r"\brumps\.notification\s*\(", codigo):
                culpables.append(f"{py.name}:{n}")
    assert not culpables, (
        "rumps.notification no se entrega en macOS 26 — usa _alert() (modal, "
        f"para info que el usuario ha pedido) o _hud() (efímero): {culpables}"
    )


# health_summary() and "Backend status…" were removed: the AI engine submenu
# already carries the active engine in its own title ("AI engine — Groq"), so
# the modal said the same thing in backend jargon. refine.health() is still
# alive — setup_checks and `launch.sh --check` use it.
