"""Estado de los requisitos del sistema: micrófono, Accesibilidad, modelo y motor IA.

La lógica va separada de la ventana de onboarding para poder testearla sin AppKit.

Todo se comprueba en tiempo real, no con un flag guardado en preferencias: si el
usuario revoca un permiso en Ajustes (o lo pierde tras reinstalar la app, que
invalida la firma), Voooxly tiene que enterarse y volver a guiarle.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger("voooxly.setup")

ACCESSIBILITY_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
MICROPHONE_PANE = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
)
# AVAuthorizationStatus: notDetermined(0), restricted(1), denied(2), authorized(3)
_AV_NOT_DETERMINED = 0
_AV_AUTHORIZED = 3


@dataclass
class Check:
    key: str
    label: str
    ok: bool
    blocking: bool


def microphone_status() -> int:
    """Estado crudo de AVAuthorizationStatus. 0=sin decidir, 2=denegado, 3=ok.

    Se distingue de has_microphone() porque el onboarding necesita el matiz:
    'sin decidir' abre el prompt del sistema; 'denegado' ya no vuelve a
    preguntar y hay que mandar al usuario a Ajustes.
    """
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        return int(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio))
    except Exception as e:
        log.debug("No pude leer el estado del micrófono: %s", e)
        return _AV_NOT_DETERMINED


def has_microphone() -> bool:
    return microphone_status() == _AV_AUTHORIZED


def open_microphone_settings() -> None:
    """Abre Ajustes › Privacidad › Micrófono (cuando el permiso ya se denegó)."""
    try:
        subprocess.run(["open", MICROPHONE_PANE], check=False, timeout=5)
    except Exception as e:
        log.warning("No pude abrir Ajustes de micrófono: %s", e)


def request_microphone(callback=None) -> None:
    """Dispara el prompt del sistema. El callback recibe True/False desde otro hilo."""
    try:
        from AVFoundation import AVCaptureDevice, AVMediaTypeAudio

        def _done(granted):
            log.info("Permiso de micrófono: %s", "concedido" if granted else "denegado")
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
    """Accesibilidad habilita el hotkey global y el pegado en otras apps."""
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception as e:
        log.debug("No pude leer el estado de Accesibilidad: %s", e)
        return False


def open_accessibility_settings() -> None:
    """Abre el panel exacto de Ajustes (no se puede conceder por API)."""
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
    """True si falta algo imprescindible para poder dictar."""
    return any(not c.ok for c in check_all() if c.blocking)
