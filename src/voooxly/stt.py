"""Speech-to-text with whisper.cpp (persistent HTTP server, Metal on Apple Silicon).

Architecture: we launch `whisper-server` as a subprocess when the app starts. The model
is loaded ONCE and stays in memory. Transcriptions (partials and final) are requested
over HTTP POST /inference with a wav — so each transcription is fast (~0.3–0.8s) with no
model re-load and no torch.

No heavy Python dependency: whisper.cpp is a native binary with Metal acceleration
(optional CoreML/ANE if the .mlmodelc encoder is downloaded).
"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np
import requests

log = logging.getLogger("voooxly.stt")

SR = 16000
_server_proc: subprocess.Popen | None = None
_server_lock = threading.Lock()
_server_url: str = "http://127.0.0.1:8080"
_server_ready = threading.Event()
# The onboarding and the warmup can request the model at the same time: without
# this, two downloads would write over the same .part and leave it corrupt.
_download_lock = threading.Lock()

# With a 60s recording cap, a fixed 30s timeout on /inference never caused
# problems in production — that bounds whisper.cpp's real worst case
# (large-v3-turbo, Metal) at an RTF <= 0.5 (30s of compute per 60s of audio).
# By scaling the timeout with the duration we keep THAT SAME ratio instead of
# inventing a new number: at audio.max_duration's 300s it gives 150s, well
# below the ceiling further down. (whisper.cpp with Metal on Apple Silicon
# usually runs quite a bit faster than this in practice — this module's own
# warmup measures ~0.3-0.8s on 5s windows, RTF ~0.06-0.16 — so 0.5 leaves
# ample margin for a cold model start, CPU/GPU shared with
# other apps or more modest Macs.)
_TRANSCRIBE_TIMEOUT_PER_SECOND = 0.5
# Floor: same as the old fixed timeout, so a short dictation against a
# stalled server keeps failing fast — don't regress the case that already
# worked fine.
_TRANSCRIBE_TIMEOUT_FLOOR = 30.0
# Hard ceiling: at audio.max_duration's 300s the calculation above gives 150s,
# below this — in practice it should never kick in. It's here as a safety
# net in case audio.max_duration goes up in the future or the calculation
# drifts: a hung server cannot leave the app waiting forever.
_TRANSCRIBE_TIMEOUT_CEILING = 180.0

# Whisper's encoder ALWAYS processes a 30s window (1500 frames, 50/s),
# however long the real audio is. Per-request `audio_ctx` trims that window:
# -51% measured latency on short dictations with ZERO text divergence
# (scratchpad/latency-experiments.md). The 1.5x margin (75 frames/s) and the
# cutoff exist because a context smaller than the audio corrupts the ending
# into a hallucination loop — reproduced in the experiment with 19s of audio.
#
# ONLY multiples of 256: the Metal kernels of whisper.cpp 1.9.1 are only
# fast with the context aligned (measured on this Mac: 309/320/384 → ~4s;
# 256/512/768/1024 → 0.4-1.1s, same audio and same text). Above 1280 the
# next useful step is already almost the full window: native context.
_AUDIO_CTX_FRAMES_PER_S = 75
_AUDIO_CTX_STEP = 256
_AUDIO_CTX_MAX = 1280


def audio_ctx_for(duration_s: float) -> int | None:
    """Context frames for the encoder, or None (= full context)."""
    import math

    if duration_s <= 0:
        return None
    frames = duration_s * _AUDIO_CTX_FRAMES_PER_S
    ctx = max(1, math.ceil(frames / _AUDIO_CTX_STEP)) * _AUDIO_CTX_STEP
    return ctx if ctx <= _AUDIO_CTX_MAX else None


def _transcribe_timeout(audio: np.ndarray) -> float:
    """/inference timeout proportional to the audio, not fixed.

    A fixed timeout was enough when the recording cap was 60s. With dictations
    of up to 5 min, transcribing can take longer than a fixed 30s: the POST
    times out, transcribe()'s `except Exception` swallows it and the whole
    dictation is lost without pasting anything — the same bug that raising
    the recording cap fixed, one step further down the chain.
    """
    from .config import get_config

    duration_s = len(audio) / SR
    cfg = get_config()
    floor = cfg.get("stt.transcribe_timeout_floor", _TRANSCRIBE_TIMEOUT_FLOOR)
    ceiling = cfg.get("stt.transcribe_timeout_ceiling", _TRANSCRIBE_TIMEOUT_CEILING)
    ceiling = max(ceiling, floor)  # an inverted floor in config.yaml can't promise less than itself
    scaled = duration_s * _TRANSCRIBE_TIMEOUT_PER_SECOND
    return min(ceiling, max(floor, scaled))


def _find_model() -> str | None:
    # q5_0 first: on 8GB Macs the unquantized model (1.5GB) gets paged out
    # after inactivity and the next dictation pays 10-19s; the quantized one
    # (~550MB) fits comfortably in RAM with nearly identical quality.
    candidates = [
        os.path.expanduser("~/.voooxly/models/ggml-large-v3-turbo-q5_0.bin"),
        os.path.expanduser("~/.voooxly/models/ggml-large-v3-turbo.bin"),
        os.path.expanduser("~/.voooxly/models/ggml-large-v3.bin"),
        os.path.expanduser("~/.voooxly/models/ggml-medium.bin"),
    ]
    env_model = os.environ.get("VOOOXLY_STT_MODEL_FILE")
    if env_model and os.path.exists(env_model):
        return env_model
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin"


def find_model() -> str | None:
    return _find_model()


def server_ready() -> bool:
    """True if the whisper-server responded the last time it was needed.

    The UI uses it to tell "you said nothing" apart from "the engine is down":
    different messages, different remedies.
    """
    return _server_ready.is_set()


def ensure_model(progress_cb=None) -> str | None:
    """Returns the model path, downloading it if it doesn't exist (0-100 progress).

    Serialized: if two threads request it at once (onboarding + warmup), the second
    waits and finds the model already downloaded instead of duplicating the download.
    """
    m = _find_model()
    if m:
        return m
    with _download_lock:
        return _download_model(progress_cb)


def _download_model(progress_cb=None) -> str | None:
    # Re-check inside the lock: whoever held it may have downloaded it.
    m = _find_model()
    if m:
        return m
    dst = pathlib.Path(os.path.expanduser("~/.voooxly/models/ggml-large-v3-turbo-q5_0.bin"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    log.info("Descargando modelo: %s", MODEL_URL)
    try:
        with requests.get(MODEL_URL, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) or None
            done, last_pct = 0, -1
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if total and progress_cb:
                        pct = int(done * 100 / total)
                        if pct != last_pct:
                            last_pct = pct
                            try:
                                progress_cb(pct)
                            except Exception:
                                pass
        tmp.rename(dst)
        log.info("Modelo descargado (%.2f GB).", done / 1e9)
        return str(dst)
    except Exception as e:
        log.error("Model download failed: %s", e)
        try:
            tmp.unlink()
        except Exception:
            pass
        return None


def _which_server() -> str | None:
    # 1st, the whisper-server EMBEDDED in the .app (vendor/whisper in the spec):
    # the recipient doesn't need Homebrew.
    import sys

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = os.path.join(meipass, "whisper", "whisper-server")
        if os.path.exists(bundled) and os.access(bundled, os.X_OK):
            return bundled
    # Apps launched by LaunchServices do NOT inherit the shell's PATH
    # (/opt/homebrew/bin isn't there) — without the explicit paths, the .app
    # wouldn't find whisper-server after a Mac restart.
    explicit = [
        os.path.expanduser("~/.voooxly/bin/whisper-server"),
        "/opt/homebrew/bin/whisper-server",
        "/usr/local/bin/whisper-server",
    ]
    for p in explicit:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return shutil.which("whisper-server") or shutil.which("whisper-cli")


def start_server(model_path: str | None = None, threads: int = 4, port: int = 8080) -> bool:
    """Starts whisper-server in the background. Idempotent. Returns True if ready.

    If a server is already responding on the port (e.g. from a previous launch
    that didn't close), it reuses it instead of spawning one that couldn't bind.
    """
    global _server_proc, _server_url
    with _server_lock:
        if _server_proc and _server_proc.poll() is None and _server_ready.is_set():
            return True
        _server_url = f"http://127.0.0.1:{port}"
        # is someone already responding on the port? reuse it
        if _probe(_server_url):
            log.info("Reusing whisper-server already active at %s", _server_url)
            _server_ready.set()
            return True
        server_bin = _which_server()
        if not server_bin:
            log.error("whisper-server not found. Install: brew install whisper-cpp")
            return False
        model = model_path or _find_model()
        if not model:
            log.error("No ggml model in ~/.voooxly/models/. Download one (see README).")
            return False
        _server_url = f"http://127.0.0.1:{port}"
        cmd = [
            server_bin,
            "-m", model,
            "-t", str(threads),
            "--port", str(port),
            "-l", "auto",  # language auto-detection
        ]
        log.info("Starting whisper-server: %s", " ".join(cmd))
        env = os.environ.copy()
        # embedded server: ggml looks for its backends (Metal/CPU .so) in a
        # compiled-in Homebrew path that doesn't exist on other Macs —
        # GGML_BACKEND_PATH redirects them to the vendored directory if
        # they're placed there.
        server_dir = os.path.dirname(server_bin)
        if any(f.startswith("libggml-") and f.endswith(".so")
               for f in os.listdir(server_dir) if os.path.isfile(os.path.join(server_dir, f))):
            env["GGML_BACKEND_PATH"] = server_dir
            log.info("GGML_BACKEND_PATH=%s (backends embebidos)", server_dir)
        try:
            _server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                env=env,
            )
        except Exception as e:
            log.exception("Couldn't start whisper-server: %s", e)
            return False
        threading.Thread(target=_reader, daemon=True).start()
        # wait for the server to respond
        ok = _wait_ready(timeout=60)
        _server_ready.set() if ok else _server_ready.clear()
        return ok


def _reader():
    # consume the server's stderr so the pipe doesn't block
    global _server_proc
    while _server_proc and _server_proc.poll() is None:
        try:
            line = _server_proc.stderr.readline()
            if line:
                log.debug("whisper-server: %s", line.decode("utf-8", "ignore").strip())
        except Exception:
            break


def _probe(url: str) -> bool:
    """True if something responds at the URL (quick GET)."""
    try:
        requests.get(url, timeout=1.5)
        return True
    except requests.exceptions.HTTPError:
        return True
    except Exception:
        return False


def _wait_ready(timeout: float = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _server_proc and _server_proc.poll() is not None:
            log.error("whisper-server died on startup (code %s)", _server_proc.returncode)
            return False
        if _probe(_server_url):
            return True
        time.sleep(0.5)
    return False


def stop_server() -> None:
    global _server_proc, _server_ready
    with _server_lock:
        if _server_proc:
            try:
                _server_proc.terminate()
                _server_proc.wait(timeout=5)
            except Exception:
                try:
                    _server_proc.kill()
                except Exception:
                    pass
            _server_proc = None
        _server_ready.clear()


def _audio_to_wav(audio: np.ndarray, path: str) -> None:
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(audio.tobytes())


def transcribe(
    audio: np.ndarray,
    model_id: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
) -> str:
    """Transcribes an int16 16kHz array by asking the whisper-server. Returns text.

    `prompt` = personal dictionary (proper names, jargon): whisper uses it as the
    initial prompt and biases the transcription towards those spellings.
    """
    if audio is None or len(audio) == 0:
        return ""
    if not (_server_ready.is_set() or start_server()):
        log.error("STT server unavailable.")
        return ""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        _audio_to_wav(audio, wav_path)
        data = {"temperature": "0.0", "response_format": "json"}
        ctx = audio_ctx_for(len(audio) / SR)
        if ctx is not None:
            data["audio_ctx"] = str(ctx)
        if language and language != "auto":
            data["language"] = language
        if prompt:
            data["prompt"] = prompt
        # Same timeout on the initial attempt and the retry: a long dictation
        # takes the same to transcribe in both, so fixing only one of the
        # two would leave the bug alive on the other path.
        timeout = _transcribe_timeout(audio)
        with open(wav_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            try:
                r = requests.post(f"{_server_url}/inference", files=files, data=data, timeout=timeout)
            except requests.exceptions.ConnectionError:
                # retry starting the server once
                if start_server():
                    with open(wav_path, "rb") as f:
                        files = {"file": ("audio.wav", f, "audio/wav")}
                        r = requests.post(f"{_server_url}/inference", files=files, data=data, timeout=timeout)
                else:
                    return ""
        if not r.ok:
            log.error("whisper-server /inference %s: %s", r.status_code, r.text[:200])
            return ""
        body = r.json()
        text = (body.get("text", "") or "").strip()
        # collapse newlines/multiple spaces: a dictation is a single utterance
        import re

        return re.sub(r"\s+", " ", text).strip()
    except Exception as e:
        log.exception("Error transcribiendo: %s", e)
        return ""
    finally:
        try:
            os.unlink(wav_path)
        except Exception:
            pass


# Phrases Whisper "makes up" when the audio is silence or near silence
# (trained on videos: sign-offs like "Thank you." or subtitlers' credits).
_HALLUCINATIONS = {
    "thank you", "thank you very much", "thanks for watching", "thank you for watching",
    "you",
    "gracias", "muchas gracias", "gracias por ver", "gracias por ver el video",
    "subtitulos realizados por la comunidad de amara org",
    "subtitulos por la comunidad de amara org",
    "subtitles by the amara org community",
}


def _norm_text(text: str) -> str:
    import re
    import unicodedata

    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")  # no accents
    return re.sub(r"[\W_]+", " ", t).strip()


def looks_hallucinated(text: str, speech_ratio: float) -> bool:
    """True if the transcription smells like a Whisper hallucination over silence.

    We only discard blacklist phrases when the VAD barely saw speech
    (low speech_ratio): if the user really dictated "gracias", it's respected.
    """
    norm = _norm_text(text)
    if not norm:
        return True
    return norm in _HALLUCINATIONS and speech_ratio < 0.15


def warmup(model_id: str | None = None) -> None:
    """Preload: starts the server and does an empty transcription."""
    if start_server():
        transcribe(np.zeros(SR, dtype=np.int16))


def is_available() -> bool:
    return _which_server() is not None and _find_model() is not None
