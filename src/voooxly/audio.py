"""Microphone capture + VAD + silence endpointing.

Uses sounddevice (PortAudio) to capture 16kHz mono int16 and webrtcvad to detect
speech frame by frame. Detects the end of the utterance by sustained silence and
exposes both the full audio and a recent window for the live partials.

Built-in diagnostics: each recording knows its RMS and its ratio of voiced
frames. If macOS denies the microphone (TCC), CoreAudio silently delivers zeros
— the RMS≈0 gives it away and the app can warn instead of sending silence to
Whisper (which hallucinates "Thank you." / "Gracias.").
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
import webrtcvad

log = logging.getLogger("voooxly.audio")

SR = 16000
FRAME_MS = 30
FRAME_SAMPLES = SR * FRAME_MS // 1000  # 480


def rms_of(audio: np.ndarray) -> float:
    """RMS of an int16 buffer. TCC silence ≈ 0; normal speech ≈ 300–3000."""
    if audio is None or len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


def default_input_name(device: int | str | None = None) -> str:
    try:
        info = sd.query_devices(device, kind="input")
        return str(info["name"])
    except Exception:
        return "?"


@dataclass
class AudioConfig:
    device: int | str | None = None
    vad_aggressiveness: int = 2
    silence_to_stop: float = 1.2
    # 5 min, not 60s: the one-minute cap nullified the latch, which exists
    # precisely for long dictations. It's not removed entirely — it remains
    # the safety net against a stuck key, which would record until the disk fills.
    max_duration: float = 300.0
    min_duration: float = 0.4


class Recorder:
    """Recorder with VAD and automatic silence endpointing."""

    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self.vad = webrtcvad.Vad(cfg.vad_aggressiveness)
        self._lock = threading.Lock()
        self._frames: list[np.ndarray] = []          # full captured audio
        self._recent: deque[np.ndarray] = deque()    # window for partials
        self._silence_frames = 0
        self._speech_frames = 0
        self._total_frames = 0
        self._has_speech = False
        self._start_ts = 0.0
        self._stream: sd.InputStream | None = None
        self._stop_event = threading.Event()
        self._finalize_lock = threading.Lock()
        self._finalized = False
        self._on_stop: callable | None = None
        self._on_partial: callable | None = None
        self._partial_thread: threading.Thread | None = None
        self._partial_interval = 1.5
        self._partial_window = 12.0

    # --- API ---
    def start(
        self,
        on_stop: callable | None = None,
        on_partial: callable | None = None,
        partial_interval: float = 1.5,
        partial_window: float = 12.0,
    ) -> None:
        self._on_stop = on_stop
        self._on_partial = on_partial
        self._partial_interval = partial_interval
        self._partial_window = partial_window
        with self._lock:
            self._frames.clear()
            self._recent.clear()
            self._silence_frames = 0
            self._speech_frames = 0
            self._total_frames = 0
            self._has_speech = False
        self._stop_event.clear()
        with self._finalize_lock:
            self._finalized = False
        self._start_ts = time.monotonic()
        if on_partial:
            self._partial_thread = threading.Thread(
                target=self._partial_loop, daemon=True
            )
            self._partial_thread.start()
        log.info("Microphone: %s", default_input_name(self.cfg.device))
        self._stream = sd.InputStream(
            samplerate=SR,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=self.cfg.device,
            callback=self._audio_cb,
        )
        self._stream.start()

    def stop(self) -> None:
        """Aborts without processing (e.g. when quitting the app)."""
        with self._finalize_lock:
            self._finalized = True  # blocks any subsequent on_stop
        self._stop_event.set()
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None

    def force_finish(self) -> None:
        """Closes the recording now and processes (hotkey released / menu button)."""
        self._finalize()

    # --- diagnostic stats ---
    @property
    def had_speech(self) -> bool:
        with self._lock:
            return self._has_speech

    @property
    def speech_ratio(self) -> float:
        with self._lock:
            if self._total_frames == 0:
                return 0.0
            return self._speech_frames / self._total_frames

    # --- internals ---
    def _audio_cb(self, indata, frames, time_info, status):  # noqa: ANN001
        if self._stop_event.is_set():
            return
        frame = indata[:, 0].copy()
        is_speech = False
        try:
            is_speech = self.vad.is_speech(frame.tobytes(), SR)
        except Exception:
            is_speech = False

        # We ALWAYS capture the audio (not just what the VAD marks as speech):
        # if the VAD fails or the mic is low, we still have real audio to
        # transcribe. The VAD is only used for silence endpointing.
        with self._lock:
            self._recent.append(frame)
            max_recent = int(self._partial_window * SR / FRAME_SAMPLES)
            while len(self._recent) > max_recent:
                self._recent.popleft()
            self._frames.append(frame)
            self._total_frames += 1
            if is_speech:
                self._speech_frames += 1
                self._silence_frames = 0
                self._has_speech = True
            elif self._has_speech:
                self._silence_frames += 1

        # endpointing (in hold mode silence_to_stop is ~infinite, so it doesn't cut).
        # CAREFUL: the stream can't be stopped from inside its own callback
        # (PortAudio deadlock) — it's delegated to a thread and cut with CallbackStop.
        silence_secs = self._silence_frames * FRAME_MS / 1000.0
        elapsed = time.monotonic() - self._start_ts
        end_by_silence = self._has_speech and silence_secs >= self.cfg.silence_to_stop
        end_by_timeout = elapsed >= self.cfg.max_duration
        if end_by_silence or end_by_timeout:
            threading.Thread(target=self._finalize, daemon=True).start()
            raise sd.CallbackStop()

    def _finalize(self) -> None:
        with self._finalize_lock:
            if self._finalized:
                return
            self._finalized = True
        self._stop_event.set()
        if self._partial_thread and self._partial_thread.is_alive():
            self._partial_thread.join(timeout=2)
        self._close_stream_with_watchdog()
        audio = self.get_full_audio()
        duration = len(audio) / SR
        log.info(
            "Recording closed: %.1fs, RMS=%.0f, voice=%.0f%%",
            duration, rms_of(audio), self.speech_ratio * 100,
        )
        if self._on_stop:
            keep = duration >= self.cfg.min_duration
            self._on_stop(audio if keep else None, duration)

    def _close_stream_with_watchdog(self) -> None:
        """Closes the stream without getting hung by CoreAudio.

        abort()/close() can block FOREVER (seen for real: the recorder
        went zombie, _on_stop never arrived and the app stayed in
        RECORDING with the mic open, immune to release/Esc/the 60s cap
        because the _finalized guard turns retries into no-ops). The close
        goes in a thread with a timeout: if it doesn't respond in 3s, the
        stream is abandoned (freed when the process dies) and the captured
        audio is processed anyway — recovering is worth more than a clean close.
        """
        stream, self._stream = self._stream, None
        if stream is None:
            return

        def _close():
            try:
                # abort() discards pending buffers instead of waiting for them:
                # a stream stuck by TCC would never deliver them and stop() would hang
                stream.abort()
                stream.close()
            except Exception:
                pass

        t = threading.Thread(target=_close, daemon=True)
        t.start()
        t.join(timeout=3.0)
        if t.is_alive():
            log.warning(
                "Audio stream didn't respond to abort/close in 3s "
                "(CoreAudio hung): continuing without waiting for it."
            )

    def _partial_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self._partial_interval)
            if self._stop_event.is_set() or not self._on_partial:
                continue
            audio = self.get_recent_audio()
            if len(audio) / SR < 0.3:
                continue
            self._on_partial(audio)

    def get_full_audio(self) -> np.ndarray:
        with self._lock:
            if not self._frames:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(self._frames).astype(np.int16)

    def get_recent_audio(self) -> np.ndarray:
        with self._lock:
            if not self._recent:
                return np.zeros(0, dtype=np.int16)
            return np.concatenate(list(self._recent)).astype(np.int16)


def list_input_devices() -> list[dict]:
    devs = sd.query_devices()
    out = []
    for i, d in enumerate(devs):
        if d["max_input_channels"] >= 1:
            out.append({"index": i, "name": d["name"], "channels": d["max_input_channels"]})
    return out
