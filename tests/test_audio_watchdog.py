"""A CoreAudio stream hung in abort()/close() cannot hijack the shutdown
of the recording: _finalize must still finish in ~3s and deliver _on_stop,
or the app stays in RECORDING forever (seen in the wild).
"""
import threading
import time

from voooxly import audio


class _StreamColgado:
    def abort(self):
        time.sleep(30)  # CoreAudio that never comes back

    def close(self):
        pass


class _StreamSano:
    def __init__(self):
        self.closed = False

    def abort(self):
        pass

    def close(self):
        self.closed = True


def _recorder_con(stream):
    r = audio.Recorder(audio.AudioConfig())
    r._stream = stream
    return r


def test_finalize_no_se_cuelga_con_stream_zombi():
    r = _recorder_con(_StreamColgado())
    got = threading.Event()
    r._on_stop = lambda a, d: got.set()
    t0 = time.monotonic()
    r._finalize()
    elapsed = time.monotonic() - t0
    assert elapsed < 6, f"_finalize tardó {elapsed:.1f}s: el watchdog no cortó"
    assert got.is_set(), "_on_stop no llegó pese al watchdog"


def test_finalize_cierra_el_stream_sano():
    stream = _StreamSano()
    r = _recorder_con(stream)
    r._on_stop = lambda a, d: None
    r._finalize()
    assert stream.closed
    assert r._stream is None


def test_finalize_es_idempotente():
    r = _recorder_con(_StreamSano())
    calls = []
    r._on_stop = lambda a, d: calls.append(1)
    r._finalize()
    r._finalize()  # the _finalized guard prevents the double close
    assert calls == [1]
