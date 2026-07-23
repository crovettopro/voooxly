"""El gate cierra las dos carreras del micro encallado (bug de Jeff, v1.4):

1. Tap rápido: el stop llegaba antes de que el estado fuera RECORDING, era un
   no-op, y la grabación quedaba huérfana hasta audio.max_duration (5 min).
2. Doble press: dos hilos pasaban el chequeo de IDLE y abrían dos recorders.
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
    assert g.begin_done() is False          # nadie pidió parar durante el arranque
    assert g.state == recgate.RECORDING
    assert g.request_stop() == "stop"
    g.processing()
    assert g.state == recgate.PROCESSING
    g.idle()
    assert g.state == recgate.IDLE


def test_doble_arranque_solo_pasa_el_primero():
    g = _gate()
    assert g.try_begin()
    assert not g.try_begin()                # segundo press mientras arranca
    g.begin_done()
    assert not g.try_begin()                # ni mientras graba
    g.processing()
    assert not g.try_begin()                # ni mientras procesa
    g.idle()
    assert g.try_begin()                    # tras volver a IDLE, sí


def test_stop_durante_el_arranque_queda_anotado():
    """El corazón del bug: el release del tap rápido no puede perderse."""
    g = _gate()
    g.try_begin()
    assert g.request_stop() == "deferred"   # el llamador no para nada aún
    assert g.begin_done() is True           # ...pero el arranque lo aplica al terminar


def test_el_stop_anotado_no_sobrevive_al_siguiente_dictado():
    g = _gate()
    g.try_begin()
    g.request_stop()
    g.begin_done()                          # consumido aquí
    g.processing()
    g.idle()
    g.try_begin()
    assert g.begin_done() is False          # el dictado nuevo arranca limpio


def test_stop_sin_nada_que_parar_es_no():
    g = _gate()
    assert g.request_stop() == "no"         # IDLE
    g.try_begin()
    g.begin_done()
    g.processing()
    assert g.request_stop() == "no"         # PROCESSING: _process ya decide solo


def test_begin_failed_vuelve_a_idle_y_limpia_el_pendiente():
    g = _gate()
    g.try_begin()
    g.request_stop()
    g.begin_failed()
    assert g.state == recgate.IDLE
    g.try_begin()
    assert g.begin_done() is False


def test_carrera_real_tap_rapido_alguien_para_siempre():
    """La carrera con hilos de verdad: press y release concurrentes. Pase lo
    que pase el orden, exactamente un camino para la grabación — o el stop
    directo (ya era RECORDING) o el pendiente que devuelve begin_done()."""
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
