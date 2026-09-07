# Análisis técnico — Tibia Mapper

**Fecha:** 2026-09-07
**Rama analizada:** `feature/ai-advisor`
**Alcance:** revisión estática completa del código Python, frontend, empaquetado y datos de sesión (`logs/`, `settings.json`, `routines/`, `battle_targets/`).

---

## 1. Resumen ejecutivo

Tibia Mapper es una herramienta local de **mapeo de pantalla en tiempo real** para Windows, construida sobre Flask + PIL + DXGI. Captura frames de un monitor, recorta regiones configurables, las compara contra plantillas de referencia y reacciona a los cambios: detecta objetivos en el panel Battle, sigue el panel Loot para saber cuándo terminó un ciclo, lee HP por OCR y ejecuta rutinas de coordenadas grabadas manualmente.

**Lo que está sólido:**

- La separación captura/lectura (DXGI, coordenadas locales del monitor) vs interacción (coordenadas reales de Windows) está bien pensada y documentada en `CODEX_CONTEXT.md`.
- La migración de Bestiary/OCR a Loot/comparación visual como señal de fin de ciclo bajó el escaneo de **~10.000 ms a ~70 ms** (comparar entradas `BATTLE PERF` en `logs/session_20260906_09*.log`). Fue la decisión de arquitectura más rentable del proyecto.
- La persistencia junto al ejecutable (`app_paths.py`) permite actualizar binarios conservando rutinas, eventos y referencias.
- El aislamiento de estado con `BattleRuntimeState` + lock no bloqueante evita escaneos superpuestos.
- Instrumentación abundante: `BATTLE PERF`, `BATTLE MATCH DEBUG`, `HEALTH ALERT`, más un log estructurado JSONL (`event_audit_log.py`).

**Lo que bloquea la evolución:**

1. **El bucle de tiempo real vive en el navegador**, no en el backend. Si se cierra la pestaña, el monitor muere.
2. **Contradicción de diseño crítica:** todo el código y la documentación declaran "solo observación, sin input automático", pero `/api/battle/scan-passive` sí ejecuta clicks reales — con **coordenadas hardcodeadas** que ignoran la detección.
3. **El motor de matching es O(W·H·w·h) en Python puro.** Funciona hoy por casualidad geométrica; se cae en cuanto la plantilla sea más pequeña que la región.
4. **El subsistema de Eventos es un stub completo.** `analyze_event_region()` siempre devuelve `detected: False` y todos los handlers de acción son `TODO`.
5. **Los checkpoints se capturan pero nunca se usan.** El ejecutor de rutinas ignora `validation_image`.

---

## 2. Arquitectura

### 2.1 Mapa de módulos

```
┌─ Entrada ──────────────────────────────────────────────────┐
│ app.py          Flask + API REST (602 líneas, 40+ rutas)   │
│ app_ai.py       app.py + rutas IA/mapa + inyección de JS   │
│ launcher.py     Entrada del EXE (importa app.py, NO app_ai)│
│ app_paths.py    Rutas runtime vs recurso (PyInstaller)     │
└────────────────────────────────────────────────────────────┘
          │
┌─ Captura ──────────────────────────────────────────────────┐
│ capture_utils.py   DXGI continuo (dxcam) + hotkeys Win32   │
│                    + fallback legacy NVIDIA Alt+F1         │
└────────────────────────────────────────────────────────────┘
          │
┌─ Percepción ───────────────────────────────────────────────┐
│ battle_monitor.py    Template matching + máquina de estados│
│ checkpoint_store.py  Captura/comparación de checkpoints    │
│ bestiary_reader.py   OCR RapidOCR (bestiary + HP)          │
│ health_monitor.py    Hilo pasivo de OCR de vida            │
│ screen_event_monitor.py  Monitor de eventos (STUB)         │
└────────────────────────────────────────────────────────────┘
          │
┌─ Decisión ─────────────────────────────────────────────────┐
│ decision_engine.py   Reglas explicables, advisory-only     │
│ ai_advisor.py        Ollama qwen2.5:3b + fallback heurístico│
│ tibia_map_service.py Lectura offline de tibia-map-data     │
└────────────────────────────────────────────────────────────┘
          │
┌─ Acción ───────────────────────────────────────────────────┐
│ routine_executor.py       Recorrido de pasos + hotkeys     │
│ mouse_helpers.py          pyautogui + handlers (TODO)      │
│ battle_action_executor.py Click Battle (coords fijas)      │
│ recorder.py               Grabación F9/F11/F12             │
└────────────────────────────────────────────────────────────┘
          │
┌─ Persistencia ─────────────────────────────────────────────┐
│ routine_store / event_store / battle_store  JSON por archivo│
│ settings_store   settings.json normalizado                 │
│ mapper_store     SQLite (map_points)                       │
│ session_log / event_audit_log   .log + .jsonl              │
└────────────────────────────────────────────────────────────┘
```

### 2.2 La regla de coordenadas

Es el invariante central del proyecto:

```
LECTURA / ANÁLISIS  →  DXGI / escena OBS / coordenadas locales del monitor
INTERACCIÓN         →  coordenadas reales de la pantalla de Windows
```

`settings.dxgi_output_idx` selecciona qué monitor lee el capturador. Todas las regiones (`battle_event_region`, `loot_tracker_region`, `health_value_region`, `map_validation_region`) son coordenadas **dentro de ese monitor**. Las coordenadas de las rutinas y de `click_atack_on_battle()` son del escritorio completo. Mezclarlas es la fuente de error más probable del sistema.

**Excepción no documentada:** `screen_event_monitor.py:114` usa `ImageGrab.grab(all_screens=True)` — coordenadas del escritorio virtual, no DXGI. Rompe el invariante.

---

## 3. Funcionamiento por subsistema

### 3.1 Captura DXGI (`capture_utils.py`)

Una única cámara `dxcam` global (`_LIVE_CAMERA`) en modo `video_mode=True` a 30 FPS, protegida por `_LIVE_CAPTURE_LOCK`. `get_live_frame()` devuelve el último frame disponible más metadatos (`source`, `output_idx`, `acquire_ms`, dimensiones).

**Coste medido:** 8–14 ms por frame (`capture_ms` en los logs). Excelente.

Si cambia `dxgi_output_idx`, la cámara se detiene y se recrea. Si falla el arranque, el error se cachea en `_LIVE_CAPTURE_ERROR` y **no se reintenta nunca más** en la vida del proceso — hay que reiniciar la app.

También expone helpers Win32 por polling de `GetAsyncKeyState`: `wait_for_f12_position`, `wait_for_f12_region` (4 pulsaciones = x, y, ancho, alto), `wait_for_tibia_f10`.

### 3.2 Detección Battle (`battle_monitor.py`) — el núcleo

Máquina de estados de dos fases sobre `BattleRuntimeState`:

```
        ┌──────────────────────────────────────────┐
        │              idle                        │
        │  _scan_idle(): busca plantillas dentro   │
        │  de battle_event_region                  │
        └───────────────┬──────────────────────────┘
                        │ match ≥ battle_similarity_threshold (0.90)
                        │ guarda snapshot de loot_tracker_region
                        ▼
        ┌──────────────────────────────────────────┐
        │        waiting_loot_change               │
        │  _scan_tracking(): compara Loot actual   │
        │  contra el snapshot                      │
        └───────┬───────────────────────┬──────────┘
                │ similitud < 0.975     │ elapsed ≥ 5 s
                │ × N confirmaciones    │
                ▼                       ▼
          loot_changed              timeout
                └───────────┬───────────┘
                            ▼  vuelve a idle
```

Detalles clave:

- **En fase `tracking` no se buscan objetivos nuevos.** Solo se compara Loot. Esto es lo que hace que el escaneo cueste ~10 ms en vez de ~70 ms.
- El timeout de 5 s es un *fallback de seguridad*, no el camino normal.
- `loot_change_confirmations = 1` en la configuración actual: un solo frame por debajo del umbral libera el ciclo. Sensible a parpadeos del cliente.

**Métrica de similitud** (`_similarity`, líneas 41–52): error absoluto medio normalizado sobre el diff RGB.

```python
error = sum((index % 256) * count for index, count in enumerate(histogram))
similarity = 1.0 - (error / (255 * pixels))
```

Es correcta pero **muy poco discriminante**: dos crops oscuros distintos dan ~0,98. Por eso los umbrales tienen que estar en 0,975 y no en 0,80. No es invariante a brillo, escala ni desplazamiento sub-píxel.

**Búsqueda de plantilla** (`_best_match`, líneas 54–77): fuerza bruta con `scan_step`.

| Escenario | Posiciones evaluadas | Píxeles comparados | Tiempo |
|---|---|---|---|
| Actual: región 420×480, plantilla 420×55, step 2 | 1 × 213 = **213** | ~4,9 M | **~68 ms** ✔ |
| Plantilla 120×20 (icono de criatura) | 151 × 231 = **34.881** | ~84 M | **~1,2 s** ✖ |
| Lo anterior × 5 objetivos | — | ~420 M | **~6 s** ✖✖ |

Con `battle_poll_seconds = 1.0`, el tercer caso hace que cada escaneo tarde más que el intervalo de polling. Funciona hoy **solo porque la plantilla ocupa todo el ancho de la región**, dejando una única posición horizontal.

### 3.3 Rutinas (`routine_executor.py`, `recorder.py`)

**Grabación** — hilo con polling de teclas cada 50 ms:

| Tecla | Acción |
|---|---|
| `F12` | Añade la posición actual del cursor como paso |
| `F11` | Captura checkpoint DXGI de `map_validation_region` para el último paso |
| `F9` | Alterna muestreo automático cada 2 s |

**Ejecución** — espera Tibia en primer plano + `F12`, luego recorre los pasos:

- `F12` durante la ejecución: pausa/reanuda.
- `Ctrl+F12`: detiene.
- `step_delay_seconds` (2 s) entre pasos, interrumpible.
- Si `event_config.detected_enabled`, arranca un hilo `monitor_events` en paralelo restringido a la categoría `move_mouse`.

**Hueco funcional:** `execute_step()` (`mouse_helpers.py:41`) solo hace `moveTo` + `click`. El campo `validation_image` viaja en el record (`routine_executor.py:78`), se registra en el log (línea 197) y **nunca se compara**. Toda la infraestructura de checkpoints (`checkpoint_store.compare_checkpoint`, la ruta `/checkpoint/compare`, `validation_similarity_threshold`, `validation_timeout_seconds`, `validation_poll_seconds`) existe pero está desconectada del ejecutor.

### 3.4 Health Monitor (`health_monitor.py`)

Hilo daemon que cada 5 s captura DXGI, recorta `health_value_region`, corre RapidOCR con `scale_override=2` y aplica reglas estrictas (`bestiary_reader.read_health_number`): solo acepta un token que sea `\d{1,6}` completo y ≤ `health_ocr_max_value`. Rechaza explícitamente concatenar tokens separados — el bug de "920 261 108" → `920261108` ya está corregido.

Registra `HEALTH ALERT` al cruzar el umbral hacia abajo y `HEALTH RECOVERY` al volver. `ai_routes._health_context_for_ai()` anula `last_value` cuando `last_read_valid` es falso, para no darle a la IA una lectura vieja como si fuera actual — buen detalle.

**Problema de arranque:** `settings_store.py:167` lanza el monitor con un `threading.Timer` **a nivel de módulo**. Importar `settings_store` desde cualquier script (un test, un CLI, un notebook) arranca un hilo de OCR y abre la cámara DXGI como efecto colateral invisible.

### 3.5 Eventos (`screen_event_monitor.py`) — no funcional

La infraestructura de concurrencia está bien construida: `EventRuntimeState` con lock, workers por evento, encadenamiento con detección de ciclos (`seen`), filtro por categorías permitidas, `event_busy` para pausar la rutina.

Pero el detector es un stub:

```python
# screen_event_monitor.py:117-131
def analyze_event_region(event, image):
    ...
    return {"detected": False, ..., "reason": "Detector todavía no definido para este evento."}
```

Consecuencia en cascada: nunca se lanza un worker → `wait_for_event_to_finish` es código muerto → los 5 handlers de `mouse_helpers.py` (`_prepare_click`, `_prepare_write`, `_prepare_move_mouse`, `_prepare_detect_text`, `_prepare_custom`) son todos `TODO`. **El subsistema de eventos no hace nada hoy.**

### 3.6 Capa IA (`ai_advisor.py`, `decision_engine.py`)

Dos motores independientes y ambos correctamente **advisory-only**:

- **`decision_engine.decide()`** — reglas puras, sin efectos secundarios, con `Decision` inmutable y `advisory_only: True`. Cascada: HP < 30 % → `attention_required`; escaneo en curso → `wait_for_scan`; objetivo bloqueado → `keep_observing_current`; hay candidatos → `prioritize_target`; si no → `no_target`.
- **`ai_advisor.analyze_context()`** — construye contexto estructurado (battle + health + recording + rutina + últimas 80 líneas de log + mapa opcional), lo manda a Ollama `qwen2.5:3b` con `format: json`, y si falla cae a `_heuristic_advice()`. El fallback nunca lanza excepción.

`analyze_routine_path()` es una utilidad útil de geometría: cuenta coordenadas, distancia total, pares casi duplicados (≤ 8 px), saltos grandes (≥ 250 px) y segmenta en tramos `quiet`/`move`. Pensado para limpiar grabaciones F9 ruidosas.

### 3.7 Mapas offline (`tibia_map_service.py`)

Lee el clon local de `tibiamaps/tibia-map-data`. Traduce posición Tibia → píxel de floor (`x - xMin`, `y - yMin`), lee el RGB del mapa y del pathfinding:

| Color | Estado |
|---|---|
| `#FFFF00` | no caminable |
| `#FF00FF` | inexplorado |
| gris (R=G=B) | caminable, `friction` = valor |

Cero peticiones remotas por consulta. Devuelve también marcadores cercanos por radio y la URL del visor.

---

## 4. Modelo de datos

| Recurso | Formato | Ubicación | Notas |
|---|---|---|---|
| Rutinas | JSON, 1 archivo por rutina | `routines/<slug>.json` | `id` derivado del nombre de archivo |
| Eventos | JSON, 1 por evento | `events/<slug>.json` | |
| Objetivos Battle | JSON índice + PNGs | `battle_targets/targets.json` + `images/` | |
| Checkpoints | PNG | `checkpoints/<rutina>/step_NNNN.png` | |
| Configuración | JSON normalizado | `settings.json` | |
| Puntos de mapa | SQLite | `data/mapper.db` | Única tabla: `map_points` |
| Log de sesión | Texto | `logs/session_<ts>.log` | Uno por arranque, sin rotación |
| Auditoría de acciones | JSONL | `logs/action_events.jsonl` | Crece sin límite |
| Snapshots OCR | JSONL | `data/bestiary_snapshots.jsonl` | Crece sin límite |

**Escrituras sin bloqueo ni atomicidad:** los tres stores JSON hacen `read → modify → write_text()` completo. Dos peticiones HTTP concurrentes sobre la misma rutina pierden una de las dos escrituras. Un fallo a mitad de `write_text()` deja el archivo truncado y `list_routines()` lo salta silenciosamente con `except Exception: continue` — la rutina desaparece de la UI sin ningún aviso.

---

## 5. Hallazgos concretos

### 5.1 Bugs

| # | Severidad | Ubicación | Problema |
|---|---|---|---|
| B1 | **Alta** | `battle_action_executor.py:19` | `"ok": {resultAction.get('ok')}` construye un **set** `{'ok'}`, no un booleano. El log imprime `action_ok={'ok'}` y el valor no es serializable a JSON si algún día se devuelve por la API. Debe ser `bool(resultAction.get("ok"))`. |
| B2 | **Alta** | `mouse_helpers.py:20` | `click_atack_on_battle(x=3196, y=681)` tiene **coordenadas hardcodeadas** que ignoran por completo `screen_x`/`screen_y` del match detectado. Todo el pipeline de detección visual termina clicando siempre en el mismo punto fijo. |
| B3 | **Alta** | `app.py:249` | `/api/battle/scan-passive` ejecuta `execute_battle_action()` → click real + `press("a")`. Contradice `battle_observation.input_executed: False` que se escribe en el log de auditoría (`battle_monitor.py:329`) y toda la documentación "advisory-only". El registro de auditoría es **falso**. |
| B4 | **Alta** | `capture_utils.py:246` | `get_live_frame()` acepta `tibia_title` pero **nunca lo usa**. Combinado con B3: la app hace clicks aunque Tibia no esté en primer plano — puede clicar sobre cualquier otra aplicación. |
| B5 | Media | `settings_store.py:167` | El Health Monitor arranca por efecto colateral de importar el módulo (`threading.Timer` a nivel top-level). Imposible importar `settings_store` sin abrir DXGI y un hilo OCR. |
| B6 | Media | `app.py:217, 474, 531` | Operaciones bloqueantes largas dentro del hilo de request: `wait_for_tibia_f10` (30 s), `time.sleep(delay_seconds)` (10 s), `execute_routine` (**minutos**, sin forma de cancelar por API). Ocupan un worker de Flask y la petición del navegador queda colgada. |
| B7 | Media | `capture_utils.py:213-222` | Si el arranque de DXGI falla una vez, `_LIVE_CAPTURE_ERROR` queda cacheado permanentemente. No hay reintento ni reset — se requiere reiniciar el proceso. |
| B8 | Media | `screen_event_monitor.py:114` | `ImageGrab.grab(all_screens=True)` usa coordenadas del escritorio virtual mientras el resto del sistema usa coordenadas locales DXGI. Las regiones de eventos apuntan a píxeles distintos que las de Battle. |
| B9 | Baja | `tibia-mapper.spec:13` | El EXE empaqueta `launcher.py`, que importa `app.py` — **sin** las rutas de IA ni de mapas. El binario distribuido no tiene `/api/ai/*` ni `/api/map/*`. |
| B10 | Baja | `requirements.txt` | `numpy` se importa explícitamente (`bestiary_reader.py:134, 234, 296`) pero no está declarado. Llega solo como dependencia transitiva de `rapidocr-onnxruntime`. |
| B11 | Baja | `templates/index.html` | La UI no expone `loot_tracker_region`, `loot_similarity_threshold`, `loot_change_confirmations`, ninguna configuración de Health ni `dxgi_output_idx`. Solo se pueden ajustar editando `settings.json` a mano o con `PUT /api/settings`. Son precisamente los parámetros que más se calibran. |

### 5.2 Riesgo de seguridad

`app.py:249` combinado con la ausencia de autenticación crea un vector real: **cualquier página web abierta en el navegador del usuario puede enviar `POST http://127.0.0.1:5000/api/battle/scan-passive`**. Es una petición simple sin preflight CORS, así que el navegador la envía; la respuesta queda bloqueada, pero el efecto secundario —un click y una pulsación de tecla en la máquina— ya ocurrió.

Mitigación mínima: exigir una cabecera personalizada (`X-Requested-With`) que fuerce el preflight, o un token de sesión generado al arrancar e inyectado en las plantillas.

### 5.3 Deuda técnica

- **Sin tests.** Cero archivos de test. `_similarity`, `_best_match`, `analyze_routine_path`, `_pathfinding_info` y los normalizadores de los stores son funciones puras trivialmente testeables.
- **Sin rotación de logs.** `logs/` ya tiene 23 archivos y 1,2 MB. `action_events.jsonl` y `bestiary_snapshots.jsonl` crecen indefinidamente.
- **Campos legacy de Bestiary** en `battle_runtime_status()` (`battle_monitor.py:474-480`): seis claves siempre `None` para no romper la UI. `bestiary_tracker_region` sigue en la configuración y en el formulario de `index.html`, ya sin uso.
- **`decision_engine.decide()` no está conectado a nada.** Existen `GET`/`POST /api/battle/decision` pero ningún JS los llama.
- **HTML/JS minificado a mano** en `templates/index.html` (líneas de 2.000+ caracteres). Muy difícil de mantener o revisar en diff.
- **`debug_dxgi_capture.py`** en la raíz del repositorio, sin marcar como script de diagnóstico.

---

## 6. Mejoras propuestas

### P0 — Corrección e integridad (hacer primero)

**1. Resolver la contradicción observación / acción.** Es la decisión de diseño más importante pendiente. Dos caminos posibles:

- *Camino A (observación pura):* eliminar `execute_battle_action()` de `/api/battle/scan-passive`. El sistema queda 100 % consistente con su documentación y su log de auditoría.
- *Camino B (acción explícita):* mantener la acción pero (a) que use `pending["screen_x"]` / `pending["screen_y"]` en lugar de coordenadas fijas, (b) exigir `tibia_is_foreground()` antes de cada input, (c) ponerla detrás de un flag `battle_auto_action_enabled` apagado por defecto, (d) corregir el log de auditoría para que refleje `input_executed: True`.

Sea cual sea el camino, arreglar B1 (el set) y B2 (las coordenadas fijas).

**2. Guardia de foreground antes de todo input.**

```python
if not tibia_is_foreground(settings.get("tibia_window_title", "Tibia")):
    log_event("BATTLE ACTION OMITIDA | Tibia no está en primer plano")
    return {"ok": False, "reason": "not_foreground"}
```

**3. Conectar los checkpoints al ejecutor de rutinas.** La infraestructura ya existe entera; falta el pegamento en `routine_executor.py`:

```python
if record.get("validation_image"):
    check = compare_checkpoint(
        routine_id, record["index"],
        settings["map_validation_region"],
        settings["validation_similarity_threshold"],
    )
    if not check["match"]:
        # reintentar hasta validation_timeout_seconds cada validation_poll_seconds
        ...
```

Esto convierte las rutinas de "reproducción ciega de coordenadas" a "navegación verificada", que es el objetivo aparente del diseño original.

**4. Escrituras atómicas en los stores JSON.** Escribir a `<archivo>.tmp` y luego `os.replace()`. Añadir un `threading.Lock` por store. Elimina la corrupción silenciosa y la pérdida de escrituras concurrentes.

### P1 — Rendimiento y arquitectura

**5. Sustituir el matching por fuerza bruta por `cv2.matchTemplate`.**

```python
import cv2, numpy as np
result = cv2.matchTemplate(region_np, template_np, cv2.TM_CCOEFF_NORMED)
_, max_val, _, max_loc = cv2.minMaxLoc(result)
```

Gana en tres dimensiones a la vez: **~100× más rápido** (FFT/SIMD sobre el bucle Python), **invariante a brillo** (`TM_CCOEFF_NORMED` normaliza), y elimina el acantilado de rendimiento con plantillas pequeñas. Habilita plantillas por icono de criatura en lugar de filas completas de 420 px, que es lo que el sistema realmente quiere hacer. Coste: `opencv-python-headless` (~35 MB en el paquete). Con diferencia, el mejor retorno del listado.

**6. Mover el bucle de tiempo real al backend.** Hoy el monitor es `setTimeout` en `execution_ui.js:137` y `battle_ui.js:180`; cerrar la pestaña lo mata y dos pestañas abiertas lo duplican. Un `BattleMonitorThread` en el servidor (igual que `health_monitor.py`, que ya lo hace bien) con `POST /api/battle/monitor/start|stop` y `GET /api/battle/monitor/state` para que el frontend solo lea. Sobrevive al cierre del navegador y elimina el latido HTTP por ciclo.

**7. Sacar las operaciones largas del hilo de request.** `execute_routine` en un hilo de trabajo con `POST /api/routines/start` → `{job_id}` y `GET /api/jobs/<id>`, más `POST /api/jobs/<id>/cancel`. Resuelve B6 y da por fin una forma de cancelar una rutina desde la UI.

**8. Arranque explícito del Health Monitor.** Quitar el `threading.Timer` de `settings_store.py` y llamar `start_health_monitor()` desde `app.py`/`launcher.py`. Hace el módulo importable y testeable.

**9. Reintento de DXGI con backoff.** Reemplazar el error cacheado permanente por un reintento con espera creciente y un `POST /api/capture/reset` manual.

### P2 — Funcionalidad y calidad

**10. Implementar el detector de eventos o retirarlo.** Es ~350 líneas de infraestructura de concurrencia correcta alimentando un detector que devuelve `False` constante. Opciones: implementarlo reutilizando `_best_match` (detección por plantilla) o `read_bestiary` (detección por texto); o marcar el subsistema como experimental y ocultar la pestaña. Mantenerlo visible y no funcional confunde al usuario y a cualquier agente que lea el código.

**11. Exponer los parámetros de calibración en la UI (B11).** Loot, Health y `dxgi_output_idx` son los que más se ajustan y hoy exigen editar JSON a mano. Sería útil añadir un panel de vista previa que muestre el recorte actual de cada región junto a su valor de similitud en vivo — convierte la calibración de prueba y error a ajuste visual directo.

**12. Rotación de logs.** `RotatingFileHandler` para los `.log`; para los `.jsonl`, rotar por tamaño o purgar registros con más de N días.

**13. Batería de tests mínima.** Empezar por las funciones puras: `_similarity` (imágenes idénticas → 1,0; invertidas → ~0,0), `_best_match` (plantilla insertada en posición conocida), `analyze_routine_path`, `_pathfinding_info`, `_normalize_settings`. Unas 15 pruebas cubren la lógica que más duele si se rompe en silencio.

**14. Token CSRF o cabecera obligatoria** en los endpoints con efectos secundarios (§5.2).

**15. Empaquetar `app_ai.py` en el EXE** (B9), o fusionar las rutas de IA/mapa en `app.py` detrás de un flag y eliminar el punto de entrada dual.

**16. Retirar los restos de Bestiary.** Eliminar los seis campos legacy de `battle_runtime_status()`, `bestiary_tracker_region` de la configuración y su fieldset de `index.html`. `bestiary_reader.py` se mantiene: `read_health_number` sigue en uso activo.

### Priorización

| Mejora | Impacto | Esfuerzo | Prioridad |
|---|---|---|---|
| 5. OpenCV matchTemplate | Muy alto | Bajo | **1** |
| 1–2. Coherencia de acción + guardia foreground | Muy alto | Bajo | **2** |
| 3. Conectar checkpoints | Alto | Medio | **3** |
| 6. Monitor Battle en backend | Alto | Medio | **4** |
| 4. Escrituras atómicas | Medio | Bajo | **5** |
| 7. Jobs asíncronos | Medio | Medio | 6 |
| 11. Calibración en UI | Medio | Medio | 7 |
| 13. Tests | Medio | Bajo | 8 |
| 10. Eventos: implementar o retirar | Medio | Alto | 9 |
| 8, 9, 12, 14, 15, 16 | Bajo–medio | Bajo | 10 |

---

## 7. Conclusión

El proyecto tiene una **arquitectura de percepción sólida**: la separación entre lectura DXGI e interacción Windows es correcta, la máquina de estados de dos fases es elegante y eficiente, y la instrumentación permite diagnosticar sin adivinar. La migración de Bestiary a Loot demuestra buen criterio de ingeniería —cambiar la señal en vez de optimizar la lenta— y se refleja en dos órdenes de magnitud de mejora medida.

Los tres problemas que más limitan el avance no son de percepción sino de **coherencia y arquitectura de ejecución**: la contradicción entre lo que el código dice hacer y lo que hace (`scan-passive` con clicks de coordenadas fijas), el bucle de tiempo real alojado en el navegador, y la infraestructura construida pero desconectada (checkpoints, eventos, motor de decisión).

Si hubiera que elegir tres cambios: **sustituir el matching por OpenCV** (desbloquea plantillas pequeñas y quita el acantilado de rendimiento), **resolver la ambigüedad observación/acción** (hoy el log de auditoría es literalmente falso), y **conectar los checkpoints al ejecutor** (convierte las rutinas en navegación verificada, que es lo que el diseño ya anticipaba).
