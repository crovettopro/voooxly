"""Capturar una tecla desde la ventana y ajustar el delay.

La regla que más cuesta acertar es el salto automático del slíder: elegir el
⌘ izquierdo con 0 ms deja la app inservible (cada ⌘C arranca una grabación),
así que el slíder salta a 400 solo. Pero elegir el ⌘ derecho NO puede subir a
nadie de 0 a 400: sería cambiarle el tacto de la app por la cara.
"""
from AppKit import NSFontAttributeName, NSStringDrawingUsesLineFragmentOrigin, NSString
from Foundation import NSMakeSize
from PyObjCTools import AppHelper
from pynput.keyboard import Key

from voooxly import keys, settings_window, shortcuts, theme

ESTADO = {
    "dictation": {"keys": ["cmd_r"], "style": "hold", "delay_ms": 0},
    "cycle_mode": {"keys": ["ctrl", "shift", "m"]},
    "latch": {"keys": ["shift"]},
    "cancel": {"keys": ["esc"]},
}


def _ctl(on_change=None):
    return settings_window.ShortcutsController.alloc().initWithState_onChange_(
        ESTADO, on_change or (lambda sid, fila: (True, "")))


class _HotkeyFalso:
    """Doble de HotkeyManager para test (Finding 2 del review). NUNCA es el
    de verdad: instanciar un segundo `keyboard.Listener` de verdad hace que
    macOS aborte con SIGABRT (TIS/TSM llamado desde dos hilos, ver
    attachHotkey_ en settings_window.py), así que el doble solo registra la
    llamada y guarda el callback para que el test lo dispare a mano, como
    haría pynput desde su propio hilo."""

    def __init__(self):
        self.capturas = 0
        self.cb = None
        self.canceladas = 0

    def begin_capture(self, cb):
        self.capturas += 1
        self.cb = cb

    def end_capture(self):
        self.canceladas += 1


def test_una_tecla_conflictiva_sube_el_delay_al_default():
    assert settings_window.delay_for(["cmd_l"], 0) == shortcuts.DEFAULT_DELAY_MS


def test_una_tecla_sin_conflicto_conserva_el_delay_anterior():
    # Cero regresión: quien tenía 0 con ⌘ derecho sigue con 0.
    assert settings_window.delay_for(["cmd_r"], 0) == 0


def test_una_tecla_sin_conflicto_no_baja_un_delay_ya_elegido():
    # Si el usuario había puesto 600 a mano, cambiar de tecla no se lo pisa.
    assert settings_window.delay_for(["cmd_r"], 600) == 600


def test_capturar_aplica_la_tecla_y_avisa_al_llamador():
    visto = []
    c = _ctl(lambda sid, fila: (visto.append((sid, fila)), (True, ""))[1])
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert visto[-1][0] == "cancel"
    assert visto[-1][1]["keys"] == ["f13"]
    c.close()


def test_una_tecla_en_conflicto_no_se_aplica():
    visto = []
    c = _ctl(lambda sid, fila: (visto.append(sid), (True, ""))[1])
    c.begin_capture_("dictation")
    c.apply_capture_(["esc"])          # ya es la de cancelar
    assert visto == [], "se aplicó una tecla en conflicto"
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    c.close()


def test_una_tecla_en_conflicto_deja_mensaje_en_la_fila():
    c = _ctl()
    c.begin_capture_("dictation")
    c.apply_capture_(["esc"])
    assert "Cancel dictation" in c._error_text
    c.close()


def test_si_el_llamador_rechaza_el_cambio_el_estado_no_se_toca():
    # on_change devuelve (False, msg) cuando hotkey.rebind() rechaza: el
    # estado de la ventana tiene que reflejar lo que suena de verdad, no lo
    # que se pidió, o el keycap mentiría.
    c = _ctl(lambda sid, fila: (False, "nope"))
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert c._estado["cancel"]["keys"] == ["esc"]
    assert c._error_text == "nope"
    c.close()


def test_cancelar_la_captura_deja_el_atajo_como_estaba():
    c = _ctl()
    c.begin_capture_("dictation")
    c.cancel_capture_()
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    assert c._capturing is None
    c.close()


def test_el_delay_se_recorta_al_rango():
    c = _ctl()
    c.set_delay_(9999)
    assert c._estado["dictation"]["delay_ms"] == shortcuts.MAX_DELAY_MS
    c.set_delay_(-5)
    assert c._estado["dictation"]["delay_ms"] == 0
    c.close()


def test_capturar_repinta_el_teclado():
    c = _ctl()
    c.begin_capture_("cancel")
    c.apply_capture_(["f13"])
    assert settings_window.lit_keys(c._estado)["f13"] == "cancel"
    c.close()


# ---------- Finding 1 (CRÍTICO): el valor del delay ahora se lee ----------

def test_el_valor_del_delay_sigue_al_estado_tras_set_delay():
    # El requisito estructural del brief: el texto mostrado tiene que seguir
    # a _estado["dictation"]["delay_ms"], no solo el pomo del slíder.
    c = _ctl()
    c.set_delay_(600)
    assert c._delay_valor.stringValue() == "600 ms"
    assert c._estado["dictation"]["delay_ms"] == 600
    c.close()


def test_el_valor_del_delay_tambien_sigue_al_salto_automatico():
    # apply_capture_ también puede cambiar delay_ms (delay_for salta al
    # default con una tecla que necesita guarda) sin pasar por set_delay_:
    # el valor tiene que sincronizarse por esa vía también.
    c = _ctl()
    c.begin_capture_("dictation")
    c.apply_capture_(["cmd_l"])
    assert c._delay_valor.stringValue() == f"{shortcuts.DEFAULT_DELAY_MS} ms"
    assert c._estado["dictation"]["delay_ms"] == shortcuts.DEFAULT_DELAY_MS
    c.close()


def test_las_marcas_del_delay_son_0_200_400_600_800():
    c = _ctl()
    textos = [m.stringValue() for m in c._delay_ticks]
    assert textos == ["0", "200", "400", "600", "800 ms"]
    c.close()


def test_las_marcas_del_delay_estan_alineadas_con_el_slider_de_izquierda_a_derecha():
    # No es un reparto a ojo: cada marca vive en la posición real del pomo
    # para su valor (_marca_x), así que tienen que salir en orden creciente.
    c = _ctl()
    xs = [m.frame().origin.x for m in c._delay_ticks]
    assert xs == sorted(xs)
    assert len(set(xs)) == len(xs)
    c.close()


def test_ningun_campo_nuevo_del_delay_mide_menos_que_su_texto():
    # La misma lección que ya escarmentó a _lado_ancho(): un campo ajustado
    # a ojo se recorta en silencio y stringValue() sigue devolviendo el
    # texto completo. Nada de constantes de píxeles clavadas: se compara
    # contra theme.text_width() con el font real de cada campo.
    c = _ctl()
    for campo in [*c._delay_ticks, c._delay_valor]:
        necesita = theme.text_width(campo.stringValue(), campo.font())
        assert campo.frame().size.width >= necesita, campo.stringValue()
    c.close()


# ---------- Finding 2 (Importante): captura real con un doble ----------

def test_filaclicked_arma_la_fila_y_llama_a_begin_capture_del_doble():
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.filaClicked_(c._fila_boton["latch"])
    assert c._capturing == "latch"
    assert hk.capturas == 1
    c.close()


def test_on_captured_con_combinacion_valida_aplica_al_estado(monkeypatch):
    # callAfter se sustituye por un espía que SÍ ejecuta la función (para
    # poder comprobar el efecto), pero de forma síncrona: en el test no hay
    # un run loop de verdad esperando al otro lado.
    monkeypatch.setattr(AppHelper, "callAfter", lambda fn, *a, **kw: fn(*a, **kw))
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.begin_capture_("cancel")
    c._on_captured_(["f13"])
    assert c._estado["cancel"]["keys"] == ["f13"]
    assert c._capturing is None
    c.close()


def test_on_captured_con_esc_cancela_sin_tocar_el_estado(monkeypatch):
    monkeypatch.setattr(AppHelper, "callAfter", lambda fn, *a, **kw: fn(*a, **kw))
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.begin_capture_("dictation")
    c._on_captured_(["esc"])
    assert c._capturing is None
    assert c._estado["dictation"]["keys"] == ["cmd_r"]
    assert hk.canceladas == 1  # cancel_capture_ llamó a end_capture() del doble
    c.close()


def test_on_captured_no_toca_appkit_directo_siempre_pasa_por_callafter(monkeypatch):
    # El invariante MÁS importante del Finding 2: _on_captured_ llega por el
    # hilo del listener de pynput, y tocar AppKit ahí directamente es el
    # SIGTRAP/EXC_BREAKPOINT de siempre. Aquí el espía NO ejecuta la función
    # que le pasan -solo la registra-, así que si _on_captured_ mutase el
    # estado o AppKit por otro camino que no fuera callAfter, este test lo
    # vería: el estado tendría que seguir intacto.
    llamadas = []
    monkeypatch.setattr(
        AppHelper, "callAfter",
        lambda fn, *a, **kw: llamadas.append((fn, a, kw)))
    hk = _HotkeyFalso()
    c = _ctl()
    c.attachHotkey_(hk)
    c.begin_capture_("cancel")
    c._on_captured_(["f13"])

    assert len(llamadas) == 1, "_on_captured_ no pasó (una sola vez) por AppHelper.callAfter"
    fn, args, _kwargs = llamadas[0]
    assert fn == c.apply_capture_
    assert list(args[0]) == ["f13"]
    # Como el espía no ejecutó la función diferida, nada tiene que haber
    # cambiado todavía.
    assert c._estado["cancel"]["keys"] == ["esc"]
    assert c._capturing == "cancel"
    c.close()


# ---------- Finding 3 (Menor): el campo de error, con aire de verdad ----------

def _peor_caso_error(font):
    """El mensaje más ancho que puede acabar en _error_text, mirando los DOS
    validadores -shortcuts.validate Y keys.validate_custom(), no solo el
    primero: ese fue justo el defecto que dejó el campo al filo- sobre
    nombres de tecla realmente alcanzables por una captura de una sola
    tecla: las letras y dígitos que reporta pynput.keyboard.KeyCode.char, y
    el catálogo entero de pynput.keyboard.Key (los "media_volume_..." son
    justo el caso "del enum de pynput" que menciona el review)."""
    nombres = set("abcdefghijklmnopqrstuvwxyz0123456789")
    nombres |= {k.name for k in Key}
    nombres |= {"ctrl", "alt", "cmd", "shift"}  # modificadores sin lado

    mensajes = set()
    for nombre in nombres:
        _, msg = keys.validate_custom(nombre)
        if msg:
            mensajes.add(msg)

    estado = {sid: {"keys": list(sc.default)} for sid, sc in shortcuts.SHORTCUTS.items()}
    for sid in shortcuts.SHORTCUTS:
        for otro_sid, fila in estado.items():
            if otro_sid == sid:
                continue
            _, msg = shortcuts.validate(sid, list(fila["keys"]), estado)
            if msg:
                mensajes.add(msg)
    _, msg = shortcuts.validate("dictation", [], estado)
    mensajes.add(msg)
    _, msg = shortcuts.validate("dictation", ["f5"], estado)
    mensajes.add(msg)

    return max(mensajes, key=lambda m: theme.text_width(m, font))


def _alto_necesario(texto, font, ancho):
    """Alto real (con AppKit) que necesita `texto` para no recortarse
    envuelto a `ancho` puntos con `font` -la misma API que usaría un
    NSTextField multilínea para hacer layout de verdad, no una división a
    ojo de theme.text_width() entre el ancho del campo."""
    rect = NSString.stringWithString_(texto).boundingRectWithSize_options_attributes_(
        NSMakeSize(ancho, 1_000_000.0),
        NSStringDrawingUsesLineFragmentOrigin,
        {NSFontAttributeName: font})
    return rect.size.height


def test_el_campo_de_error_puede_dar_a_dos_lineas():
    c = _ctl()
    assert c._error.cell().wraps()
    assert not c._error.usesSingleLineMode()
    c.close()


def test_el_campo_de_error_no_recorta_el_peor_caso_de_los_dos_validadores():
    c = _ctl()
    peor = _peor_caso_error(c._error.font())
    necesita = _alto_necesario(peor, c._error.font(), c._error.frame().size.width)
    assert c._error.frame().size.height >= necesita, peor
    c.close()
