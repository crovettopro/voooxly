"""The gate closes the two stuck-mic races (Jeff's bug, v1.4):

1. Quick tap: the stop arrived before the state was RECORDING, was a
   no-op, and the recording was left orphaned until audio.max_duration (5 min).
2. Double press: two threads passed the IDLE check and opened two recorders.
"""
import threading

from voooxly import recgate


def _gate():
    return recgate.RecordingGate()


def test_ciclo_normal():
    g = _gate()
    assert g.state == recgate.IDLE
    assert g.try_begin()
    assert g.state == recgate.STARTING
    assert g.begin_done() is False          # nobody asked to stop during startup
    assert g.state == recgate.RECORDING
    assert g.request_stop() == "stop"
    g.processing()
    assert g.state == recgate.PROCESSING
    g.idle()
    assert g.state == recgate.IDLE


def test_double_start_only_passes_first():
    g = _gate()
    assert g.try_begin()
    assert not g.try_begin()                # second press while starting
    g.begin_done()
    assert not g.try_begin()                # nor while recording
    g.processing()
    assert not g.try_begin()                # nor while processing
    g.idle()
    assert g.try_begin()                    # after returning to IDLE, yes


def test_stop_during_start_is_noted():
    """The heart of the bug: the quick tap's release must not get lost."""
    g = _gate()
    g.try_begin()
    assert g.request_stop() == "deferred"   # the caller stops nothing yet
    assert g.begin_done() is True           # ...but startup applies it when it finishes


def test_noted_stop_does_not_survive_next_dictation():
    g = _gate()
    g.try_begin()
    g.request_stop()
    g.begin_done()                          # consumed here
    g.processing()
    g.idle()
    g.try_begin()
    assert g.begin_done() is False          # the new dictation starts clean


def test_stop_sin_nada_que_parar_es_no():
    g = _gate()
    assert g.request_stop() == "no"         # IDLE
    g.try_begin()
    g.begin_done()
    g.processing()
    assert g.request_stop() == "no"         # PROCESSING: _process already decides on its own


def test_begin_failed_vuelve_a_idle_y_limpia_el_pendiente():
    g = _gate()
    g.try_begin()
    g.request_stop()
    g.begin_failed()
    assert g.state == recgate.IDLE
    g.try_begin()
    assert g.begin_done() is False


def test_carrera_real_tap_rapido_alguien_para_siempre():
    """The race with real threads: concurrent press and release. Whatever
    the ordering, exactly one path stops the recording — either the direct
    stop (it was already RECORDING) or the pending one begin_done() returns."""
    for _ in range(50):
        g = _gate()
        arrancando = threading.Event()
        parada = threading.Event()

        def press():
            assert g.try_begin()
            arrancando.set()
            if g.begin_done():
                parada.set()

        def release():
            arrancando.wait(2)
            if g.request_stop() == "stop":
                parada.set()

        t1 = threading.Thread(target=press)
        t2 = threading.Thread(target=release)
        t1.start(); t2.start()
        t1.join(2); t2.join(2)
        assert parada.is_set(), "la grabación quedó huérfana: nadie la paró"
