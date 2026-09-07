from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Any

from checkpoint_store import compare_checkpoint
from mouse_helpers import execute_step
from routine_store import get_routine
from screen_event_monitor import monitor_events, wait_for_tibia_and_f12
from session_log import log_event
from settings_store import get_settings

WAIT_POLL_SECONDS = 0.05
VK_F12 = 0x7B
VK_CONTROL = 0x11


def _key_down(vk: int) -> bool:
    if sys.platform != "win32":
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _runtime_hotkey_state(paused: bool, f12_latched: bool) -> tuple[bool, bool, bool]:
    down = _key_down(VK_F12)
    if down and not f12_latched:
        f12_latched = True
        if _key_down(VK_CONTROL):
            log_event("RUTINA: Ctrl+F12 recibido; detención solicitada")
            return paused, f12_latched, True
        paused = not paused
        log_event("RUTINA pausada por F12" if paused else "RUTINA reanudada por F12")
    elif not down:
        f12_latched = False
    return paused, f12_latched, False


def wait_runtime_control(paused: bool, f12_latched: bool) -> tuple[bool, bool, bool]:
    while True:
        paused, f12_latched, stop_requested = _runtime_hotkey_state(paused, f12_latched)
        if stop_requested or not paused:
            return paused, f12_latched, stop_requested
        time.sleep(WAIT_POLL_SECONDS)


def load_routine_steps(routine_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    routine = get_routine(routine_id)
    if not routine:
        raise ValueError("Rutina no encontrada.")
    steps = [dict(step) for step in (routine.get("steps") or [])]
    if not steps:
        raise ValueError("La rutina no tiene registros para ejecutar.")
    return routine, steps


def build_execution_records(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if step.get("type") == "action":
            records.append({
                "index": index,
                "type": "action",
                "action": dict(step.get("action") or {}),
                "status": "pending",
            })
            continue

        record = {
            "index": index,
            "type": "coordinate",
            "x": int(step.get("x", 0)),
            "y": int(step.get("y", 0)),
            "status": "pending",
        }
        if step.get("validation_image"):
            record["validation_image"] = str(step.get("validation_image"))
        records.append(record)
    return records


def wait_until_events_finish(event_busy: threading.Event, control: dict[str, bool]) -> bool:
    logged = False
    while event_busy.is_set():
        control["paused"], control["f12_latched"], stop_requested = wait_runtime_control(
            control["paused"], control["f12_latched"]
        )
        if stop_requested:
            return False
        if not logged:
            log_event("RUTINA pausada: esperando que termine el evento activo")
            logged = True
        time.sleep(WAIT_POLL_SECONDS)
    if logged:
        log_event("RUTINA reanudada: evento finalizado")
    return True


def wait_between_steps(event_busy: threading.Event, seconds: float, control: dict[str, bool]) -> bool:
    remaining = float(seconds)
    last_tick = time.monotonic()
    while remaining > 0:
        control["paused"], control["f12_latched"], stop_requested = wait_runtime_control(
            control["paused"], control["f12_latched"]
        )
        if stop_requested:
            return False
        if event_busy.is_set():
            if not wait_until_events_finish(event_busy, control):
                return False
            last_tick = time.monotonic()
            continue
        now = time.monotonic()
        elapsed = now - last_tick
        remaining -= elapsed
        last_tick = now
        if remaining > 0:
            time.sleep(min(WAIT_POLL_SECONDS, remaining))
    return True


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


def execute_routine(routine_id: str) -> dict[str, Any]:
    execution_settings = get_settings()
    step_delay_seconds = float(execution_settings.get("step_delay_seconds", 2.0))

    routine, steps = load_routine_steps(routine_id)
    records = build_execution_records(steps)
    results: list[dict[str, Any]] = []
    event_config = dict(routine.get("event_config") or {})
    detected_enabled = bool(event_config.get("detected_enabled", False))
    enabled_event_ids = [str(x) for x in (event_config.get("enabled_event_ids") or []) if str(x)]

    wait_for_tibia_and_f12()
    control = {"paused": False, "f12_latched": False}
    stopped_by_hotkey = False

    monitor_stop = threading.Event()
    event_busy = threading.Event()
    monitor_thread = None
    if detected_enabled:
        monitor_thread = threading.Thread(
            target=monitor_events,
            kwargs={
                "stop_event": monitor_stop,
                "event_busy": event_busy,
                "enabled_event_ids": enabled_event_ids,
                "allowed_categories": {"move_mouse"},
            },
            daemon=True,
            name=f"event-monitor-{routine_id}",
        )
        monitor_thread.start()
        log_event(
            f"MONITOR EVENTOS habilitado para rutina={routine_id} | "
            f"eventos={enabled_event_ids} | categorias_permitidas=['move_mouse']"
        )
    else:
        log_event(f"MONITOR EVENTOS deshabilitado para rutina={routine_id}")

    log_event(
        f"EJECUCIÓN RUTINA INICIADA | id={routine['id']} | nombre={routine['name']} | "
        f"version={routine['version']} | pasos={len(records)} | step_delay={step_delay_seconds:.2f}s | "
        "controles=F12 pausa/reanuda, Ctrl+F12 detiene"
    )

    try:
        for position, record in enumerate(records):
            control["paused"], control["f12_latched"], stop_requested = wait_runtime_control(
                control["paused"], control["f12_latched"]
            )
            if stop_requested:
                stopped_by_hotkey = True
                break

            if not wait_until_events_finish(event_busy, control):
                stopped_by_hotkey = True
                break

            record["status"] = "running"

            if record.get("type") == "action":
                action = dict(record.get("action") or {})
                log_event(
                    f"PASO ACCIÓN registrado | rutina={routine['id']} | paso={record['index'] + 1}/{len(records)} | "
                    f"tipo={action.get('type')} | no se genera input automático"
                )
                result = {
                    "ok": True,
                    "skipped": True,
                    "reason": "Paso de acción registrado; la ejecución automática de input no está habilitada.",
                    "action": action,
                }
            else:
                log_event(
                    f"EJECUTANDO PASO | rutina={routine['id']} | paso={record['index'] + 1}/{len(records)} | "
                    f"x={record['x']} y={record['y']} | checkpoint={record.get('validation_image')}"
                )
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

            record["status"] = "done" if result.get("ok") else "error"
            record["result"] = result
            results.append(dict(record))

            if not result.get("ok"):
                log_event(f"EJECUCIÓN DETENIDA | rutina={routine['id']} | paso={record['index'] + 1}")
                break

            if position < len(records) - 1:
                if not wait_between_steps(event_busy, step_delay_seconds, control):
                    stopped_by_hotkey = True
                    break
    finally:
        monitor_stop.set()
        if monitor_thread is not None:
            monitor_thread.join(timeout=3)

    completed = (
        not stopped_by_hotkey
        and len(results) == len(records)
        and all(item.get("status") == "done" for item in results)
    )

    log_event(
        f"EJECUCIÓN RUTINA TERMINADA | id={routine['id']} | completada={completed} | "
        f"detenida_hotkey={stopped_by_hotkey} | ejecutados={len(results)}/{len(records)}"
    )

    return {
        "ok": completed,
        "routine": routine,
        "records": records,
        "results": results,
        "settings": execution_settings,
        "event_config": event_config,
        "stopped_by_hotkey": stopped_by_hotkey,
    }
