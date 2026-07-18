# Voxly Public Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convertir Voxly de app personal en un DMG notarizado que cualquiera pueda descargar, instalar y usar sin tocar la terminal.

**Architecture:** Cuatro piezas nuevas y aisladas: detección de requisitos (`setup_checks.py`), asistente visual de primer arranque (`onboarding.py`), aviso de versiones (`updates.py`) y el pipeline de release (`scripts/release.sh`). El código existente solo recibe enganches mínimos en `app.py`. La lógica pura se separa de la UI de AppKit para poder testearla sin ventanas.

**Tech Stack:** Python 3.12, PyObjC (AppKit/AVFoundation/ApplicationServices), rumps, PyInstaller, codesign + notarytool, hdiutil, pytest.

## Global Constraints

- Bundle identifier: `com.eduardocrovetto.dictador` — NO cambiar (los permisos TCC concedidos están ligados a él).
- Versión de lanzamiento: `1.0.0` en `CFBundleVersion` y `CFBundleShortVersionString`.
- Requisitos declarados al usuario: macOS 13.0+ y Apple Silicon (arm64).
- Todo texto visible por el usuario en **inglés**.
- Ventanas de AppKit: instanciar **solo en el hilo principal** (fuera de él, SIGABRT).
- Ningún fallo de red o de update puede impedir que la app dicte.
- Certificado de firma: `Developer ID Application` (el autofirmado "Dictador Dev" queda solo para `deploy.sh` de desarrollo).
- Entitlements: reutilizar `voxly.entitlements` (ya existe, no recrear).

---

### Task 1: Comprobación de actualizaciones

**Files:**
- Create: `src/dictador/updates.py`
- Create: `tests/test_updates.py`
- Modify: `pyproject.toml` (añadir grupo dev con pytest)

**Interfaces:**
- Consumes: nada.
- Produces: `is_newer(remote: str, local: str) -> bool`, `current_version() -> str`, `check(url: str, local: str) -> dict | None` (devuelve `{"version","url","notes"}` si hay versión nueva, `None` si no o si falla).

- [ ] **Step 1: Instalar pytest en el venv**

```bash
~/.dictador/venv/bin/pip install pytest
```

- [ ] **Step 2: Escribir el test que falla**

```python
# tests/test_updates.py
import json
from unittest.mock import patch, MagicMock
from dictador import updates


def test_is_newer_compara_numericamente_no_alfabeticamente():
    assert updates.is_newer("1.10.0", "1.9.0") is True   # alfabéticamente "1.10" < "1.9"
    assert updates.is_newer("1.0.1", "1.0.0") is True
    assert updates.is_newer("1.0.0", "1.0.0") is False
    assert updates.is_newer("0.9.0", "1.0.0") is False


def test_is_newer_tolera_versiones_raras():
    assert updates.is_newer("1.2", "1.1.9") is True
    assert updates.is_newer("basura", "1.0.0") is False
    assert updates.is_newer("1.0.0", "basura") is False


def test_check_devuelve_info_si_hay_version_nueva():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "2.0.0", "url": "https://x/y.dmg", "notes": "Nuevo"}
    with patch("dictador.updates.requests.get", return_value=resp):
        got = updates.check("https://voxly/appcast.json", "1.0.0")
    assert got["version"] == "2.0.0"
    assert got["url"] == "https://x/y.dmg"


def test_check_devuelve_none_si_estamos_al_dia():
    resp = MagicMock(ok=True)
    resp.json.return_value = {"version": "1.0.0", "url": "https://x/y.dmg"}
    with patch("dictador.updates.requests.get", return_value=resp):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None


def test_check_nunca_lanza_si_no_hay_red():
    with patch("dictador.updates.requests.get", side_effect=OSError("sin red")):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None


def test_check_nunca_lanza_con_json_invalido():
    resp = MagicMock(ok=True)
    resp.json.side_effect = ValueError("no es json")
    with patch("dictador.updates.requests.get", return_value=resp):
        assert updates.check("https://voxly/appcast.json", "1.0.0") is None
```

- [ ] **Step 3: Ejecutar el test y verificar que falla**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/pytest tests/test_updates.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'dictador.updates'`

- [ ] **Step 4: Implementar `updates.py`**

```python
"""Aviso de actualizaciones: consulta un appcast.json y compara versiones.

Sin auto-instalación: si hay versión nueva, la app muestra un ítem de menú que
abre la URL de descarga. Cualquier fallo (sin red, JSON roto, campos ausentes)
es silencioso salvo en el log — un comprobador de updates jamás debe estorbar.
"""
from __future__ import annotations

import logging
import plistlib
import sys
from pathlib import Path

import requests

log = logging.getLogger("dictador.updates")

APPCAST_URL = "https://voxly.vercel.app/appcast.json"
FALLBACK_VERSION = "1.0.0"


def _parse(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in str(v).strip().split("."))
    except (ValueError, AttributeError):
        return None


def is_newer(remote: str, local: str) -> bool:
    r, l = _parse(remote), _parse(local)
    if r is None or l is None:
        return False
    n = max(len(r), len(l))
    return r + (0,) * (n - len(r)) > l + (0,) * (n - len(l))


def current_version() -> str:
    """Versión del bundle (Info.plist) o FALLBACK_VERSION fuera del .app."""
    try:
        # .../Voxly.app/Contents/MacOS/Voxly -> .../Contents/Info.plist
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
    """Devuelve {version,url,notes} si hay una versión más nueva; None si no."""
    local = local or current_version()
    try:
        r = requests.get(url, timeout=8)
        if not r.ok:
            return None
        data = r.json()
        remote = data.get("version")
        dmg = data.get("url")
        if not remote or not dmg or not is_newer(str(remote), local):
            return None
        log.info("Update disponible: %s (tenemos %s)", remote, local)
        return {"version": str(remote), "url": str(dmg), "notes": str(data.get("notes", ""))}
    except Exception as e:
        log.debug("Comprobación de updates falló (ignorado): %s", e)
        return None
```

- [ ] **Step 5: Ejecutar los tests y verificar que pasan**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/pytest tests/test_updates.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Añadir pytest como dependencia de desarrollo**

En `pyproject.toml`, tras el bloque `[project.scripts]`:

```toml
[dependency-groups]
dev = ["pytest>=8.0"]
```

- [ ] **Step 7: Commit**

```bash
git add src/dictador/updates.py tests/test_updates.py pyproject.toml
git commit -m "Aviso de actualizaciones: appcast.json + comparación de versiones"
```

---

### Task 2: Detección de requisitos del sistema

**Files:**
- Create: `src/dictador/setup_checks.py`
- Create: `tests/test_setup_checks.py`

**Interfaces:**
- Consumes: `stt.find_model()`, `refine.health()` (ya existen).
- Produces: `has_microphone() -> bool`, `request_microphone(callback) -> None`, `has_accessibility() -> bool`, `open_accessibility_settings() -> None`, `has_model() -> bool`, `has_ai_engine() -> bool`, `Check` (dataclass con `key: str`, `label: str`, `ok: bool`, `blocking: bool`), `check_all() -> list[Check]`, `needs_setup() -> bool`.

Claves usadas por Task 3: `"mic"`, `"accessibility"`, `"model"`, `"ai"`.

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_setup_checks.py
from unittest.mock import patch
from dictador import setup_checks


def test_check_all_devuelve_los_cuatro_pasos_en_orden():
    with patch.object(setup_checks, "has_microphone", return_value=True), \
         patch.object(setup_checks, "has_accessibility", return_value=True), \
         patch.object(setup_checks, "has_model", return_value=True), \
         patch.object(setup_checks, "has_ai_engine", return_value=True):
        checks = setup_checks.check_all()
    assert [c.key for c in checks] == ["mic", "accessibility", "model", "ai"]
    assert all(c.ok for c in checks)


def test_el_motor_de_ia_no_es_bloqueante():
    """Sin IA la app dicta igual en modo Verbatim: no debe impedir el arranque."""
    with patch.object(setup_checks, "has_microphone", return_value=True), \
         patch.object(setup_checks, "has_accessibility", return_value=True), \
         patch.object(setup_checks, "has_model", return_value=True), \
         patch.object(setup_checks, "has_ai_engine", return_value=False):
        checks = {c.key: c for c in setup_checks.check_all()}
        assert checks["ai"].blocking is False
        assert setup_checks.needs_setup() is False


def test_needs_setup_true_si_falta_un_requisito_bloqueante():
    with patch.object(setup_checks, "has_microphone", return_value=True), \
         patch.object(setup_checks, "has_accessibility", return_value=False), \
         patch.object(setup_checks, "has_model", return_value=True), \
         patch.object(setup_checks, "has_ai_engine", return_value=True):
        assert setup_checks.needs_setup() is True


def test_has_model_delega_en_stt():
    with patch("dictador.stt.find_model", return_value="/ruta/modelo.bin"):
        assert setup_checks.has_model() is True
    with patch("dictador.stt.find_model", return_value=None):
        assert setup_checks.has_model() is False


def test_has_ai_engine_true_si_algun_backend_esta_vivo():
    with patch("dictador.refine.health", return_value={"ollama": False, "claude": True, "openai": False}):
        assert setup_checks.has_ai_engine() is True
    with patch("dictador.refine.health", return_value={"ollama": False, "claude": False, "openai": False}):
        assert setup_checks.has_ai_engine() is False
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/pytest tests/test_setup_checks.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'dictador.setup_checks'`

- [ ] **Step 3: Implementar `setup_checks.py`**

```python
"""Estado de los requisitos del sistema: micrófono, Accesibilidad, modelo y motor IA.

Lógica separada de la ventana de onboarding para poder testearla sin AppKit.
Se comprueba en tiempo real (no con un flag guardado): si el usuario revoca un
permiso en Ajustes, la app debe enterarse.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger("dictador.setup")

ACCESSIBILITY_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)


@dataclass
class Check:
    key: str
    label: str
    ok: bool
    blocking: bool


def has_microphone() -> bool:
    """True si el permiso de micrófono está concedido (estado 3 = authorized)."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        return int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)) == 3
    except Exception as e:
        log.debug("No pude leer el estado del micrófono: %s", e)
        return False


def request_microphone(callback=None) -> None:
    """Dispara el prompt del sistema. El callback recibe True/False (hilo aparte)."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        def _done(granted):
            if callback:
                try:
                    callback(bool(granted))
                except Exception:
                    pass

        AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, _done)
    except Exception as e:
        log.warning("No pude pedir permiso de micrófono: %s", e)
        if callback:
            callback(False)


def has_accessibility() -> bool:
    """True si la app está en la lista de Accesibilidad (necesaria para hotkey y pegado)."""
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception as e:
        log.debug("No pude leer el estado de Accesibilidad: %s", e)
        return False


def open_accessibility_settings() -> None:
    try:
        subprocess.run(["open", ACCESSIBILITY_PANE], check=False, timeout=5)
    except Exception as e:
        log.warning("No pude abrir Ajustes: %s", e)


def has_model() -> bool:
    from . import stt

    return bool(stt.find_model())


def has_ai_engine() -> bool:
    from . import refine

    try:
        return any(refine.health().values())
    except Exception:
        return False


def check_all() -> list[Check]:
    return [
        Check("mic", "Microphone access", has_microphone(), blocking=True),
        Check("accessibility", "Accessibility access", has_accessibility(), blocking=True),
        Check("model", "Speech model", has_model(), blocking=True),
        Check("ai", "AI engine (optional)", has_ai_engine(), blocking=False),
    ]


def needs_setup() -> bool:
    """True si falta algo imprescindible para dictar."""
    return any(not c.ok for c in check_all() if c.blocking)
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/pytest tests/test_setup_checks.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Verificar contra el sistema real**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/python -c "from dictador import setup_checks; [print(c) for c in setup_checks.check_all()]"`
Expected: cuatro líneas `Check(...)`; `model` debe salir `ok=True` (el modelo está descargado) y `ai` `ok=True` (Ollama corriendo).

- [ ] **Step 6: Añadir dependencia de AVFoundation**

En `pyproject.toml`, en `dependencies`, tras `pyobjc-framework-ApplicationServices`:

```toml
    "pyobjc-framework-AVFoundation>=10.0",
```

Instalar: `~/.dictador/venv/bin/pip install "pyobjc-framework-AVFoundation>=10.0"`

- [ ] **Step 7: Commit**

```bash
git add src/dictador/setup_checks.py tests/test_setup_checks.py pyproject.toml
git commit -m "Detección de requisitos: micrófono, Accesibilidad, modelo y motor IA"
```

---

### Task 3: Ventana de onboarding

**Files:**
- Create: `src/dictador/onboarding.py`

**Interfaces:**
- Consumes: `setup_checks` (Task 2) completo, `stt.ensure_model(progress_cb)`.
- Produces: `show_onboarding(on_finish=None) -> None` (debe llamarse desde el hilo principal), `OnboardingWindow`.

Sin tests automáticos: es una ventana de AppKit. Se prueba lanzándola aislada (Step 4) y en el arranque real (Task 4).

- [ ] **Step 1: Implementar `onboarding.py`**

```python
"""Asistente de primer arranque: guía los permisos y la descarga del modelo.

Una sola ventana con una fila por requisito, cada una con su botón de acción.
El estado se re-comprueba con un temporizador (1s): cuando el usuario concede
Accesibilidad en Ajustes, la fila se marca sola sin tener que reiniciar.

RESTRICCIÓN: NSWindow solo puede instanciarse en el hilo principal. Igual que
overlay.py — hacerlo desde otro hilo aborta el proceso con SIGABRT.
"""
from __future__ import annotations

import logging
import threading

from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFont,
    NSMakeRect,
    NSProgressIndicator,
    NSTextField,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject, NSTimer

from . import setup_checks, stt

log = logging.getLogger("dictador.onboarding")

W, H = 520, 470
ROW_H = 72

STEPS = [
    ("mic", "Microphone", "Voxly needs the microphone to hear your dictation.", "Allow"),
    ("accessibility", "Accessibility", "Lets Voxly use the hotkey and paste into any app.", "Open Settings"),
    ("model", "Speech model", "One-time 547 MB download. Runs entirely on your Mac.", "Download"),
    ("ai", "AI engine (optional)", "Ollama or an API key cleans up your dictation. Works without it.", "Check again"),
]


class OnboardingWindow(NSObject):
    def initWithFinish_(self, on_finish):
        self = objc_super_init(self)
        if self is None:
            return None
        self._on_finish = on_finish
        self._rows = {}
        self._downloading = False
        self._build()
        return self

    def _build(self):
        rect = NSMakeRect(0, 0, W, H)
        self._win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False
        )
        self._win.setTitle_("Welcome to Voxly")
        self._win.setReleasedWhenClosed_(False)
        content = self._win.contentView()

        title = _label(NSMakeRect(24, H - 66, W - 48, 28), "Let's get you dictating", 20, bold=True)
        content.addSubview_(title)
        sub = _label(NSMakeRect(24, H - 92, W - 48, 20),
                     "Three quick things and you're set.", 12, secondary=True)
        content.addSubview_(sub)

        y = H - 130
        for key, name, desc, action in STEPS:
            y -= ROW_H
            row = NSView.alloc().initWithFrame_(NSMakeRect(24, y, W - 48, ROW_H - 8))
            status = _label(NSMakeRect(0, 34, 24, 20), "○", 15)
            row.addSubview_(status)
            row.addSubview_(_label(NSMakeRect(26, 34, 260, 20), name, 13, bold=True))
            row.addSubview_(_label(NSMakeRect(26, 12, W - 130, 32), desc, 11, secondary=True))

            btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 168, 30, 120, 26))
            btn.setTitle_(action)
            btn.setBezelStyle_(1)
            btn.setTarget_(self)
            btn.setAction_(_selector_for(key))
            row.addSubview_(btn)

            bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(26, 6, W - 200, 12))
            bar.setStyle_(0)
            bar.setIndeterminate_(False)
            bar.setMinValue_(0.0)
            bar.setMaxValue_(100.0)
            bar.setHidden_(True)
            row.addSubview_(bar)

            content.addSubview_(row)
            self._rows[key] = {"status": status, "button": btn, "bar": bar}

        self._hint = _label(NSMakeRect(24, 24, W - 48, 36),
                            "Tip: hold the right Command key and speak.", 12, secondary=True)
        self._hint.setHidden_(True)
        content.addSubview_(self._hint)

        self._done = NSButton.alloc().initWithFrame_(NSMakeRect(W - 140, 20, 116, 30))
        self._done.setTitle_("Start dictating")
        self._done.setBezelStyle_(1)
        self._done.setTarget_(self)
        self._done.setAction_("finish:")
        content.addSubview_(self._done)

        self._refresh()
        self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True
        )

    # --- acciones (una por paso; los selectores los enruta _selector_for) ---
    def mic_(self, _sender):
        setup_checks.request_microphone(lambda ok: log.info("Micrófono concedido: %s", ok))

    def accessibility_(self, _sender):
        setup_checks.open_accessibility_settings()

    def model_(self, _sender):
        if self._downloading:
            return
        self._downloading = True
        row = self._rows["model"]
        row["button"].setEnabled_(False)
        row["bar"].setHidden_(False)

        def _work():
            def _progress(pct):
                row["bar"].performSelectorOnMainThread_withObject_waitUntilDone_(
                    "setDoubleValue:", float(pct), False
                )
            try:
                stt.ensure_model(progress_cb=_progress)
            except Exception as e:
                log.error("Descarga del modelo falló: %s", e)
            finally:
                self._downloading = False

        threading.Thread(target=_work, daemon=True).start()

    def ai_(self, _sender):
        from . import refine

        refine.detect_backend(force=True)
        self._refresh()

    def tick_(self, _timer):
        self._refresh()

    def finish_(self, _sender):
        try:
            self._timer.invalidate()
        except Exception:
            pass
        self._win.orderOut_(None)
        if self._on_finish:
            try:
                self._on_finish()
            except Exception:
                pass

    def show(self):
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self._win.center()
        self._win.makeKeyAndOrderFront_(None)

    def _refresh(self):
        blocking_ok = True
        for check in setup_checks.check_all():
            row = self._rows.get(check.key)
            if not row:
                continue
            row["status"].setStringValue_("●" if check.ok else "○")
            row["status"].setTextColor_(
                NSColor.systemGreenColor() if check.ok else NSColor.tertiaryLabelColor()
            )
            row["button"].setEnabled_(not check.ok or check.key == "ai")
            if check.key == "model" and check.ok:
                row["bar"].setHidden_(True)
            if check.blocking and not check.ok:
                blocking_ok = False
        self._done.setEnabled_(blocking_ok)
        self._hint.setHidden_(not blocking_ok)


def _label(rect, text, size, bold=False, secondary=False):
    f = NSTextField.alloc().initWithFrame_(rect)
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    if secondary:
        f.setTextColor_(NSColor.secondaryLabelColor())
    return f


def _selector_for(key: str) -> str:
    return {"mic": "mic:", "accessibility": "accessibility:", "model": "model:", "ai": "ai:"}[key]


def objc_super_init(obj):
    return NSObject.init(obj)


_window = None


def show_onboarding(on_finish=None) -> None:
    """Muestra el asistente. DEBE llamarse desde el hilo principal."""
    global _window
    try:
        _window = OnboardingWindow.alloc().initWithFinish_(on_finish)
        _window.show()
    except Exception as e:
        log.error("No pude mostrar el onboarding: %s", e)
```

- [ ] **Step 2: Registrar los selectores en PyObjC**

PyObjC deriva los selectores del nombre del método (`mic_` → `mic:`), así que los
métodos ya coinciden con lo que devuelve `_selector_for`. Verificar que la clase
hereda de `NSObject` y que `initWithFinish_` devuelve `self`.

- [ ] **Step 3: Añadir el flag `--onboarding` para probar la ventana aislada**

En `src/dictador/__main__.py`, tras el argumento `--devices`:

```python
    p.add_argument("--onboarding", action="store_true", help="Muestra el asistente de primer arranque y sale.")
```

Y antes de arrancar la app (tras el bloque de `--check`):

```python
    if args.onboarding:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper

        from .onboarding import show_onboarding

        NSApplication.sharedApplication()
        show_onboarding(on_finish=lambda: AppHelper.stopEventLoop())
        AppHelper.runEventLoop()
        return
```

- [ ] **Step 4: Probar la ventana**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/python -m dictador --onboarding`
Expected: se abre una ventana "Welcome to Voxly" con cuatro filas; las que ya están cumplidas (modelo, IA) muestran ● verde; "Start dictating" está habilitado y cierra la ventana.

- [ ] **Step 5: Commit**

```bash
git add src/dictador/onboarding.py src/dictador/__main__.py
git commit -m "Asistente de primer arranque: permisos, modelo y motor IA guiados"
```

---

### Task 4: Integración en la app y subida de versión

**Files:**
- Modify: `src/dictador/app.py` (arranque en `run()`, menú en `_build_menu`)
- Modify: `Voxly.spec` (versión 1.0.0)

**Interfaces:**
- Consumes: `setup_checks.needs_setup()`, `onboarding.show_onboarding()`, `updates.check()`.
- Produces: nada para tareas posteriores.

- [ ] **Step 1: Importar los módulos nuevos en `app.py`**

En la línea de imports del paquete:

```python
from . import audio, modes, output, refine, setup_checks, stt, updates
```

- [ ] **Step 2: Añadir el ítem de update al menú**

En `_build_menu`, junto a `self.quit`:

```python
        # Oculto hasta que el comprobador encuentre una versión nueva.
        self.update_item = rumps.MenuItem("Update available", callback=self._open_update)
        self.update_item._menuitem.setHidden_(True)
        self._update_url = ""
```

Y en la lista `self.menu`, antes de `self.quit`:

```python
            self.update_item,
```

- [ ] **Step 3: Añadir el callback de update**

Como método de `DictadorApp`:

```python
    def _open_update(self, _sender):
        if self._update_url:
            subprocess.run(["open", self._update_url], check=False)
```

Con `import subprocess` en la cabecera del módulo.

- [ ] **Step 4: Mostrar el onboarding al arrancar si falta algo**

En `run()`, después de `self._overlay.build()` y **antes** de `super().run()`:

```python
        # Primer arranque (o permiso revocado): el asistente explica qué falta.
        # Va aquí, en el hilo principal, porque NSWindow no puede crearse fuera.
        try:
            if setup_checks.needs_setup():
                from .onboarding import show_onboarding

                show_onboarding()
        except Exception as e:
            log.warning("No pude mostrar el onboarding: %s", e)
```

- [ ] **Step 5: Comprobar updates en el warmup**

Al final de `_warmup`, antes del bucle de keepalive:

```python
        # Aviso de versión nueva (silencioso si falla).
        try:
            info = updates.check()
            if info:
                self._update_url = info["url"]
                self.update_item.title = f"Update to {info['version']}"
                self.update_item._menuitem.setHidden_(False)
        except Exception:
            pass
```

- [ ] **Step 6: Subir la versión a 1.0.0**

En `Voxly.spec`, dentro de `info_plist`:

```python
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
```

- [ ] **Step 7: Verificar que la app sigue funcionando**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/python -c "
from dictador import app, setup_checks, updates
print('imports OK')
print('needs_setup:', setup_checks.needs_setup())
print('update:', updates.check())
"`
Expected: `imports OK`, `needs_setup: False`, `update: None` (no hay appcast publicado todavía).

- [ ] **Step 8: Ejecutar toda la suite de tests**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/pytest tests/ -v`
Expected: PASS (11 tests)

- [ ] **Step 9: Commit**

```bash
git add src/dictador/app.py Voxly.spec
git commit -m "Integrar onboarding y aviso de updates; versión 1.0.0"
```

---

### Task 5: Pipeline de release firmado y notarizado

**Files:**
- Create: `scripts/release.sh`
- Create: `docs/RELEASING.md`

**Interfaces:**
- Consumes: `Voxly.spec`, `voxly.entitlements` (existentes).
- Produces: `dist/Voxly-<version>.dmg` notarizado y stapleado.

- [ ] **Step 1: Escribir `scripts/release.sh`**

```bash
#!/bin/bash
# Release público de Voxly: build + firma Developer ID + notarización + DMG.
#
# Requisitos (una sola vez, ver docs/RELEASING.md):
#   - Certificado "Developer ID Application: <nombre> (<TEAMID>)" en el llavero
#   - Perfil de notarización guardado:
#       xcrun notarytool store-credentials voxly --apple-id ... --team-id ... --password ...
#
# Uso: ./scripts/release.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${DICTADOR_VENV:-$HOME/.dictador/venv}"
PROFILE="${NOTARY_PROFILE:-voxly}"
APP="$ROOT/dist/Voxly.app"
ENTITLEMENTS="$ROOT/voxly.entitlements"

cd "$ROOT"

IDENTITY="$(security find-identity -v -p codesigning | grep "Developer ID Application" | head -1 | sed -E 's/.*"(.*)"/\1/')"
[ -n "$IDENTITY" ] || { echo "ERROR: no hay certificado 'Developer ID Application'. Ver docs/RELEASING.md"; exit 1; }
echo "→ Identidad: $IDENTITY"

VERSION="$(grep -E '"CFBundleShortVersionString"' Voxly.spec | head -1 | sed -E 's/.*: *"([^"]+)".*/\1/')"
[ -n "$VERSION" ] || { echo "ERROR: no pude leer la versión de Voxly.spec"; exit 1; }
echo "→ Versión: $VERSION"

echo "→ Compilando…"
rm -rf "$ROOT/dist/Voxly.app"
"$VENV/bin/pyinstaller" Voxly.spec --noconfirm | tail -1

# iCloud re-inyecta xattrs que rompen la firma ("resource fork ... not allowed").
echo "→ Limpiando atributos extendidos…"
xattr -cr "$APP"

# Firma de DENTRO AFUERA: los .dylib y binarios anidados primero, el bundle al final.
# Los libggml-* se cargan por dlopen y necesitan firma propia o la notarización falla.
echo "→ Firmando binarios internos…"
find "$APP/Contents" \( -name "*.dylib" -o -name "*.so" -o -type f -perm -111 \) -print0 |
  while IFS= read -r -d '' f; do
    case "$(file -b "$f")" in
      Mach-O*) codesign --force --timestamp --options runtime \
                 --entitlements "$ENTITLEMENTS" -s "$IDENTITY" "$f" >/dev/null 2>&1 || true ;;
    esac
  done

echo "→ Firmando el bundle…"
codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" \
  -s "$IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"

echo "→ Notarizando la app…"
ZIP="$ROOT/dist/Voxly-$VERSION.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$APP"
rm -f "$ZIP"

echo "→ Construyendo el DMG…"
DMG="$ROOT/dist/Voxly-$VERSION.dmg"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Voxly" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo "→ Firmando y notarizando el DMG…"
codesign --force --timestamp -s "$IDENTITY" "$DMG"
xcrun notarytool submit "$DMG" --keychain-profile "$PROFILE" --wait
xcrun stapler staple "$DMG"

echo "→ Verificación final (lo que ejecuta Gatekeeper en el Mac del usuario):"
spctl -a -vvv -t install "$DMG"

echo
echo "✅ Listo: $DMG"
echo "   Súbelo a GitHub Releases y actualiza web/appcast.json a la versión $VERSION."
```

- [ ] **Step 2: Hacerlo ejecutable**

```bash
chmod +x scripts/release.sh
```

- [ ] **Step 3: Verificar que aborta limpiamente sin certificado**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && ./scripts/release.sh`
Expected: `ERROR: no hay certificado 'Developer ID Application'. Ver docs/RELEASING.md` y salida con código 1 (correcto hasta que se cree el certificado).

- [ ] **Step 4: Escribir `docs/RELEASING.md`**

Documento con los pasos manuales que requieren la cuenta de Apple:
1. Crear el certificado Developer ID Application (developer.apple.com → Certificates → `+` → Developer ID Application), descargarlo y hacer doble clic para instalarlo en el llavero.
2. Crear una contraseña específica de app en appleid.apple.com → Sign-In and Security → App-Specific Passwords.
3. Guardar el perfil de notarización:
   `xcrun notarytool store-credentials voxly --apple-id <email> --team-id 96Y828UCBL --password <app-specific-password>`
4. Ejecutar `./scripts/release.sh`.
5. Subir el DMG a GitHub Releases.
6. Actualizar `web/appcast.json` con la versión y la URL del DMG, y desplegar la web.

- [ ] **Step 5: Commit**

```bash
git add scripts/release.sh docs/RELEASING.md
git commit -m "Pipeline de release: firma Developer ID, notarización y DMG"
```

---

### Task 6: Landing de descarga y appcast

**Files:**
- Create: `web/index.html`
- Create: `web/appcast.json`
- Create: `web/vercel.json`

**Interfaces:**
- Consumes: la URL del DMG en GitHub Releases.
- Produces: `https://voxly.vercel.app/appcast.json` (lo consume `updates.check()`).

- [ ] **Step 1: Escribir `web/index.html`**

Página estática autocontenida (CSS inline, sin dependencias externas), con:
- Titular: "Dictate anywhere on your Mac. Locally."
- Tres bullets: **Private** (tu voz nunca sale del Mac), **Fast** (~1s), **Free**.
- Botón de descarga al DMG de GitHub Releases.
- Requisitos visibles: "macOS 13+ · Apple Silicon".
- Sección de tres pasos: descarga → concede permisos → mantén Cmd derecha y habla.
- Soporte de tema claro y oscuro con `prefers-color-scheme`.

- [ ] **Step 2: Escribir `web/appcast.json`**

```json
{
  "version": "1.0.0",
  "url": "https://github.com/eduardocrovetto/voxly/releases/latest/download/Voxly-1.0.0.dmg",
  "notes": "First public release."
}
```

- [ ] **Step 3: Escribir `web/vercel.json`**

```json
{
  "headers": [
    {
      "source": "/appcast.json",
      "headers": [{ "key": "Cache-Control", "value": "public, max-age=300" }]
    }
  ]
}
```

- [ ] **Step 4: Verificar el HTML localmente**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local/web && ~/.dictador/venv/bin/python -m http.server 8099`
Abrir `http://localhost:8099` y comprobar que se ve bien en claro y oscuro.

- [ ] **Step 5: Verificar que `updates.check()` lee el appcast servido**

Run: `cd /Users/eduardocrovetto/Desktop/code-edu/dictado-local && PYTHONPATH=src ~/.dictador/venv/bin/python -c "
from dictador import updates
print('con 0.9.0 instalado:', updates.check('http://localhost:8099/appcast.json', '0.9.0'))
print('con 1.0.0 instalado:', updates.check('http://localhost:8099/appcast.json', '1.0.0'))
"`
Expected: la primera línea devuelve el dict con la versión 1.0.0; la segunda `None`.

- [ ] **Step 6: Commit**

```bash
git add web/
git commit -m "Landing de descarga y appcast.json"
```

---

## Estado final esperado

Tras las seis tareas, el repositorio contiene todo lo necesario para publicar. Lo
único que queda es lo que exige la cuenta de Apple del usuario y no puede
automatizarse: crear el certificado Developer ID, guardar el perfil de
notarización, ejecutar `./scripts/release.sh`, subir el DMG a GitHub Releases y
desplegar `web/` en Vercel. Todo ello está documentado paso a paso en
`docs/RELEASING.md`.

La verificación definitiva —cuenta de usuario nueva en el Mac, instalar desde el
DMG y dictar sin abrir la terminal— solo puede hacerse una vez el DMG esté
notarizado.
