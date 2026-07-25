# Estudio: ventana post-paste para aprender correcciones antes de que el campo desaparezca

## 1. Cómo funciona el auto-learn hoy (v1.8.0)

Flujo actual (`src/voooxly/app.py` + `learn.py` + `axfield.py`):

1. El usuario dicta → se refina → se pega `final` en el campo con foco.
   En ese momento se guarda `self._pending_learn = final` (`app.py:1073`).
2. El usuario corrige palabras en el campo (o se va a otra app).
3. **Recién en el próximo dictado** (`_start_record`, `app.py:734`) se consume
   `pending` y se lanza un hilo daemon `_auto_learn_check(pasted)` (`app.py:1108`).
4. Ese hilo hace **una sola lectura** `axfield.read_focused_text()` del campo
   *que tenga foco en ese momento*, y `learn.auto_learn_from(pasted, field)`
   calcula el diff (sustituciones cortas que suenan parecido, no palabras
   comunes) y guarda las parejas (wrong→right) en el diccionario.

Es decir: **la lectura es un único instante, atado al inicio del dictado
siguiente, del campo que tenga foco en ese instante.**

## 2. El problema (el que describe el objetivo)

- La lectura ocurre en el **próximo dictado**, no tras el paste. Para entonces
  el usuario puede haber **salido del campo**: cerró la terminal, cambió de
  ventana de Slack, abrió otra app. `read_focused_text()` devuelve `None` o un
  campo distinto → `locate_pasted` no encuentra el pegado → **no se aprende nada**
  y la corrección se pierde para siempre.
- Como es una sola lectura puntual, no capta correcciones hechas *después* de
  que el usuario dejó el campo (pero antes del próximo dictado).
- El caso que más duele: el usuario corrige "wisperflow"→"Wispr Flow" apenas
  se pega, **dentro** del campo, pero luego salta a otro Slack; en el próximo
  dictado el campo ya no es legible → la grafía correcta nunca llega al
  diccionario → el error se repite.

## 3. Restricciones que cualquier solución debe respetar

- **Promesa de privacidad**: solo se lee el elemento con foco, en el device, el
  texto nunca se persiste ni se loguea — solo las parejas aprendidas. La
  ventana nueva lee *más veces* pero el **mismo** scope (el campo pegado), sin
  capturas ni otras apps. Mismo opt-out (`auto_learn` en prefs).
- **Sesgo a precisión**: `auto_corrections` ya filtra (sustituciones 1→2,
  suenan parecido, no palabras comunes). La ventana **reutiliza la misma
  función** → no introduce nuevos falsos positivos.
- **Cuándo es legible un campo (AX)**: Slack (compose) ✓, Mail ✓, Notes ✓,
  TextEdit ✓, inputs del navegador ✓, editores nativos ✓. **Terminales ✗**
  (el scrollback no expone `AXValue` como texto editable) — hoy ni el flujo
  actual ni el nuevo pueden aprender ahí; es una limitación aceptada.
  Electron/apps WebKit: varía. La ventana ayuda justamente en los campos
  legibles (Slack, Mail, Notes, editores) capturando la corrección *antes* de
  que el usuario navegue fuera.
- **No tocar la grabación ni la UI**: el hilo de monitoreo solo lee AX + escribe
  diccionario + deja `_learned_note` (mismo patrón que `_auto_learn_check`).
- **Sin dobles problemáticos**: `dictionary.add` es idempotente (una pareja
  "wrong -> right" ya guardada se sobreescribe), así que aprende dos veces la
  misma pareja es inofensivo.

## 4. Solución propuesta: ventana de monitoreo post-paste (10–20 s)

En vez de (o además de) leer en el próximo dictado, **se arranca un hilo en el
momento del paste** que vigila el campo durante una ventana corta y aprende en
cuanto el usuario termina de corregir — antes de que se vaya.

### Disparador
En `app.py` justo después de `self._pending_learn = final` (paste), si
`auto_learn` está on, lanzar `threading.Thread(target=self._auto_learn_watch,
args=(final,), daemon=True).start()`. Mismo patrón ya usado para `_auto_learn_check`.

### Bucle de monitoreo (en `learn.py`, puro y testeable)
Nueva función que recibe un *callable* de lectura (inyectado, para test sin AppKit):

```python
def watch_field(pasted, read, *, window_s=15.0, poll_s=2.0, stable_s=3.0, clock=time.monotonic):
    """Polls read() until the field stabilizes or disappears, then returns the
    text to learn from (the last good read where the paste was located), or None."""
    last_good = None          # último campo donde se vio el pegado
    last_change = clock()
    deadline = clock() + window_s
    while clock() < deadline:
        field = read() or ""
        region = locate_pasted(pasted, field) if field else None
        if region is None:
            # el usuario salió del campo / cambió de app / lo borró:
            # aprendemos de lo último que capturamos (con las correcciones hechas).
            return last_good
        if field != (last_good if last_good is not None else pasted):
            last_change = clock()          # sigue corrigiendo
        last_good = field
        if (clock() - last_change) >= stable_s:
            return last_good               # se aquietó: aprende ya
        sleep(poll_s)
    return last_good                       # ventana agotada: aprende de lo último
```

- **`last_good`** es la clave: aunque el campo desaparezca (terminal/Slack
  switch), conservamos el último estado capturado *con* las correcciones y
  aprendemos de ahí. Resuelve exactamente el caso del objetivo.
- **Debounce `stable_s`**: no aprende estados intermedios; espera a que el
  texto se aquiete ~3 s (el usuario terminó una corrección).
- **Cap `window_s`**: 15 s por defecto (dentro del rango 10–20 que pide el
  objetivo), configurable.

### Aprendizaje
El hilo `watch` devuelve `last_good`; el llamador hace
`learn.auto_learn_from(pasted, last_good)` (misma función de siempre).

- Si aprende parejas → `self._learned_note = note` (lo pinta `_hud` cuando el
  gate esté libre) y **`self._pending_learn = None`** (ya aprendí: no hace
  falta re-leer en el próximo dictado).
- Si no aprende nada (no hubo correcciones, o el campo fue ilegible de entrada)
  → **deja `_pending_learn`** intacto, así el **fallback** del próximo dictado
  (`_auto_learn_check`) sigue cubriendo correcciones tardías hechas después de
  la ventana pero antes del próximo dictado. Complementario, no reemplazo.

### Config (nuevo, en `config.yaml` bajo `learn:` o reusing `app.*`)
- `learn.window_seconds: 15`  (la ventana total)
- `learn.poll_interval: 2.0`  (cada cuánto re-leer)
- `learn.stable_seconds: 3.0`  (debounce: cuándo se considera "terminó")

Gateado por el pref existente `auto_learn` (on por defecto).

## 5. Por qué resuelve el caso terminal/Slack

- **Slack (compose, legible)**: la ventana capta la corrección mientras el
  usuario todavía está en el mensaje (10–20 s). Si salta a otro Slack antes
  de aquietarse, `region is None` → aprende de `last_good` (el último estado
  con la corrección). Hoy se perdía; ahora no.
- **Terminal (ilegible)**: `read()` devuelve `""` desde el inicio → `last_good`
  queda `None` → no se aprende (igual que hoy). Aceptado; los usuarios de
  terminal tienen "Correct last dictation…" (manual) como alternativa. La
  ventana no empeora nada.

## 6. Plan de implementación

1. `learn.py` — añadir `watch_field(pasted, read, *, window_s, poll_s, stable_s)`
   puro (sin AppKit); usa `locate_pasted` y `sleep`/`clock` inyectados.
2. `app.py` — añadir `_auto_learn_watch(self, pasted)`:
   llama `watch_field(pasted, axfield.read_focused_text, **cfg)`, luego
   `auto_learn_from`; setea `_learned_note` y limpia `_pending_learn` si aprendió.
   Lanzar el hilo en el punto de paste (L1073) si `auto_learn` on.
   Mantener `_auto_learn_check` (próximo dictado) como **fallback**.
3. `axfield.py` — sin cambios (`read_focused_text` ya existe y basta). Opcional:
   `focused_signature()` para detectar cambio de campo vía identidad AX (refuerzo;
   `locate_pasted` ya cubre el caso).
4. `config.yaml` — claves `learn.window_seconds/poll_interval/stable_seconds`.
5. Tests `tests/test_learn_auto.py` — casos con un `read` simulado que devuelve
   una secuencia: (a) se aquietó en la ventana → aprende; (b) el campo se va a
   la mitad → aprende de `last_good`; (c) sin cambios → no aprende y deja
   pending; (d) ventana agotada → aprende de `last_good`; (e) ilegible desde el
  inicio → no aprende. `clock` inyectado para no esperar 15 s reales.

## 7. Riesgos y mitigaciones

- **Costo de polling AX**: ~7 lecturas de 15 s × 1 AX read c/u, cap 20 k chars.
  Despreciable frente a la grabación.
- **Falsos positivos**: ninguno nuevo — misma `auto_corrections` (precisión).
- **Editar otra parte del doc grande**: `locate_pasted` aísla la región pegada.
- **Carrera watch vs. próximo-dictado**: idempotente (mismo par sobreescribe);
  si watch aprendió y limpió pending, el fallback no corre.
- **Privacidad**: misma promesa (solo el campo con foco, on-device, sin
  logs/persistencia del texto). La ventana es más larga pero mismo scope y
  mismo opt-out; documentar el trade-off en la guía.

## 8. Conclusión (del estudio original)

El problema real es que la lectura está atada al **próximo dictado** (campo
puede haber desaparecido) y es **un solo instante**. Una **ventana post-paste de
~15 s** que mantiene el `last_good` y aprende cuando el texto se aquietó o el
campo se va, **resuelve el caso Slack/editores** (captura la corrección antes
de que el usuario navegue fuera) sin nuevas superficies de privacidad ni
falsos positivos. Terminales siguen fuera (ilegibles por AX), cubiertos por la
corrección manual. Implementación contenida: 1 función nueva en `learn.py`,
1 método + 1 spawn en `app.py`, claves de config, tests.

---

# 9. Revisión adversarial (25 jul 2026) — §4-§6 quedan superadas

> **Estado: implementado el 25 jul siguiendo esta §9** (no §4-§6, que se dejan
> como registro de lo que se descartó y por qué). Código en `learn.watch_field`,
> `axfield.clip`/`app_locked_reader`, `app.LearnState`/`_watch_and_learn`/
> `_drain_learned_note`, bloque `learn:` de `config.yaml`, y el lock + escritura
> atómica de `dictionary.py`. Tests en `tests/test_learn_watch.py`,
> `tests/test_app_auto_learn.py`, `tests/test_axfield.py`, `tests/test_dictionary.py`.
> **La §9 tal cual seguía sin aprender nada en uso real: ver §10** (la salida por
> sosiego se disparaba sobre el pegado intacto). Gate manual pendiente en
> `docs/superpowers/launch/gate-ventana-post-paste.md`.

El diagnóstico de §1-§2 es correcto y el enfoque es el bueno. **El pseudocódigo
de §4 no lo es**: ejecutado contra las funciones reales de `learn.py`, corrompe el
diccionario de forma permanente y además falla el caso estrella de Slack. Lo que
sigue son los defectos verificados con evidencia, y el diseño corregido.

## 9.1 Bloqueantes — corrupción permanente del diccionario

**B1. Aprende estados a medio teclear.** Dos de las tres salidas (`region is None`
y ventana agotada) devuelven un snapshot **sin debounce**. Los filtros de
precisión NO los rechazan; medido contra `learn.auto_corrections` real con el
`PEGADO` de los tests:

```
'Wispr'      → [('wisperflow', 'Wispr')]
'Wispr F'    → [('wisperflow', 'Wispr F')]
'Wispr Flo'  → [('wisperflow', 'Wispr Flo')]
```

Flujo dominante en Slack: pegar en t=0 → poll en t=2 capta `"Wispr Flo"` → el
usuario teclea `"w"` y pulsa Enter en t=2.6 → el compose se vacía → poll t=4 ve
`region is None` → aprende `wisperflow -> Wispr Flo`.

Es **irreversible por diseño**: `dictionary.apply` (`dictionary.py:85-100`) es
global, whole-word e IGNORECASE y corre en `app.py:1047` **antes** del paste, así
que "wisperflow" ya nunca vuelve a aparecer en un dictado → esa clave no se puede
re-aprender ni sobreescribir nunca. Y `dictionary.add:59-60` **además** hace
`words.append(right)`: la basura truncada queda para siempre en el prompt inicial
de Whisper (no hay API de borrado en el módulo). La afirmación de §7 "falsos
positivos: ninguno nuevo" es falsa — `auto_corrections` no cambia, pero se le
alimentan estados que la lectura única nunca podía producir.

**B2. `dictionary.add` no es thread-safe ni atómico** (bug preexistente que el
plan amplifica). `dictionary.py:50-71` es un read-modify-write sin lock que
termina en `path.write_text` (sin tmp+rename). Es el único módulo con estado
compartido sin `Lock`. Medido por el verificador (dos `add` sincronizados por
barrera, dict de 40 pares, 400 pruebas): **385 lost updates, 11 colapsos a un
solo par, 9 lecturas devolviendo diccionario vacío**, y tres escritores dejaron
el fichero corrupto en disco — tras lo cual `load()` (`:37-41`) se traga el error
y devuelve `{}` para siempre, en silencio. Hoy la escritura está clavada a ~100ms
al inicio de una grabación; el plan la mueve a un instante que decide el usuario
al dejar de teclear, y admite N watchers concurrentes. Súmale el thread daemon:
si el usuario sale de la app entre el `open(truncate)` y el `write`, se queda sin
diccionario.

→ **Arreglar `dictionary.py` (lock + `os.replace` desde tmp) es prerrequisito, e
independiente de esta feature. Vale la pena hacerlo ya.**

**B3. El corte de 20 000 chars puede partir una palabra.** `axfield.py:41`
(`val[:_MAX_FIELD_CHARS]`) corta por carácter. Si el corte cae dentro de la
**última** palabra de la región pegada sale un `replace` 1→1 legítimo: verificado,
`auto_corrections` devuelve `[('mañana', 'maña')]` (`_is_common('mañana')` es
False). Una sola lectura casi nunca acierta ese punto; 7 lecturas mientras el
usuario teclea **encima** del pegado barren el punto de corte un carácter por
pulsación.
→ Fix de una línea en `axfield.py`: descartar el token parcial final cuando se
trunca (`re.sub(r"\S+$", "", cut)`), así el diff ve un *delete* (que `corrections`
ignora) y no un *replace*.

## 9.2 El plan falla su propio caso estrella

**C1. La primera lectura llega antes que el ⌘V.** `output.deliver:123-126` hace
`sleep(0.08)` **antes** de `paste_frontmost()`, que postea CGEvents y retorna
(`output.py:95-109`); la app destino inserta el texto de forma asíncrona (en
Electron, además, con caché AX asíncrona). `app.py:1073` es la sentencia
siguiente → el primer `read()` sale a los milisegundos, el campo aún no tiene el
pegado, `locate_pasted` falla el ratio 0.6 y el pseudocódigo hace
`return last_good` = `None` **en la iteración 1**. Nada distingue "todavía no
está" de "ya no está". Consecuencia: no corrompe nada, pero la feature puede no
dispararse nunca en las apps para las que se diseñó.

**C2. Hay una ventana ciega de `poll_s`.** `last_good` es tan fresco como el poll
anterior, así que "el campo se fue → aprendo de `last_good`" solo funciona si un
poll cayó **entre** la última edición y la marcha. `corrige → Enter` en menos de
2 s (el flujo dominante en Slack) devuelve el pegado **sin corregir** → no
aprende nada. §5 afirma que ese caso queda resuelto; queda resuelto solo si el
usuario se queda quieto ≥ `poll_s` después de corregir.

**C3. `region is None` también salta mientras el usuario sigue editando.** Con
`_LOCATE_MIN_RATIO = 0.6`, en un pegado de 4 palabras corregir la segunda ya baja
del umbral (medido: 4 palabras / 2 corregidas → `None`). El watcher sale 11 s
antes de tiempo **y**, si el snapshot previo dio algún par, limpia
`_pending_learn` → el fallback del próximo dictado tampoco lee la corrección
terminada. Los dictados cortos (los que pasan por fast-lane, `app.py:1018-1024`)
son el peor caso: 1-2 palabras no sobreviven a ninguna corrección.

**C4. El debounce compara el campo entero, no la región.** `field != last_good`
sobre todo el `AXValue`: si el usuario sigue escribiendo el párrafo siguiente en
Notes, `last_change` se resetea cada poll, la salida estable no dispara nunca, se
queman los 15 s y se aprende del snapshot de t≈14 (media palabra). El debounce
está invertido: protege de lo que no importa (ediciones lejos del pegado) y no
dispara en lo que sí. (Detalle menor de la misma línea: en la iteración 1 compara
`field != pasted`, un documento entero contra el fragmento insertado — siempre
cierto aunque no se haya editado nada.)

## 9.3 Consentimiento y feedback

**D1. El "✨ Learned" no se pinta nunca a tiempo.** `_learned_note` tiene **un
solo** consumidor: `app.py:1104`, en la cola de `_process`, ~1.6-2.2 s después del
paste (`:1096-1097` + `:1101`). `watch_field` no puede retornar antes de
`stable_s`, o sea t≈4-6 s como pronto: **siempre después del drenaje**. La nota
se queda en memoria hasta el final del *siguiente* dictado (minutos después,
junto a un texto que no tiene nada que ver) o para siempre si el usuario deja de
dictar. Peor: la ruta que compone la nota ya ha volcado y persistido
`auto_learn_seen` (`:1126-1129`), así que el aviso único "Turn off in Settings if
you prefer" **se consume sin que nadie lo vea** — el usuario nunca se entera de
que se instaló un reemplazo global.
→ `_hud` (`app.py:892`) sí es seguro desde un hilo daemon (lanza su propio hilo y
comprueba el gate). El watcher debe pintar directo cuando el gate está IDLE, y
solo aparcar en `_learned_note` si no lo está. Y mover el flip de
`auto_learn_seen` al momento en que la nota se pinta de verdad.

**D2. El opt-out es lo que dispara el aprendizaje final.** Tras el paste no hay
forma de abortar la ventana: Esc hace no-op con el gate IDLE (`app.py:715-717`) y
`_toggle_auto_learn` (`:481-485`) toca un dict que el hilo ya no vuelve a leer.
Si el usuario ve un pegado que no quería y **abre la barra de menús para apagar
auto-learn**, abrir el menú mueve `AXFocusedUIElement` → el siguiente poll ve
`region is None` → el watcher **aprende de salida**, como consecuencia directa de
su clic de opt-out.

## 9.4 Colisiones de estado

**E1. `_pending_learn` clobber** (confirmado, severidad baja). El gate vuelve a
IDLE ~1.6 s tras el paste, así que el paste B cae a los ~6-9 s de la ventana de A;
como B se **añade** al mismo campo, A sigue localizable y su watcher sobrevive a
B y luego hace `_pending_learn = None`, borrando el fallback de B.
→ Comparar-y-limpiar por generación (no por string: dos dictados idénticos son
iguales), bajo un `self._learn_lock`.

**E2. N watchers a la vez.** Con `silence_to_stop=1.2` + fast-lane, los pastes van
a ~5 s → 3-4 watchers **más** el hilo de fallback conviviendo dentro de los 15 s,
todos escribiendo el diccionario (ver B2).
→ Token de generación + `threading.Event` de parada pasado a `watch_field`; el
watcher superado hace un último intento con **su** `pasted` y sale (cancelarlo a
secas perdería las correcciones tardías del pegado anterior).

**E3. El spawn está mal colocado y sin envolver.** §4 lo pone justo tras
`_pending_learn = final` (`app.py:1073`), es decir **antes** de
`_record_token_usage` (`:1078`), del aviso "AI didn't answer" (`:1085`) y del
"Press ⌘V to paste it" (`:1090`) — el único que rescata un paste fallido. Un
`RuntimeError: can't start new thread` lo captura el `except` de `:1098` y se
salta los tres. Es literalmente el "Finding 3" que ya tiene test en
`tests/test_record_token_usage.py`; el spawn de `_start_record:736-740` sí está
envuelto por eso.
→ Spawn **después** de `:1078` y con `try/except`, igual que `:736-740`.

## 9.5 Tests: el plan tal cual cuelga la suite

La firma de §4 inyecta `clock` pero llama a `sleep(poll_s)` a pelo (§6.1 dice que
se inyecta — la firma normativa y el plan de tests se contradicen). Ejecutado:

- caso (d) con reloj falso y `sleep` real → **16,1 s reales** por test.
- con reloj falso congelado → **bucle infinito** (1812 iteraciones en 3 s): las
  únicas salidas dependen de que el reloj avance. No hay `pytest-timeout` ni CI,
  o sea que cuelga la suite indefinidamente.
- `learn.poll_interval: 0` en config → mismo spin, en producción.

Además §6.5 (c) y (e) afirman estado de `app.py` (`_pending_learn`) desde un test
de una función pura que no lo ve, y ninguno de los cinco casos comprueba lo único
que importa en este módulo: **qué acaba en el diccionario** (todos los tests
existentes de `test_learn_auto.py` terminan en `dictionary.load(dic)` con
`tmp_path`).

## 9.6 Config sin validar

`config.py:44-51` (`_deep_get`) devuelve el valor crudo del YAML, sin coerción ni
clamp, y `config.load_config` (`:105-109`) coge el **primer** candidato existente
**sin merge**: `~/.voooxly/config.yaml` tapa el fichero del bundle entero, así que
los usuarios actuales no verán jamás el bloque `learn:` nuevo.
→ Toda clave nueva necesita default en el `cfg.get(...)` **y** clamp:
`poll_s` con suelo, `window_s` acotado, y tolerar strings.

## 9.7 Diseño corregido (`learn.py`)

Cambios mínimos que cierran B1, C1, C3, C4 y el hang de tests. La regla nueva es
**"solo se aprende de un estado visto quieto"**: `last_stable` = lectura vista
idéntica dos veces seguidas; las salidas por marcha/timeout devuelven eso, nunca
la última lectura cruda.

```python
def watch_field(pasted, read, *, window_s=15.0, poll_s=2.0, stable_s=3.0,
                acquire_s=4.0, clock=time.monotonic, sleep=time.sleep):
    poll_s = max(float(poll_s), 0.25)          # un 0 en config = spin infinito
    window_s = max(float(window_s), 0.0)
    deadline = clock() + window_s
    acquire_deadline = clock() + min(acquire_s, window_s)
    polls_left = int(window_s / poll_s) + 2    # cota dura (reloj falso congelado)
    last_good = last_region = last_stable = None
    last_change = clock()
    while polls_left > 0 and clock() < deadline:
        polls_left -= 1
        try:
            field = read() or ""
        except Exception:
            field = ""                          # best-effort como todo el módulo
        region = locate_pasted(pasted, field) if field else None
        if region is None:
            if last_good is None:               # el ⌘V aún no ha aterrizado
                if clock() >= acquire_deadline:
                    return None                 # ilegible de verdad (terminal)
                sleep(poll_s)
                continue
            return last_stable                  # se fue: solo lo confirmado quieto
        if last_good is not None and locate_pasted(last_good, field) is None:
            return last_stable                  # se parece, pero es OTRO campo
        if last_region is None or region != last_region:
            last_change = clock()               # debounce sobre la REGIÓN, no el doc
        else:
            last_stable = field                 # visto igual dos veces: válido
        last_good, last_region = field, region
        if (clock() - last_change) >= stable_s:
            return field                        # se aquietó estando presente
        sleep(poll_s)
    return last_stable                          # timeout: solo lo confirmado quieto
```

Coste consciente: una corrección hecha y abandonada dentro de un mismo intervalo
de poll se pierde. Es el trade correcto bajo el sesgo de precisión del módulo
(`learn.py:5-10`), y el fallback del próximo dictado (`app.py:734`) sigue
cubriéndola siempre que el campo sobreviva.

**Sobre `focused_signature()` (§6.3): NO hacerlo obligatorio.** El verificador lo
midió: la identidad de `AXUIElementRef` rota en cada re-render del DOM justo en
Electron/WebKit (Slack, inputs de navegador), o sea que fallaría cerrado
precisamente donde la feature debe funcionar, y bloquearía un caso legítimo
(enviar en Slack → clicar el mensaje enviado para editarlo = otro elemento, mismo
texto, aprender es correcto). El pid es barato pero no cierra el caso intra-app
(otro hilo de Slack = mismo pid). La **comprobación de continuidad**
(`locate_pasted(last_good, field)`, arriba) cubre el hueco real sin ese coste.

## 9.8 Cambios en `app.py`

1. Spawn **después** de `_record_token_usage` (`:1078`), envuelto en `try/except`.
2. `self._learn_lock = threading.Lock()`, `self._learn_gen = 0`, `self._learn_stop`.
   Bajo el lock: `Event` anterior `.set()`, `Event` nuevo, `gen += 1`,
   `_pending_learn = final`.
3. Al terminar el watcher, bajo el lock: `if gen == self._learn_gen:
   self._pending_learn = None`, y **acumular** la nota en vez de sobreescribirla.
4. Extraer el drenaje de `:1104-1106` a `_drain_learned_note()`: si el gate está
   IDLE → `_hud` directo; si no → volver a aparcar (hoy `_hud._do` **descarta** el
   mensaje si el gate dejó de estar IDLE, `:906`/`:912`).
5. Mover el flip de `auto_learn_seen` (`:1126-1129`) al momento en que la nota se
   pinta, y compartirlo entre `_auto_learn_check` y el watcher.
6. `dictionary.py`: `_lock` de módulo sostenido a lo largo de load+write, y
   `os.replace` desde un tmp en el mismo directorio. `learn._persist` toma el lock
   una vez para toda la lista en vez de reescribir el fichero por par.

## 9.9 Tests que faltan

Ficheros nuevos `tests/test_learn_watch.py` (bucle puro) y
`tests/test_app_auto_learn.py` (integración, sin instanciar `VoooxlyApp` — patrón
de `test_app_shortcuts.py`). Harness: reloj falso **avanzado por el sleep falso**
(`watch_field` llama a `clock()` 2-3 veces por iteración; una lista de timestamps
se desincroniza).

Casos que el plan no cubre y que deciden el diseño: ⌘V aún en vuelo (`None`
inicial); parpadeo de foco de un solo poll; se va a medio teclear → **no** aprende;
se aquieta y **luego** se va → sí aprende; timeout tecleando → no aprende; teclear
lejos del pegado; `poll_s=0` / `window_s=0` / `stable_s=0`; `read()` que lanza;
campo truncado en el cap; presupuesto de lecturas AX; opt-out `auto_learn: False`
→ cero lecturas; el spawn que falla no rompe la cola de `_process`; los valores de
config llegan a `watch_field`; `caplog` en DEBUG sin texto del campo (promesa de
privacidad); y en todos los de persistencia, aserción contra `dictionary.load`
con `tmp_path`.

## 9.10 Decisión de producto pendiente (no es un bug: es tuya)

El spec aprobado —`docs/superpowers/specs/2026-07-25-auto-learn-design.md`— dice
en **Non-goals: "Timers/observers en background"**, y en `:3` que la lectura al
siguiente dictado fue tu decisión explícita *tras revisar la evidencia de Wispr
Flow* (cuyo escándalo, dice `:5`, "fue por screenshots/tracking en background, NO
por leer el campo puntualmente"). Esta ventana **es** un observer en background.

Y el argumento de privacidad de §3 ("mismo scope, más lecturas") no se sostiene
tal cual: `axfield.py:30-31` resuelve `AXFocusedUIElement` **system-wide**, sin
ninguna atadura al elemento donde se pegó. No lee *el mismo elemento más veces*:
lee *más elementos, una vez cada uno*, y la lectura terminal es por construcción
la del momento en que el usuario se fue — el más probable de ser otro contexto.

Texto público que dejaría de ser cierto (dice "once" y "only the field it just
pasted into"):
- `README.md:48` y `README.md:28`
- `voooxly-web/index.html:610` (y FAQ `:696`), `voooxly-web/appcast.json:4`
- cuerpo de la release **v1.8.0 ya publicada** ("reads only the field it just
  pasted into, once, entirely on your Mac")
- `src/voooxly/axfield.py:1-5` ("Point-in-time read… one read"),
  `app.py:264-265`, `:731-733` ("exactly once… One attempt per paste"),
  `:1071-1072`, `:1108-1115`
- guía in-app (`guide.py:86-88` no menciona auto-learn; §7 promete documentarlo →
  tocar `sections()` rompe `tests/test_guide.py:73-94`, que fija los 9 títulos)
- gate manual `docs/superpowers/launch/gate-domingo.md:6-25` (el ciclo
  "corrige → dicta → HUD" ya no aplica; faltan 3 casos adversarios nuevos: dejar
  el campo a medias, enfocar otro campo normal dentro de los 15 s, enfocar un
  campo de contraseña dentro de los 15 s)

No es un veto: es que **cambiar la promesa hay que hacerlo a propósito y por
escrito** (enmendar el spec con fecha y rationale, y reescribir README/web antes
de que salga la build), no como efecto colateral de una mejora. Con el lanzamiento
en PH/HN/Reddit el 28-30, esa es la decisión que va primero.

## 9.11 Lo que se **refutó** de la crítica

- Gatear el watcher por `status == "pasted"`: innecesario. Sin paste, `locate_pasted`
  falla en la iteración 1 y el hilo muere tras **una** lectura — el mismo coste que
  hoy. Vale como higiene, no como fix.
- El overlay **no** roba foco: `NSWindow` borderless (`overlay.py:78-83`) mostrado
  con `orderFrontRegardless()` (`:208`); `makeKeyAndOrderFront_` solo aparece en
  `guide.py`, `onboarding.py` y `settings_window.py`.
- Pares contradictorios entre watchers concurrentes: no ocurre, `locate_pasted`
  aísla cada pegado. El daño de la concurrencia es el fichero (B2), no los pares.
---

# 10. Lo que encontró la primera prueba real (25 jul 2026, tarde)

La §9 se implementó entera y con 650 tests en verde, y **aun así la ventana no
aprendía nada** en uso real. Ocho dictados seguidos en Word y en Notes dieron
siempre lo mismo:

```
Auto-learn: watching the pasted field for up to 15.0s.
Auto-learn: nothing learned (3 polls, 3 readable, 3 located; role=AXTextArea, 62 chars readable).
```

## 10.1 Diagnóstico

Las trazas descartaron de entrada la hipótesis fácil: `3 readable, 3 located`
significa que Word **sí** expone el texto por AX y que `locate_pasted` encontró
el pegado. La sospecha de §5 de que Word no fuese legible era falsa.

La causa está en la salida por sosiego de `watch_field`. La condición era
«llevamos `stable_s` sin cambios» — y **el texto recién pegado siempre está
quieto**, porque la persona todavía no ha empezado a corregir. Con
`acquire_s=4`, `poll_s=2` y `stable_s=3` la ventana cumplía la condición a los
4 s y se marchaba con el pegado intacto, antes de que nadie hubiera hecho doble
clic en la palabra. Por eso toda corrección seguía cayendo en el fallback del
dictado siguiente, que es justo lo que esta ventana venía a sustituir.

## 10.2 El arreglo

`base_region` guarda el pegado tal como aterrizó, y la salida por sosiego exige
`region != base_region`: **quieto tiene que significar quieto DESPUÉS de una
corrección**, no quieto porque nadie ha tocado nada. Un campo que nadie toca ya
no sale a los 4 s: se vigila hasta agotar la ventana y no enseña nada, que es lo
correcto.

## 10.3 Por qué los tests no lo cazaron

Todos los tests de `watch_field` daban un campo **ya corregido** en la segunda
lectura. Ninguno modelaba a una persona tardando ocho segundos en localizar la
palabra. Los dos tests que faltaban, y que fallan sin el arreglo con la firma
exacta de producción (`assert 4.0 >= 15.0`):

- `test_waits_for_the_correction_instead_of_settling_on_the_untouched_paste`
  — cuatro lecturas idénticas del pegado y la corrección en la quinta.
- `test_a_field_nobody_touches_is_watched_to_the_end_and_teaches_nothing`
  — nadie toca nada: se agota la ventana y no se aprende.

Lección para el resto del módulo: los fixtures de dos pasos («estado inicial →
estado final») no modelan latencia humana, y esta feature vive entera en esa
latencia.

## 10.4 Verificado en uso real

Con el arreglo instalado, el HUD "✨ Aprendido" sale a los pocos segundos de
terminar de corregir, sin dictar nada más. Queda por medir si 15 s bastan: una
corrección que termine pasado t≈12 todavía cae en el fallback. No se ha subido
`window_seconds` a ojo — la señal para hacerlo es ver en el log la línea de
resultado ~15 s después de `watching…` mientras la persona seguía corrigiendo.
