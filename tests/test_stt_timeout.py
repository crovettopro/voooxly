"""The /inference timeout has to scale with the audio, not be fixed.

30s was enough when the recording cap was 60s (a timeout was never seen in
production with that combination), but with dictations of up to 5 min (see
audio.max_duration) transcribing can take longer than that: the POST times
out, transcribe()'s `except Exception` swallows it and the whole dictation is
lost without pasting anything — the same bug that raising the recording cap
fixed, one step further down the chain. These tests pin that the timeout grows
with the audio duration, with a 30s floor (do not regress short dictations)
and a hard ceiling (do not hang the app forever if the server is dead).
"""
from __future__ import annotations

import threading

import numpy as np
import pytest
import requests

from voooxly import stt
from voooxly.config import load_config


class _FakeResponse:
    ok = True
    status_code = 200
    text = "{}"

    def json(self):
        return {"text": "hola mundo"}


@pytest.fixture(autouse=True)
def _servidor_listo(monkeypatch):
    # We skip the real whisper-server startup: these tests only care
    # about which timeout requests.post receives.
    ready = threading.Event()
    ready.set()
    monkeypatch.setattr(stt, "_server_ready", ready)
    yield


def _audio_de(segundos: float) -> np.ndarray:
    return np.zeros(int(stt.SR * segundos), dtype=np.int16)


def test_un_dictado_largo_recibe_un_timeout_mayor_a_30s(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    stt.transcribe(_audio_de(300.0))  # 5 min: the audio.max_duration maximum
    assert capturados[0] > 30, (
        "300s de audio deben pedir más de los 30s fijos de antes: si no, un "
        "dictado largo real puede expirar y perderse igual que antes de "
        "subir el tope de grabación."
    )


def test_timeout_scales_proportionally_to_duration(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    stt.transcribe(_audio_de(60.0))
    stt.transcribe(_audio_de(300.0))
    corto, largo = capturados
    # 300s is 5x more audio than 60s: the timeout has to grow with it, not
    # stay flat (that would be the same bug with a different number).
    assert largo > corto


def test_un_dictado_corto_no_baja_del_piso_de_30s(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    stt.transcribe(_audio_de(2.0))
    assert capturados[0] >= 30, (
        "un dictado corto contra un server encallado tiene que seguir "
        "fallando rápido, igual que con el timeout fijo de antes."
    )


def test_timeout_has_a_ceiling(monkeypatch):
    capturados = []

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    # Far above audio.max_duration: a hung server must not leave the app
    # waiting forever no matter what happens with the audio duration.
    stt.transcribe(_audio_de(3600.0))
    assert capturados[0] <= 200, "el timeout tiene que estar acotado por un techo duro"


def test_retry_after_connectionerror_uses_same_scaled_timeout(monkeypatch):
    capturados = []
    intentos = {"n": 0}

    def fake_post(url, files=None, data=None, timeout=None):
        capturados.append(timeout)
        intentos["n"] += 1
        if intentos["n"] == 1:
            raise requests.exceptions.ConnectionError("server no responde")
        return _FakeResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(stt, "start_server", lambda *a, **k: True)
    stt.transcribe(_audio_de(300.0))
    assert len(capturados) == 2, "el reintento tiene que haber ocurrido"
    assert capturados[0] == capturados[1] > 30, (
        "arreglar solo el primer POST y dejar el reintento en 30s fijo deja "
        "vivo el bug en ese camino"
    )


def test_yaml_exposes_floor_and_ceiling_of_transcription_timeout():
    cfg = load_config()
    assert cfg.get("stt.transcribe_timeout_floor", 0) >= 30
    assert cfg.get("stt.transcribe_timeout_ceiling", 0) >= 150


class _CfgFloorPorEncimaDelTecho:
    """Config with floor > ceiling: a typo in config.yaml, not an exotic
    case — nothing today prevents someone from swapping the two values."""

    def get(self, path, default=None):
        if path == "stt.transcribe_timeout_floor":
            return 200.0
        if path == "stt.transcribe_timeout_ceiling":
            return 30.0
        return default


def test_floor_above_ceiling_does_not_drop_below_promised_floor(monkeypatch):
    # Fix 4: min(ceiling, max(floor, scaled)) with floor > ceiling returns
    # ceiling (30s) even though the floor promised at least 200s — exactly
    # below what the floor itself guarantees. Without the clamp, a config
    # with the two values swapped leaves timeouts shorter than the
    # configured floor, silently.
    import voooxly.config as config_mod

    monkeypatch.setattr(config_mod, "get_config", lambda: _CfgFloorPorEncimaDelTecho())
    assert stt._transcribe_timeout(_audio_de(2.0)) >= 200.0
