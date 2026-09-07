# Guía de implementación — Tibia Mapper

**Destinatario:** modelo/agente que continúa el trabajo en una sesión nueva, sin contexto previo.
**Repositorio:** `escuelaalz1-debug/tibia-mapper`
**Rama de trabajo:** `feature/ai-advisor` — **no tocar `main`**
**Ruta local:** `C:\Claude Code\Tibia Mapper\tibia-mapper-feature-ai-advisor`
**Plataforma:** Windows 11, PowerShell, Python 3.12
**Documento origen:** `ANALISIS_PROYECTO.md` (análisis completo; leerlo si necesitas el porqué de cada tarea)

---

## 0. Antes de escribir una sola línea

Ejecuta esto y confirma el estado:

```powershell
cd "C:\Claude Code\Tibia Mapper\tibia-mapper-feature-ai-advisor"
git status
git branch --show-current
python -m pip install -r requirements.txt
```

**Reglas de esta base de código:**

1. **Los archivos reales mandan.** Este documento y `CODEX_CONTEXT.md` pueden estar desactualizados respecto al código. Antes de cada tarea, lee el archivo que vas a modificar. Si lo que encuentras no coincide con lo que aquí se describe, **detente y reporta la discrepancia** en vez de improvisar.
2. **No inventes nombres.** Funciones, rutas, claves de `settings.json` y patrones de log existen tal cual; verifícalos con `grep` antes de usarlos.
3. **No afirmes que algo pasa sin haberlo ejecutado.** Si no pudiste correr una verificación (por ejemplo, porque requiere el cliente de Tibia abierto), dilo explícitamente.
4. **Commits pequeños y revisables**, uno por tarea. Formato de mensaje sugerido: `fix(battle): usa coordenadas del match detectado`.
5. **El invariante de coordenadas del proyecto** — respétalo en todo cambio:
   ```
   LECTURA / ANÁLISIS  →  DXGI, coordenadas locales del monitor `dxgi_output_idx`
   INTERACCIÓN         →  coordenadas reales del escritorio de Windows
   ```
   Nunca pases una coordenada de una región DXGI directamente a `pyautogui`.

**Contexto mínimo de la aplicación:** herramienta local Flask que captura un monitor por DXGI a 30 FPS, recorta regiones definidas en `settings.json`, las compara contra plantillas PNG y reacciona. Subsistemas: Battle (detección de objetivos + seguimiento de Loot), Rutinas (grabación y reproducción de coordenadas), Health Monitor (OCR de vida), Eventos (stub), IA Advisor (Ollama local) y mapas offline de TibiaMaps.

---

## 1. Orden de ejecución

Las tareas están ordenadas por retorno. **T1 a T5 son las importantes.** Cada una es independiente salvo donde se indique lo contrario.

| ID | Tarea | Impacto | Esfuerzo | Dependencias |
|---|---|---|---|---|
| T1 | Matching con OpenCV | Muy alto | Bajo | — |
| T2 | Coherencia observación/acción + guardia de foreground | Muy alto | Bajo | Requiere decisión del usuario |
| T3 | Conectar checkpoints al ejecutor de rutinas | Alto | Medio | — |
| T4 | Monitor Battle en el backend | Alto | Medio | Mejor después de T1 y T2 |
| T5 | Escrituras atómicas en los stores JSON | Medio | Bajo | — |
| T6 | Jobs asíncronos para rutinas | Medio | Medio | T4 (reutiliza el patrón) |
| T7 | Arranque explícito del Health Monitor | Medio | Bajo | — |
| T8 | Reintento de DXGI con backoff | Medio | Bajo | — |
| T9 | Exponer parámetros de calibración en la UI | Medio | Medio | — |
| T10 | Batería de tests | Medio | Bajo | Ideal después de T1 |
| T11 | Rotación de logs | Bajo | Bajo | — |
| T12 | Endurecer la API local (CSRF) | Bajo | Bajo | T2 |
| T13 | Empaquetar las rutas de IA/mapa en el EXE | Bajo | Bajo | — |
| T14 | Retirar restos de Bestiary | Bajo | Bajo | — |
| T15 | Eventos: implementar o retirar | Medio | Alto | Requiere decisión del usuario |

---

## T1 — Sustituir el matching por fuerza bruta por OpenCV

### Problema

`battle_monitor.py:54-77` busca la plantilla recorriendo la región píxel a píxel en Python puro:

```python
def _best_match(region_image, template, scan_step=2):
    ...
    for y in range(0, rh - th + 1, max(1, int(scan_step))):
        for x in range(0, rw - tw + 1, max(1, int(scan_step))):
            crop = region.crop((x, y, x + tw, y + th))
            score = _similarity(crop, target)
```

Coste: O(W·H·w·h). Hoy tarda ~68 ms **solo por casualidad geométrica**: la plantilla actual (`swamp-troll.png`, 420×55) tiene exactamente el mismo ancho que la región (420×480), así que hay **una sola posición horizontal** posible y el bucle evalúa 213 posiciones. Con una plantilla de 120×20 (un icono de criatura, que es lo que el sistema realmente querría usar) serían ~34.900 posiciones → ~1,2 s por objetivo → ~6 s con 5 objetivos, con `battle_poll_seconds = 1.0`.

Además, la métrica `_similarity()` (error absoluto medio normalizado) es poco discriminante: dos recortes oscuros distintos dan ~0,98, y por eso los umbrales tienen que vivir en 0,975.

### Solución

`cv2.matchTemplate` con `TM_CCOEFF_NORMED`: ~100× más rápido, invariante a cambios de brillo, y elimina el acantilado con plantillas pequeñas.

### Pasos

**1.1** Añadir la dependencia a `requirements.txt`:

```
opencv-python-headless>=4.9,<5.0
numpy>=1.26,<3.0
```

`numpy` ya se usa (`bestiary_reader.py:134, 234, 296`) pero solo llegaba como dependencia transitiva de `rapidocr-onnxruntime`. Declararlo explícitamente. Usa `-headless`: la app no abre ventanas de OpenCV y la variante completa arrastra Qt (~100 MB extra en el EXE).

**1.2** En `battle_monitor.py`, añadir el backend OpenCV **conservando el actual como fallback**. La app se distribuye como EXE portable; si OpenCV faltara en tiempo de ejecución, el detector debe degradarse, no morir:

```python
# Cerca de los imports de battle_monitor.py
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except Exception:  # pragma: no cover
    _CV2_AVAILABLE = False


def _best_match_cv2(region_image: Image.Image, template: Image.Image) -> dict[str, Any] | None:
    """Localiza la plantilla con correlación cruzada normalizada.

    TM_CCOEFF_NORMED resta la media de cada ventana antes de correlacionar, así
    que el score no se desplaza cuando cambia el brillo global de la escena.
    Devuelve la misma forma que _best_match() para no tocar a los llamadores.
    """
    region = np.asarray(region_image.convert("RGB"))
    target = np.asarray(template.convert("RGB"))
    th, tw = target.shape[:2]
    rh, rw = region.shape[:2]
    if tw > rw or th > rh:
        return None

    result = cv2.matchTemplate(region, target, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    return {
        "x": int(max_loc[0]),
        "y": int(max_loc[1]),
        "width": int(tw),
        "height": int(th),
        "similarity": round(float(max_val), 4),
    }
```

**1.3** Renombrar el `_best_match` actual a `_best_match_bruteforce` y crear un despachador que conserve la firma pública:

```python
def _best_match(region_image, template, scan_step: int = 2) -> dict[str, Any] | None:
    if _CV2_AVAILABLE:
        return _best_match_cv2(region_image, template)
    return _best_match_bruteforce(region_image, template, scan_step=scan_step)
```

Con esto no hay que tocar `_scan_idle()` ni ningún otro llamador.

**1.4** Añadir el backend usado al log de diagnóstico. En `_scan_idle()`, dentro del bloque `BATTLE MATCH DEBUG` (aprox. línea 168), agrega el campo:

```python
f"backend={'cv2' if _CV2_AVAILABLE else 'bruteforce'} | "
```

Sin esto, si el fallback se activa en el PC destino no habrá forma de saberlo salvo por el tiempo.

**1.5** Actualizar `tibia-mapper.spec` para que PyInstaller empaquete OpenCV. Añadir a `hiddenimports`:

```python
'cv2',
```

Y junto a los `collect_all` existentes:

```python
cv2_datas, cv2_binaries, cv2_hidden = collect_all('cv2')
```
sumando `cv2_datas` / `cv2_binaries` / `cv2_hidden` a las listas correspondientes de `Analysis`, igual que se hace ya con `rapidocr`, `onnxruntime` y `dxcam`.

### Recalibración obligatoria tras el cambio

**Los umbrales actuales dejan de ser válidos.** `battle_similarity_threshold = 0.90` está calibrado para la métrica antigua (error absoluto medio), que produce valores comprimidos hacia 1,0. `TM_CCOEFF_NORMED` devuelve una correlación en `[-1, 1]` con una distribución completamente distinta: un match real suele dar > 0,95 y el ruido cae muy por debajo de 0,5.

Procedimiento: con Tibia abierto y una criatura visible en Battle, correr la prueba manual (`POST /api/battle/scan`, o el botón "Analizar ahora" en `/battle`) y leer los valores de `best_similarity` en las líneas `BATTLE MATCH DEBUG` del log. Fijar el umbral por debajo del match real y por encima del mejor falso positivo. **Documenta en el commit los valores observados y el umbral elegido.**

`loot_similarity_threshold` (0,975) **no se toca**: lo usa `_scan_tracking()`, que compara dos recortes del mismo tamaño con `_similarity()` directamente, sin pasar por `_best_match`.

### Verificación

- [ ] `python -c "import cv2; print(cv2.__version__)"` responde.
- [ ] Con la plantilla actual (420×55), `battle_match_ms` en las líneas `BATTLE PERF` baja de ~68 ms a un valor de un dígito.
- [ ] `BATTLE MATCH DEBUG` muestra `backend=cv2`.
- [ ] Una detección real sigue produciendo `accepted=True` con el umbral recalibrado.
- [ ] Prueba de plantilla pequeña: recorta una referencia de ~120×20 con `POST /api/battle/targets/<id>/crop` y confirma que el escaneo sigue costando milisegundos.

---

## T2 — Resolver la contradicción observación / acción

### Problema

Es la incoherencia más grave del repositorio. Todo el código y la documentación declaran que el sistema **solo observa**:

- `decision_engine.Decision` lleva `advisory_only: True`.
- `battle_monitor.py` escribe en el log de auditoría `action={"type": "battle_observation", "input_executed": False}` (líneas ~329 y ~360).
- `app.py:259` registra literalmente `"BATTLE listo para nuevo análisis (sin input automático)"`.
- `CODEX_CONTEXT.md` insiste en que el Advisor no ejecuta acciones de mouse ni teclado.

Pero `app.py:249` sí ejecuta input real:

```python
pending = state.get("pending_target")
if state.get("action_triggered") and pending:
    result = execute_battle_action(pending, settings)
```

Que termina en `mouse_helpers.py:19-31`:

```python
def click_atack_on_battle(
    x=3196, y=681,          # ← COORDENADAS FIJAS
    button="left", clicks=1, interval=0.0):
    pyautogui.moveTo(x, y, duration=0.25)
    pyautogui.click(button=button, clicks=clicks, interval=interval)
    pyautogui.press("a")
```

Tres defectos encadenados:

1. **El registro de auditoría es falso.** Dice `input_executed: False` mientras se hace click y se pulsa una tecla.
2. **Las coordenadas están hardcodeadas.** El match detectado trae `screen_x` / `screen_y` (calculados en `battle_monitor.py:184-185`) y se descartan por completo. Todo el pipeline de visión termina clicando siempre en el mismo píxel.
3. **No hay guardia de foreground.** `get_live_frame()` (`capture_utils.py:246`) acepta un parámetro `tibia_title` y **nunca lo usa**: captura el monitor entero sin importar qué ventana esté activa. Combinado con lo anterior, la app puede clicar sobre cualquier otra aplicación que el usuario tenga delante.

Además, `battle_action_executor.py:19` tiene un bug de sintaxis semántica:

```python
result = {
    "ok": {resultAction.get('ok')},   # ← esto es un SET {'ok'}, no un booleano
    "target_id": target_id,
}
```

`click_atack_on_battle()` devuelve `{"ok": "ok"}`, así que `resultAction.get('ok')` es la cadena `"ok"` y las llaves la envuelven en un `set`. El log imprime `action_ok={'ok'}` y el valor no sería serializable a JSON si algún día se devolviera por la API.

### Decisión requerida del usuario

**Esta tarea no se puede completar sin confirmación.** Pregunta al usuario cuál de los dos caminos quiere antes de implementar:

> **Camino A — Observación pura.** Quitar `execute_battle_action()` de `/api/battle/scan-passive`. El sistema queda 100 % consistente con su documentación y su log de auditoría. La detección sigue funcionando y reportando, pero no genera input.
>
> **Camino B — Acción explícita y correcta.** Mantener la acción, pero arreglada: usa las coordenadas del match, exige que Tibia esté en primer plano, y queda detrás de un flag apagado por defecto.

Indicio a favor del Camino B: el usuario escribió `click_atack_on_battle()` y la cableó deliberadamente, así que la intención de automatizar parece real. Pero las coordenadas fijas sugieren que quedó a medias. **Pregunta, no asumas.**

### Implementación del Camino A

En `app.py`, función `battle_scan_passive()` (línea 239):

```python
pending = state.get("pending_target")
if state.get("action_triggered") and pending:
    log_event(
        f"BATTLE gatillo pasivo | "
        f"id={pending.get('target_id')} | "
        f"serial={state.get('trigger_serial')} | "
        f"similitud={pending.get('similarity')} | "
        f"screen=({pending.get('screen_x')},{pending.get('screen_y')}) | "
        "input_executed=False"
    )
```

Eliminar el import de `execute_battle_action` (línea 4). Borrar `battle_action_executor.py` y `click_atack_on_battle()` de `mouse_helpers.py`, o marcarlos claramente como código muerto reservado para un futuro modo de acción.

### Implementación del Camino B

**2.1** Reescribir `click_atack_on_battle()` en `mouse_helpers.py` para que reciba las coordenadas:

```python
def click_attack_on_battle(x: int, y: int, *, press_key: str | None = "a",
                           button: str = "left", clicks: int = 1) -> dict[str, Any]:
    """Click en la fila Battle detectada, en coordenadas reales de Windows.

    x/y deben venir de screen_x/screen_y del match, no de una región DXGI.
    """
    pyautogui.moveTo(int(x), int(y), duration=0.25)
    pyautogui.click(button=button, clicks=clicks)
    if press_key:
        pyautogui.press(press_key)
    return {"ok": True, "x": int(x), "y": int(y), "key": press_key}
```

Corrige de paso el typo `atack` → `attack`. Si prefieres no romper llamadores, deja un alias, pero verifica con `grep -rn "click_atack_on_battle"` que solo lo usa `battle_action_executor.py`.

**2.2** Reescribir `battle_action_executor.py` completo:

```python
from __future__ import annotations

from typing import Any

from capture_utils import tibia_is_foreground
from mouse_helpers import click_attack_on_battle
from session_log import log_event


def execute_battle_action(target: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    target_id = str(target.get("target_id") or "")
    name = str(target.get("name") or target_id)
    similarity = float(target.get("similarity") or 0.0)

    if not bool(settings.get("battle_auto_action_enabled", False)):
        return {"ok": False, "executed": False, "reason": "auto_action_disabled",
                "target_id": target_id}

    title = str(settings.get("tibia_window_title") or "Tibia")
    if not tibia_is_foreground(title):
        log_event(f"BATTLE ACTION OMITIDA | id={target_id} | Tibia no está en primer plano")
        return {"ok": False, "executed": False, "reason": "not_foreground",
                "target_id": target_id}

    x = target.get("screen_x")
    y = target.get("screen_y")
    if x is None or y is None:
        log_event(f"BATTLE ACTION OMITIDA | id={target_id} | el match no trae screen_x/screen_y")
        return {"ok": False, "executed": False, "reason": "missing_coordinates",
                "target_id": target_id}

    log_event(
        f"BATTLE ACTION | id={target_id} | name={name} | "
        f"similarity={similarity:.4f} | click=({x},{y})"
    )
    result = click_attack_on_battle(int(x), int(y))
    return {"ok": bool(result.get("ok")), "executed": True,
            "target_id": target_id, "x": int(x), "y": int(y)}
```

**2.3** Añadir el flag a `settings_store.py`. En `DEFAULT_SETTINGS`:

```python
"battle_auto_action_enabled": False,
```

En `_normalize_settings()`:

```python
"battle_auto_action_enabled": bool(data.get(
    "battle_auto_action_enabled", DEFAULT_SETTINGS["battle_auto_action_enabled"])),
```

Y añadir la clave a la tupla de claves permitidas en `update_settings()` (el bucle `for key in (...)`).

**Decisión de diseño a considerar:** `battle_detection_enabled` es deliberadamente transitorio — vive en la variable de módulo `_battle_detection_enabled` y **no se persiste**, para que una sesión anterior no reactive la detección al abrir la app. El mismo argumento aplica con más fuerza a un flag que genera clicks. Recomendación: hacerlo transitorio igual, siguiendo el patrón existente. Confirma con el usuario.

**2.4** Corregir el registro de auditoría en `battle_monitor.py`. En las dos llamadas a `log_action_event` (líneas ~329 y ~360), el campo `input_executed` está hardcodeado a `False`. Como el input se ejecuta **fuera** de `battle_monitor` (en la capa de `app.py`), lo más limpio es que `battle_monitor` deje de afirmar nada sobre input y que sea `app.py` quien registre el evento real. Mínimo aceptable: propagar el flag desde settings para que el campo no mienta.

**2.5** Verificar que `capture_utils.tibia_is_foreground()` existe con esa firma antes de importarla:

```powershell
Select-String -Path capture_utils.py -Pattern "def tibia_is_foreground"
```

Existe en `capture_utils.py:63` con firma `tibia_is_foreground(title_text: str = DEFAULT_TIBIA_TITLE) -> bool`.

### Verificación (Camino B)

- [ ] Con `battle_auto_action_enabled = False` (por defecto), un escaneo que detecta un objetivo **no** mueve el mouse y el log muestra `reason=auto_action_disabled`.
- [ ] Con el flag activado y Tibia **minimizado**, el log muestra `BATTLE ACTION OMITIDA | ... no está en primer plano` y el mouse no se mueve.
- [ ] Con el flag activado y Tibia al frente, el click ocurre en `(screen_x, screen_y)` del match — verificable comparando las coordenadas del log con la fila real de Battle.
- [ ] `action_ok=True` en el log, no `action_ok={'ok'}`.

---

## T3 — Conectar los checkpoints al ejecutor de rutinas

### Problema

Toda la infraestructura de validación visual existe y funciona, pero **nada la usa durante la ejecución**:

- `checkpoint_store.compare_checkpoint()` está implementada y probada.
- La ruta `POST /api/routines/<id>/steps/<i>/checkpoint/compare` funciona (`app.py:504`).
- `settings.json` define `validation_similarity_threshold`, `validation_timeout_seconds` y `validation_poll_seconds`.
- `recorder.py` captura los checkpoints con F11 y los guarda en `checkpoints/<rutina>/step_NNNN.png`.
- `routine_executor.py:78` copia `validation_image` al record de ejecución.
- `routine_executor.py:197` lo escribe en el log.

Y luego `execute_step()` (`mouse_helpers.py:41`) solo hace `moveTo` + `click`. **El checkpoint nunca se compara.** Las rutinas son reproducción ciega de coordenadas.

Ese es exactamente el problema que los checkpoints existen para resolver: si el personaje no llegó donde se esperaba, seguir clicando coordenadas fijas empeora la situación.

### Solución

Tras ejecutar un paso que tiene `validation_image`, comparar la región `map_validation_region` contra el checkpoint guardado, reintentando hasta `validation_timeout_seconds`.

### Pasos

**3.1** En `routine_executor.py`, añadir el import:

```python
from checkpoint_store import compare_checkpoint
```

**3.2** Añadir la función de validación (antes de `execute_routine`):

```python
def validate_step_checkpoint(
    routine_id: str,
    record: dict[str, Any],
    settings: dict[str, Any],
    control: dict[str, bool],
) -> dict[str, Any]:
    """Compara la región de validación contra el checkpoint del paso.

    Reintenta hasta validation_timeout_seconds porque el minimapa tarda en
    redibujarse tras un movimiento. Respeta pausa/stop por hotkey.
    """
    if not record.get("validation_image"):
        return {"validated": False, "skipped": True, "reason": "sin_checkpoint"}

    region = settings["map_validation_region"]
    threshold = float(settings["validation_similarity_threshold"])
    timeout = float(settings["validation_timeout_seconds"])
    poll = float(settings["validation_poll_seconds"])
    title = str(settings.get("tibia_window_title") or "Tibia")

    deadline = time.monotonic() + timeout
    last = {"similarity": 0.0}
    attempts = 0

    while time.monotonic() < deadline:
        control["paused"], control["f12_latched"], stop_requested = wait_runtime_control(
            control["paused"], control["f12_latched"]
        )
        if stop_requested:
            return {"validated": False, "stopped": True, "attempts": attempts}

        attempts += 1
        try:
            last = compare_checkpoint(
                routine_id, record["index"], region, threshold, tibia_title=title,
            )
        except Exception as exc:
            log_event(
                f"CHECKPOINT ERROR | rutina={routine_id} | paso={record['index'] + 1} | "
                f"{type(exc).__name__}: {exc}"
            )
            return {"validated": False, "error": str(exc), "attempts": attempts}

        if last.get("match"):
            log_event(
                f"CHECKPOINT OK | rutina={routine_id} | paso={record['index'] + 1} | "
                f"similitud={last.get('similarity')} | umbral={threshold} | intentos={attempts}"
            )
            return {"validated": True, **last, "attempts": attempts}

        time.sleep(poll)

    log_event(
        f"CHECKPOINT FALLÓ | rutina={routine_id} | paso={record['index'] + 1} | "
        f"similitud={last.get('similarity')} | umbral={threshold} | "
        f"timeout={timeout}s | intentos={attempts}"
    )
    return {"validated": False, "timeout": True, **last, "attempts": attempts}
```

**3.3** Llamarla en el bucle de ejecución. En `routine_executor.py`, justo después de `result = execute_step(record, record["index"])` (aprox. línea 199) y **antes** de `record["status"] = ...`:

```python
                result = execute_step(record, record["index"])

                if result.get("ok") and record.get("validation_image"):
                    validation = validate_step_checkpoint(
                        routine["id"], record, execution_settings, control
                    )
                    result["validation"] = validation
                    if validation.get("stopped"):
                        stopped_by_hotkey = True
                        result["ok"] = False
                    elif not validation.get("validated"):
                        result["ok"] = bool(execution_settings.get(
                            "validation_failure_continues", False))
```

**3.4** Añadir el ajuste `validation_failure_continues` a `settings_store.py` (`DEFAULT_SETTINGS`, `_normalize_settings` y la tupla de `update_settings`), con valor por defecto `False`.

Justificación del ajuste: en modo estricto (`False`) un checkpoint fallido detiene la rutina — el comportamiento correcto cuando la posición del personaje ya no es la esperada, porque seguir es peor que parar. Pero durante el ajuste de una rutina nueva es útil dejarla correr entera y revisar después qué pasos fallaron. Confirma con el usuario cuál debe ser el defecto.

### Riesgo a vigilar

`map_validation_region` en `settings.json` es `{x: 1701, y: 67, width: 169, height: 25}` — **169×25 píxeles**, un recorte muy pequeño y alargado. Los checkpoints en `checkpoints/test/` son de una época anterior y pueden tener otras dimensiones. `compare_checkpoint` redimensiona el frame actual al tamaño de la referencia (`checkpoint_store.py:76-77`), así que **no fallará ruidosamente: devolverá similitudes basura sin avisar**.

Antes de dar T3 por terminada, verifica que las dimensiones coinciden:

```powershell
python -c "from PIL import Image; import glob; [print(p, Image.open(p).size) for p in glob.glob('checkpoints/*/*.png')]"
```

Si no coinciden con `map_validation_region`, los checkpoints hay que regrabarlos con F11 y hay que reportarlo al usuario.

### Verificación

- [ ] Una rutina **sin** checkpoints se ejecuta exactamente igual que antes (sin regresión).
- [ ] Una rutina con checkpoints registra `CHECKPOINT OK` con la similitud real.
- [ ] Con un checkpoint deliberadamente incorrecto, la rutina se detiene y registra `CHECKPOINT FALLÓ`.
- [ ] `Ctrl+F12` durante la espera de validación detiene la rutina limpiamente.

---

## T4 — Mover el monitor Battle al backend

### Problema

El bucle de tiempo real vive en el navegador. `static/execution_ui.js:137` y `static/battle_ui.js:180` hacen `setTimeout` → `POST /api/battle/scan-passive` → repetir. Consecuencias:

- Cerrar la pestaña mata el monitor.
- Dos pestañas abiertas duplican el bucle contra el mismo estado global de `battle_monitor`.
- Cada ciclo cuesta un round-trip HTTP innecesario.
- Un navegador que suspende timers en pestañas de fondo degrada silenciosamente la frecuencia de escaneo.

### Solución

Un hilo en el servidor. **`health_monitor.py` ya implementa este patrón correctamente** — cópialo: hilo daemon, `threading.Event` para parar, lock para el estado, relectura de settings en cada ciclo, y descuento del tiempo transcurrido al calcular la espera.

### Pasos

**4.1** Crear `battle_monitor_thread.py` siguiendo la estructura de `health_monitor.py`:

```python
from __future__ import annotations

import threading
import time
from typing import Any

from battle_action_executor import execute_battle_action
from battle_monitor import update_battle_runtime, battle_runtime_status
from session_log import log_event

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last_state: dict[str, Any] = {}
_last_error: str | None = None
_cycle_count = 0


def _worker() -> None:
    global _last_state, _last_error, _cycle_count
    while not _stop_event.is_set():
        started = time.monotonic()
        try:
            from settings_store import get_settings
            settings = get_settings()
            if bool(settings.get("battle_detection_enabled", False)):
                state = update_battle_runtime(settings)
                pending = state.get("pending_target")
                if state.get("action_triggered") and pending:
                    state["action_result"] = execute_battle_action(pending, settings)
                with _lock:
                    _last_state = state
                    _last_error = None
                    _cycle_count += 1
            interval = max(0.1, float(settings.get("battle_poll_seconds", 1.0)))
        except Exception as exc:
            with _lock:
                _last_error = f"{type(exc).__name__}: {exc}"
            log_event(f"BATTLE MONITOR ERROR | {_last_error}")
            interval = 1.0

        elapsed = time.monotonic() - started
        _stop_event.wait(max(0.05, interval - elapsed))


def start_battle_monitor() -> dict[str, Any]:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return battle_monitor_status()
        _stop_event.clear()
        _thread = threading.Thread(target=_worker, name="battle-monitor", daemon=True)
        _thread.start()
    log_event("BATTLE MONITOR iniciado | bucle en backend")
    return battle_monitor_status()


def stop_battle_monitor() -> dict[str, Any]:
    global _thread
    with _lock:
        thread = _thread
        _stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    with _lock:
        _thread = None
    log_event("BATTLE MONITOR detenido")
    return battle_monitor_status()


def battle_monitor_status() -> dict[str, Any]:
    with _lock:
        active = _thread is not None and _thread.is_alive()
        return {
            "active": active,
            "last_state": dict(_last_state),
            "last_error": _last_error,
            "cycle_count": _cycle_count,
            "runtime": battle_runtime_status(),
        }
```

Nota importante: `update_battle_runtime()` ya usa un lock no bloqueante interno (`battle_monitor.py:_update_lock`) que devuelve `busy: True` si hay otro escaneo en curso. Eso protege contra la coexistencia del hilo nuevo con llamadas manuales a `/api/battle/scan`.

**4.2** Añadir las rutas en `app.py`:

```python
@app.post("/api/battle/monitor/start")
def battle_monitor_start():
    return jsonify({"ok": True, "monitor": start_battle_monitor()})


@app.post("/api/battle/monitor/stop")
def battle_monitor_stop():
    return jsonify({"ok": True, "monitor": stop_battle_monitor()})


@app.get("/api/battle/monitor/state")
def battle_monitor_state():
    return jsonify({"ok": True, "monitor": battle_monitor_status()})
```

**4.3** Adaptar el frontend. En `static/execution_ui.js` y `static/battle_ui.js`, los botones de iniciar/detener llaman a las rutas nuevas, y el `setTimeout` pasa de ejecutar el escaneo a solo **leer** `GET /api/battle/monitor/state` para refrescar la UI. El polling de lectura puede ser más lento (1–2 s) sin afectar la frecuencia real de detección, que ahora la marca el backend.

**4.4** Mantener `POST /api/battle/scan-passive` durante una transición, marcada como obsoleta, para no romper una pestaña abierta con la versión anterior del JS. Retirarla en un commit posterior.

**4.5** Detener el hilo limpiamente cuando `battle_detection_enabled` pasa a `False`. El worker ya salta el ciclo si el flag está apagado, pero conviene que `update_settings()` con `battle_detection_enabled: False` también llame a `stop_battle_monitor()`.

### Verificación

- [ ] Iniciar el monitor, **cerrar la pestaña del navegador**, esperar 30 s, reabrir: `cycle_count` siguió subiendo.
- [ ] Abrir dos pestañas: solo hay un hilo (`active: true`, un único `battle-monitor` en `threading.enumerate()`).
- [ ] `POST /api/battle/monitor/stop` detiene los ciclos y el log lo registra.
- [ ] La frecuencia real de escaneo respeta `battle_poll_seconds` (verificable por los timestamps de `BATTLE PERF`).

---

## T5 — Escrituras atómicas en los stores JSON

### Problema

`routine_store.py`, `event_store.py` y `battle_store.py` hacen `read → modify → write_text()` sin lock ni atomicidad. Dos peticiones HTTP concurrentes sobre la misma rutina pierden una escritura. Peor: un fallo a mitad de `write_text()` deja el archivo truncado, y `list_routines()` lo salta en silencio:

```python
# routine_store.py, dentro de list_routines()
except Exception:
    continue
```

La rutina simplemente **desaparece de la UI sin ningún aviso**. Es el peor modo de fallo posible: pérdida de datos silenciosa.

### Solución

**5.1** Crear `atomic_json.py`:

```python
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def file_lock(path: Path) -> threading.Lock:
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def write_json_atomic(path: Path, data: Any, *, indent: int = 2) -> None:
    """Escribe JSON de forma atómica: tmp en el mismo directorio + os.replace.

    os.replace() es atómico dentro del mismo volumen, así que un lector nunca
    ve un archivo a medio escribir. El tmp debe estar en el mismo directorio
    para garantizar que no cruza volúmenes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=indent)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
```

**5.2** Reemplazar cada `write_text(json.dumps(...))` por `write_json_atomic(...)`. Localízalos:

```powershell
Select-String -Path *.py -Pattern "write_text\(json\.dumps"
```

Al menos: `battle_store._save_index`, `settings_store.save_settings`, más los guardados de `routine_store` y `event_store`.

**5.3** Hacer ruidoso el fallo silencioso. En `routine_store.list_routines()` y `event_store.list_events()`, cambiar el `except Exception: continue` por:

```python
except Exception as exc:
    log_event(f"STORE ERROR | archivo ilegible: {path.name} | {type(exc).__name__}: {exc}")
    continue
```

Cuidado con el import circular: `session_log` no importa los stores, así que importar `log_event` en ellos es seguro. Verifícalo antes.

### Verificación

- [ ] Guardar una rutina y confirmar que no queda ningún `.tmp` en `routines/`.
- [ ] Escrituras concurrentes (dos `PUT` simultáneos sobre la misma rutina) no corrompen el archivo.
- [ ] Un JSON corrupto a mano genera una línea `STORE ERROR` en el log en vez de desaparecer sin más.

---

## T6 — Jobs asíncronos para la ejecución de rutinas

### Problema

`app.py` bloquea el hilo de request en tres sitios:

- Línea 217: `wait_for_tibia_f10(timeout_seconds=30.0)` — hasta 30 s.
- Línea 474: `time.sleep(delay_seconds)` — hasta 10 s.
- Línea 531: `execute_routine(routine["id"])` — **minutos**, sin forma de cancelar por API.

Cada uno ocupa un worker de Flask y deja el `fetch` del navegador colgado. Una rutina larga es indistinguible de una app congelada, y no hay endpoint para abortarla: solo `Ctrl+F12` en el teclado.

### Solución

Registro de jobs en memoria + hilo de trabajo.

**6.1** Crear `job_store.py` con `create_job()`, `get_job()`, `list_jobs()`, `cancel_job()`, `update_job()`. Estado por job: `id` (uuid4), `type`, `status` (`pending`/`running`/`done`/`error`/`cancelled`), `created_at`, `finished_at`, `progress`, `result`, `error`. Todo bajo un `threading.Lock`.

**6.2** `POST /api/routines/start` devuelve `202` con `{"ok": True, "job_id": ...}` inmediatamente y lanza el hilo.

**6.3** Añadir `GET /api/jobs/<job_id>` y `POST /api/jobs/<job_id>/cancel`.

**6.4** La cancelación necesita cooperación de `execute_routine`: acepta un `threading.Event` opcional y lo consulta en el mismo punto donde ya consulta `wait_runtime_control()`. La estructura de pausa/stop por hotkey ya existe (`control` dict + `stop_requested`); el evento de cancelación se integra ahí sin rediseñar el bucle.

**6.5** El frontend hace polling de `GET /api/jobs/<id>` para mostrar progreso y habilita un botón "Cancelar".

### Verificación

- [ ] `POST /api/routines/start` responde en < 100 ms.
- [ ] `GET /api/jobs/<id>` refleja el avance paso a paso.
- [ ] `POST /api/jobs/<id>/cancel` detiene la rutina en el siguiente paso.
- [ ] `Ctrl+F12` sigue funcionando (no debe romperse el camino existente).

---

## T7 — Arranque explícito del Health Monitor

### Problema

`settings_store.py:167`, a nivel de módulo:

```python
threading.Timer(0.25, _start_health_monitor_after_import).start()
```

Importar `settings_store` desde cualquier script —un test, un CLI, un notebook— arranca un hilo de OCR y abre la cámara DXGI como efecto colateral invisible. Hace el módulo imposible de importar en aislamiento, lo que bloquea T10 (tests).

El comentario del código explica que el retardo de 0,25 s existe para evitar un arranque circular: el hilo del monitor llama a `get_settings()` mientras `settings_store` aún se está importando. El arranque explícito elimina el problema de raíz en vez de esquivarlo con un temporizador.

### Solución

**7.1** Borrar de `settings_store.py` el `threading.Timer` y la función `_start_health_monitor_after_import`.

**7.2** En `app.py`, junto a `init_db()` y `log_event("Tibia Mapper iniciado")` (líneas 46-48):

```python
from health_monitor import start_health_monitor
...
init_db()
log_event("Tibia Mapper iniciado")
if get_settings().get("health_monitor_enabled", True):
    start_health_monitor()
```

**7.3** Verificar que `launcher.py` (que importa `app`) hereda el arranque. Lo hace: importa `app` desde `app.py`, y el código a nivel de módulo se ejecuta en la importación.

**7.4** Considerar exponer `POST /api/health/start` y `POST /api/health/stop`. `stop_health_monitor()` ya existe pero no tiene ruta.

### Verificación

- [ ] `python -c "import settings_store; print(settings_store.get_settings())"` termina sin abrir DXGI ni dejar hilos vivos.
- [ ] `python app.py` sigue registrando `HEALTH MONITOR iniciado`.
- [ ] `threading.enumerate()` durante la app muestra exactamente un `health-monitor`.

---

## T8 — Reintento de DXGI con backoff

### Problema

`capture_utils.py:227-232`: si `dxcam.create()` falla una vez, el mensaje se cachea en `_LIVE_CAPTURE_ERROR` y la comprobación de la línea 228 hace que **toda llamada posterior lance el mismo error para siempre**. No hay reintento. Si DXGI falla transitoriamente al arrancar —cambio de resolución, un juego tomando exclusividad de pantalla, el driver reinicializándose— la única salida es reiniciar el proceso.

### Solución

**8.1** Sustituir el error permanente por error con marca de tiempo y backoff:

```python
_LIVE_CAPTURE_ERROR: str | None = None
_LIVE_CAPTURE_ERROR_AT: float = 0.0
_LIVE_CAPTURE_FAILURES: int = 0
_RETRY_BASE_SECONDS = 2.0
_RETRY_MAX_SECONDS = 60.0
```

En `_start_live_camera`, reemplazar `if _LIVE_CAPTURE_ERROR: raise ...` por una comprobación que solo rechaza mientras la ventana de backoff siga vigente:

```python
if _LIVE_CAPTURE_ERROR:
    wait = min(_RETRY_MAX_SECONDS, _RETRY_BASE_SECONDS * (2 ** min(_LIVE_CAPTURE_FAILURES, 5)))
    if time.monotonic() - _LIVE_CAPTURE_ERROR_AT < wait:
        raise RuntimeError(_LIVE_CAPTURE_ERROR)
    # ventana vencida: se permite reintentar
```

En el `except` del `create()`, incrementar `_LIVE_CAPTURE_FAILURES` y sellar `_LIVE_CAPTURE_ERROR_AT = time.monotonic()`. En el camino de éxito, resetear ambos a 0.

**8.2** Añadir `POST /api/capture/reset` que llame a `stop_live_capture()` (ya existe en `capture_utils.py:283`) y limpie el estado de error, para forzar reconexión sin reiniciar.

### Verificación

- [ ] Con un `dxgi_output_idx` inválido (por ejemplo 99), el primer fallo se registra y los reintentos se espacian progresivamente.
- [ ] Corregir el índice y esperar la ventana de backoff permite volver a capturar sin reiniciar el proceso.

---

## T9 — Exponer los parámetros de calibración en la UI

### Problema

`templates/index.html` no expone ninguno de los parámetros que más se ajustan en el uso real:

| Parámetro | Estado en la UI |
|---|---|
| `loot_tracker_region` | Ausente |
| `loot_similarity_threshold` | Ausente |
| `loot_change_confirmations` | Ausente |
| `health_value_region` | Ausente |
| `health_monitor_enabled`, `health_poll_seconds`, `health_log_threshold` | Ausentes |
| `dxgi_output_idx` | Ausente |

Verificado: `grep -c "loot" templates/index.html` → 0. La única forma de ajustarlos es editar `settings.json` a mano o hacer `PUT /api/settings` con curl.

Al mismo tiempo, la UI **sí** muestra `bestiary_tracker_region`, que ya no usa nadie (ver T14).

### Solución

**9.1** Añadir fieldsets en la sección de configuración de `index.html`, siguiendo el patrón de los existentes (bloque `<fieldset><legend>...</legend><div class="grid cols-4">`).

**9.2** Extender `renderSettings()` y el handler `settingsForm.onsubmit` (líneas 167 y 177) con los campos nuevos. **Aviso:** esas líneas son JS minificado a mano de más de 2.000 caracteres. Es buen momento para extraer esa lógica a `static/settings_ui.js` — pero hazlo en un commit separado del que añade los campos, para que el diff sea revisable.

**9.3 (opcional, alto valor)** Panel de vista previa de regiones. Un endpoint `GET /api/capture/region-preview?region=loot_tracker_region` que devuelva el recorte actual como PNG, más un `<img>` que se refresque cada 2 s. Convierte la calibración de prueba y error a ajuste visual directo. Para Loot, mostrar además la similitud en vivo contra el frame anterior ayuda a elegir `loot_similarity_threshold` observando el valor real en reposo y durante un cambio.

### Verificación

- [ ] Cambiar `loot_similarity_threshold` desde la UI se refleja en `settings.json`.
- [ ] Cambiar `dxgi_output_idx` reinicia la cámara y cambia el monitor capturado.
- [ ] Los valores guardados sobreviven al reinicio de la app (salvo `battle_detection_enabled`, transitorio por diseño).

---

## T10 — Batería de tests mínima

### Problema

Cero tests. La lógica más delicada del proyecto —métricas de similitud, búsqueda de plantilla, normalización de settings, interpretación del pathfinding— son funciones puras que se pueden probar sin Windows, sin DXGI y sin Tibia.

### Solución

**10.1** Añadir `pytest>=8.0,<9.0` a `requirements.txt` (o mejor, crear `requirements-dev.txt`).

**10.2** Crear `tests/` con:

`tests/test_similarity.py`
- `_similarity(img, img)` con la misma imagen → `1.0`.
- Blanco puro vs negro puro → `0.0`.
- Tamaños distintos → `0.0` (contrato actual: `battle_monitor.py:45-46`).
- **Test de caracterización de la debilidad conocida:** dos imágenes oscuras distintas (`RGB(10,10,10)` vs `RGB(20,20,20)`) dan > 0,95. Documenta por qué los umbrales están en 0,975 y detecta si alguien cambia la métrica sin recalibrar.

`tests/test_best_match.py`
- Insertar una plantilla en una posición conocida de una imagen mayor y verificar que `_best_match` devuelve esas coordenadas con similitud alta.
- Plantilla mayor que la región → `None`.
- **Si T1 está hecho:** parametrizar sobre `_best_match_cv2` y `_best_match_bruteforce` para verificar que ambos backends coinciden en la posición encontrada.

`tests/test_routine_path.py`
- `analyze_routine_path(None)` y rutina vacía → ceros, sin excepción.
- Puntos separados 5 px → cuentan como `near_duplicate` (umbral ≤ 8).
- Salto de 300 px → cuenta como `large_jump` (umbral ≥ 250).
- Segmentación `quiet`/`move` con una secuencia conocida.

`tests/test_map_service.py`
- `_pathfinding_info((255,255,0))` → `non_walkable`.
- `_pathfinding_info((255,0,255))` → `unexplored`.
- `_pathfinding_info((128,128,128))` → `walkable` con `friction=128`.
- `_pathfinding_info(None)` → `None`.

`tests/test_settings_normalize.py`
- Valores fuera de rango se recortan (`validation_similarity_threshold` > 1 → 1,0).
- Claves ausentes toman el valor por defecto.
- Las regiones normalizan `width`/`height` a mínimo 1.

**Requisito previo:** `test_settings_normalize.py` importa `settings_store`, lo que **arranca el Health Monitor** por el efecto colateral descrito en T7. Haz T7 antes, o el test abrirá DXGI.

**10.3** Verificar que la suite corre sin Tibia, sin OBS y sin dependencias de Windows:

```powershell
python -m pytest tests/ -v
```

---

## T11 — Rotación de logs

`logs/` ya acumula 23 archivos y 1,2 MB. Tres flujos crecen sin límite:

- `logs/session_<ts>.log` — uno nuevo por arranque (`session_log.py`), nunca se purga.
- `logs/action_events.jsonl` — append infinito (`event_audit_log.py`).
- `data/bestiary_snapshots.jsonl` — append infinito (`bestiary_reader.persist_snapshot`).

Solución: purga por antigüedad al arrancar (borrar sesiones de más de N días, con N configurable y defecto 14) y rotación por tamaño para los `.jsonl` (rotar a `.1`, `.2` al superar unos 10 MB).

Ojo: `session_log.LOG_PATH` se calcula una sola vez a nivel de módulo. Si introduces rotación real, no rompas `get_log_path()`, que usa `ai_advisor._recent_log_lines()` para alimentar el contexto de la IA.

---

## T12 — Endurecer la API local

**Depende de la decisión de T2.** Si el Camino A gana (sin input automático), el riesgo baja mucho y esta tarea es opcional.

Riesgo actual: `POST /api/battle/scan-passive` provoca un click real y no tiene autenticación. Es una petición simple, sin preflight CORS, así que **cualquier página web abierta en el navegador del usuario puede enviarla**. La respuesta queda bloqueada por CORS, pero el efecto secundario —click y pulsación de tecla en la máquina— ya ocurrió.

Mitigación mínima: exigir una cabecera personalizada en todos los endpoints con efectos secundarios. Una cabecera no estándar fuerza el preflight, y el preflight falla en origen cruzado:

```python
@app.before_request
def require_local_header():
    if request.method in ("POST", "PUT", "DELETE"):
        if request.headers.get("X-Tibia-Mapper") != "1":
            return jsonify({"ok": False, "error": "Petición no autorizada."}), 403
```

Requiere añadir la cabecera a todos los `fetch` del frontend. Alternativa más sólida: token aleatorio generado al arrancar, inyectado en las plantillas y validado por petición.

---

## T13 — Empaquetar las rutas de IA y mapa en el EXE

`tibia-mapper.spec:13` construye desde `launcher.py`, que hace `from app import app`. Nunca importa `app_ai.py`, así que **el EXE distribuido no tiene `/api/ai/*` ni `/api/map/*`** ni la inyección de `ai_ui.js`.

Dos opciones:

- **A (mínima):** crear `launcher_ai.py` que importe de `app_ai` y apuntar el spec ahí.
- **B (recomendada):** fusionar el registro de rutas dentro de `app.py` detrás de un flag, y eliminar el punto de entrada dual. `app_ai.py` son 31 líneas; mantener dos entradas paralelas es una fuente permanente de divergencias como esta.

Si eliges B, conserva el `@app.after_request` que inyecta `ai_ui.js` — es cómo el panel de IA llega a la página sin modificar `index.html`.

---

## T14 — Retirar los restos de Bestiary

Bestiary fue reemplazado por Loot como señal de fin de ciclo Battle. Quedan restos:

- `battle_monitor.battle_runtime_status()` (líneas ~474-480): seis claves siempre `None` (`bestiary_target_name`, `bestiary_target_before`, `bestiary_target_current`, `bestiary_value_region`, `bestiary_snapshot`, `last_bestiary_before`, `last_bestiary_after`), con un comentario que las declara legacy "para que la UI existente no falle".
- `settings.bestiary_tracker_region`: en `DEFAULT_SETTINGS`, en `_normalize_settings`, y con un fieldset visible en `index.html`.
- `decision_engine.build_context()` lee `bestiary_target_before` / `bestiary_target_current` y `decide()` construye un mensaje de progreso con ellos — siempre vacío.

Orden seguro: primero quitar los consumidores en el frontend, luego los campos del backend. Verifica con `grep -rin "bestiary" static templates *.py` que no queda ningún lector antes de borrar cada campo.

**No borrar `bestiary_reader.py`.** El módulo conserva el nombre histórico pero `read_health_number()` está en uso activo por `health_monitor.py`. Si molesta el nombre, renómbralo a `ocr_reader.py` en un commit aparte, actualizando los imports.

---

## T15 — Eventos: implementar o retirar

**Requiere decisión del usuario.**

`screen_event_monitor.py` tiene ~350 líneas de infraestructura de concurrencia bien construida: `EventRuntimeState` con lock, workers por evento, encadenamiento con detección de ciclos, filtro por categorías, `event_busy` para pausar la rutina. Todo correcto.

Y alimenta un detector que es un stub:

```python
# screen_event_monitor.py:117-131
def analyze_event_region(event, image):
    ...
    return {"detected": False, ..., "reason": "Detector todavía no definido para este evento."}
```

Cascada de código muerto: nunca se lanza un worker → `wait_for_event_to_finish()` es inalcanzable → los cinco handlers de `mouse_helpers.py` (`_prepare_click`, `_prepare_write`, `_prepare_move_mouse`, `_prepare_detect_text`, `_prepare_custom`) son todos `TODO`. **La pestaña de Eventos de la UI no hace absolutamente nada**, pero permite crear, editar y encadenar eventos como si funcionara.

Opciones a plantear al usuario:

- **Implementar.** El detector puede reutilizar piezas existentes: `battle_monitor._best_match` para detección por plantilla, o `bestiary_reader.read_bestiary` para detección por texto. Además hay que corregir B8: `capture_event_region()` usa `ImageGrab.grab(all_screens=True)` (coordenadas del escritorio virtual) mientras el resto del sistema usa coordenadas locales DXGI — las regiones de eventos apuntan a píxeles distintos que las de Battle. Debe migrar a `get_live_frame()`.
- **Retirar/ocultar.** Marcar el subsistema como experimental y esconder la pestaña. Mantenerlo visible y no funcional confunde al usuario y a cualquier agente que lea el código creyendo que es una pieza en uso.

---

## 2. Checklist final antes de entregar

- [ ] `git branch --show-current` sigue siendo `feature/ai-advisor`; `main` intacto.
- [ ] `python -m pytest tests/ -v` en verde (si T10 está hecho).
- [ ] `python app.py` arranca y `http://127.0.0.1:5000` carga sin errores en consola.
- [ ] `python app_ai.py` arranca y `/api/ai/status` responde.
- [ ] Una rutina existente se ejecuta sin regresión.
- [ ] `logs/session_*.log` no muestra excepciones nuevas.
- [ ] Los umbrales recalibrados en T1 están documentados en el commit, con los valores observados.
- [ ] `ANALISIS_PROYECTO.md` y `CODEX_CONTEXT.md` actualizados con los cambios de arquitectura (especialmente T2 y T4, que alteran cómo funciona el sistema).
- [ ] Cada verificación que **no** pudiste ejecutar está listada explícitamente como pendiente, con el motivo.

---

## 3. Referencia rápida

**Ejecutar:**
```powershell
python app.py       # app base
python app_ai.py    # con rutas de IA y mapa
```

**Endpoints útiles para diagnóstico:**
```
http://127.0.0.1:5000/                                    UI principal
http://127.0.0.1:5000/battle                              UI de Battle
http://127.0.0.1:5000/api/status                          estado global
http://127.0.0.1:5000/api/ai/status                       proveedor IA + mapa + health
http://127.0.0.1:5000/api/map/position?x=31946&y=31900&z=7  consulta de mapa
```

**Patrones de log para grep:**
```
BATTLE PERF            tiempos por escaneo
BATTLE MATCH DEBUG     similitud por objetivo y si fue aceptado
BATTLE TRANSITION      cambios de fase idle ↔ waiting_loot_change
BATTLE LOOT CHANGE     detección de cambio en Loot
HEALTH ALERT           HP bajo umbral
HEALTH MONITOR ERROR   fallo de OCR o de captura
CHECKPOINT OK/FALLÓ    validación de pasos (tras T3)
STORE ERROR            JSON ilegible (tras T5)
```

**Archivos que casi nunca hay que tocar:** `app_paths.py` (rutas PyInstaller, delicado), `mapper_store.py` (SQLite, aislado y estable), `tibia_map_service.py` (lectura offline, correcto).

**Archivos de datos que no se deben borrar:** `settings.json`, `routines/`, `events/`, `battle_targets/`, `checkpoints/`, `data/mapper.db`.
