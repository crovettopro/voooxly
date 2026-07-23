"""La máquina de estados de la grabación, serializada entre hilos.

    IDLE -> STARTING -> RECORDING -> PROCESSING -> IDLE

Un módulo de datos sin AppKit (mismo motivo que keys.py o shortcuts.py:
instanciar VoooxlyApp construye menús y no corre en un test). app.py delega
aquí TODAS las transiciones.

Por qué existe: on_start y on_stop llegan del hotkey en hilos separados sin
orden garantizado. Con un tap rápido de la tecla de dictado, el stop podía
ejecutarse ANTES de que el estado llegara a RECORDING — era un no-op — y el
arranque terminaba después: grabación huérfana que nadie paraba hasta
audio.max_duration (5 minutos de micro abierto, el bug de Jeff). También
podían pasar dos press seguidos el chequeo de IDLE y abrir DOS recorders, el
primero huérfano para siempre. Las dos carreras se cierran igual: reservar
IDLE→STARTING de forma atómica y anotar el stop que llegue durante STARTING
para aplicarlo en cuanto el arranque termine.
"""
from __future__ import annotations

import threading

IDLE = "IDLE"
STARTING = "STARTING"
RECORDING = "RECORDING"
PROCESSING = "PROCESSING"


class RecordingGate:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = IDLE
        self._stop_pending = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def try_begin(self) -> bool:
        """Reserva IDLE→STARTING de forma atómica.

        False si ya hay un dictado en marcha (o arrancando): quien llama NO
        debe crear otro recorder — este es el cierre del doble arranque.
        """
        with self._lock:
            if self._state != IDLE:
                return False
            self._state = STARTING
            self._stop_pending = False
            return True

    def begin_done(self) -> bool:
        """El arranque terminó: STARTING→RECORDING.

        Devuelve True si durante el arranque llegó un stop (o un Esc): el
        llamador debe cerrar la grabación YA. Antes ese evento se perdía.
        """
        with self._lock:
            if self._state == STARTING:
                self._state = RECORDING
            pending, self._stop_pending = self._stop_pending, False
            return pending

    def begin_failed(self) -> None:
        """El arranque reventó: vuelta a IDLE, sin dejar un stop rancio."""
        with self._lock:
            self._state = IDLE
            self._stop_pending = False

    def request_stop(self) -> str:
        """Qué hacer con un stop que acaba de llegar.

        - "stop": hay grabación de verdad — el llamador debe pararla.
        - "deferred": el arranque sigue en su hilo — queda anotado y
          begin_done() lo devolverá; el llamador no hace nada más.
        - "no": no hay nada que parar (IDLE o ya PROCESSING).
        """
        with self._lock:
            if self._state == RECORDING:
                return "stop"
            if self._state == STARTING:
                self._stop_pending = True
                return "deferred"
            return "no"

    def processing(self) -> None:
        with self._lock:
            self._state = PROCESSING

    def idle(self) -> None:
        with self._lock:
            self._state = IDLE
            self._stop_pending = False
