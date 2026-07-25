"""The recording state machine, serialized across threads.

    IDLE -> STARTING -> RECORDING -> PROCESSING -> IDLE

A data module without AppKit (same reason as keys.py or shortcuts.py:
instantiating VoooxlyApp builds menus and doesn't run in a test). app.py
delegates ALL transitions here.

Why it exists: on_start and on_stop arrive from the hotkey on separate
threads with no guaranteed order. With a fast tap of the dictation key, the
stop could run BEFORE the state reached RECORDING — it was a no-op — and the
start finished afterwards: an orphan recording nobody stopped until
audio.max_duration (5 minutes of open mic, Jeff's bug). Two consecutive
presses could also pass the IDLE check and open TWO recorders, the
first one orphaned forever. Both races are closed the same way: reserving
IDLE→STARTING atomically and noting a stop arriving during STARTING
to apply it as soon as the start finishes.
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
        """Reserves IDLE→STARTING atomically.

        False if a dictation is already underway (or starting): the caller
        must NOT create another recorder — this is the double-start closure.
        """
        with self._lock:
            if self._state != IDLE:
                return False
            self._state = STARTING
            self._stop_pending = False
            return True

    def begin_done(self) -> bool:
        """The start finished: STARTING→RECORDING.

        Returns True if a stop (or an Esc) arrived during the start: the
        caller must close the recording NOW. Before, that event got lost.
        """
        with self._lock:
            if self._state == STARTING:
                self._state = RECORDING
            pending, self._stop_pending = self._stop_pending, False
            return pending

    def begin_failed(self) -> None:
        """The start blew up: back to IDLE, without leaving a stale stop."""
        with self._lock:
            self._state = IDLE
            self._stop_pending = False

    def request_stop(self) -> str:
        """What to do with a stop that just arrived.

        - "stop": there's a real recording — the caller must stop it.
        - "deferred": the start is still on its thread — it gets noted and
          begin_done() will return it; the caller does nothing else.
        - "no": there's nothing to stop (IDLE or already PROCESSING).
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
