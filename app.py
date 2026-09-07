import time
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
from battle_action_executor import execute_battle_action
from battle_monitor import battle_runtime_status, reset_battle_runtime, update_battle_runtime
from battle_monitor_thread import battle_monitor_status, start_battle_monitor, stop_battle_monitor
from battle_store import (
    battle_target_action_image_path,
    battle_target_image_path,
    crop_battle_target_image,
    delete_battle_target,
    list_battle_targets,
    save_battle_target_image,
    update_battle_target,
)
from capture_utils import (
    capture_info,
    get_latest_capture,
    wait_for_f12_position,
    wait_for_f12_region,
    wait_for_tibia_f10,
)
from checkpoint_store import (
    capture_checkpoint,
    compare_checkpoint,
    get_checkpoint_file,
    save_uploaded_checkpoint,
)
from decision_engine import decide
from event_store import create_event, delete_event, get_event, list_events, update_event
from mapper_store import add_point, delete_point, init_db, list_points
from recorder import recording_status, start_recording, stop_recording
from routine_executor import execute_routine
from routine_store import (
    create_routine,
    delete_step,
    find_routine_by_name,
    get_routine,
    insert_step,
    list_routines,
    set_routine_event_config,
    set_step_validation_image,
    update_routine,
)
from session_log import get_log_path, log_event
from settings_store import get_settings, update_settings

app = Flask(__name__)
init_db()
log_event("Tibia Mapper iniciado")


def _to_int(value):
    if value in (None, ""):
        return None
    return int(value)


def _form_region(prefix: str):
    x = request.form.get(f"{prefix}_x")
    if x in (None, ""):
        return None
    return {
        "x": int(x),
        "y": int(request.form.get(f"{prefix}_y")),
        "width": int(request.form.get(f"{prefix}_width")),
        "height": int(request.form.get(f"{prefix}_height")),
    }


@app.get("/")
def index():
    return render_template(
        "index.html",
        points=list_points(),
        routines=list_routines(),
        events=list_events(),
        battle_targets=list_battle_targets(),
        settings=get_settings(),
        latest_capture=capture_info(get_latest_capture()),
        recording=recording_status(),
        log_path=get_log_path(),
    )


@app.get("/battle")
def battle_page():
    return render_template(
        "battle.html",
        settings=get_settings(),
        battle_targets=list_battle_targets(),
    )


@app.get("/api/status")
def status():
    return jsonify({
        "ok": True,
        "latest_capture": capture_info(get_latest_capture()),
        "points": list_points(),
        "routines": list_routines(),
        "events": list_events(),
        "battle_targets": list_battle_targets(),
        "battle_state": battle_runtime_status(),
        "settings": get_settings(),
        "recording": recording_status(),
        "log_path": get_log_path(),
    })


@app.get("/api/settings")
def settings_get():
    return jsonify({"ok": True, "settings": get_settings()})


@app.put("/api/settings")
def settings_update():
    payload = request.get_json(silent=True) or {}
    try:
        settings = update_settings(payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    log_event(f"Configuración actualizada | {settings}")
    return jsonify({"ok": True, "settings": settings})


@app.get("/api/battle/targets")
def battle_targets_list():
    return jsonify({"ok": True, "targets": list_battle_targets()})


@app.post("/api/battle/targets")
def battle_targets_create():
    try:
        target = save_battle_target_image(
            name=str(request.form.get("name") or ""),
            priority=int(request.form.get("priority") or 100),
            uploaded_file=request.files.get("image"),
            crop_region=_form_region("crop"),
            action_uploaded_file=request.files.get("action_image"),
            action_crop_region=_form_region("action_crop"),
        )
    except (OSError, TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    reset_battle_runtime()
    log_event(
        f"Battle referencia creada | id={target['id']} | prioridad={target['priority']} | "
        f"action_image={target.get('action_image')}"
    )
    return jsonify({"ok": True, "target": target, "targets": list_battle_targets()})


@app.put("/api/battle/targets/<target_id>")
def battle_target_update(target_id):
    payload = request.get_json(silent=True) or {}
    try:
        target = update_battle_target(target_id, payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    reset_battle_runtime()
    log_event(
        f"Battle referencia actualizada | id={target_id} | enabled={target.get('enabled')} | "
        f"prioridad={target.get('priority')}"
    )
    return jsonify({"ok": True, "target": target, "targets": list_battle_targets()})


@app.get("/api/battle/targets/<target_id>/image")
def battle_target_image(target_id):
    path = battle_target_image_path(target_id)
    if not path:
        return jsonify({"ok": False, "error": "Imagen battle no encontrada."}), 404
    return send_file(path, mimetype="image/png", max_age=0)


@app.get("/api/battle/targets/<target_id>/action-image")
def battle_target_action_image(target_id):
    path = battle_target_action_image_path(target_id)
    if not path:
        return jsonify({"ok": False, "error": "Imagen de acción Battle en ejecución no encontrada."}), 404
    return send_file(path, mimetype="image/png", max_age=0)


@app.post("/api/battle/targets/<target_id>/crop")
def battle_target_crop(target_id):
    payload = request.get_json(silent=True) or {}
    try:
        target = crop_battle_target_image(
            target_id,
            int(payload.get("x")),
            int(payload.get("y")),
            int(payload.get("width")),
            int(payload.get("height")),
        )
    except (OSError, TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    reset_battle_runtime()
    log_event(
        f"Battle referencia recortada | id={target_id} | "
        f"{target.get('image_width')}x{target.get('image_height')}"
    )
    return jsonify({"ok": True, "target": target, "targets": list_battle_targets()})


@app.delete("/api/battle/targets/<target_id>")
def battle_target_delete(target_id):
    if not delete_battle_target(target_id):
        return jsonify({"ok": False, "error": "Referencia battle no encontrada."}), 404
    reset_battle_runtime()
    log_event(f"Battle referencia eliminada | id={target_id}")
    return jsonify({"ok": True, "targets": list_battle_targets()})


@app.post("/api/battle/scan")
def battle_scan():
    settings = dict(get_settings())
    try:
        wait_for_tibia_f10(
            title_text=str(settings.get("tibia_window_title") or "Tibia"),
            timeout_seconds=30.0,
        )
        # La prueba manual debe ejecutar exactamente un análisis aunque el monitor
        # continuo esté detenido. El override es local y no persiste el flag.
        settings["battle_detection_enabled"] = True
        log_event("BATTLE prueba manual | F10 recibido | force_scan=True")
        state = update_battle_runtime(settings)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    pending = state.get("pending_target")
    if state.get("action_triggered") and pending:
        log_event(
            f"BATTLE gatillo lógico | id={pending.get('target_id')} | prioridad={pending.get('priority')} | "
            f"similitud={pending.get('similarity')} | serial={state.get('trigger_serial')}"
        )
    if state.get("released"):
        log_event(f"BATTLE liberado | reason={state.get('release_reason')}")
    return jsonify({"ok": True, "state": state})


@app.post("/api/battle/scan-passive")
def battle_scan_passive():
    """OBSOLETA: el bucle de detección ahora vive en el backend (battle_monitor_thread).

    Se conserva temporalmente para no romper una pestaña abierta con una
    versión anterior del frontend. Usar /api/battle/monitor/start|stop|state.
    """
    settings = get_settings()
    try:
        state = update_battle_runtime(settings)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    pending = state.get("pending_target")
    if state.get("action_triggered") and pending:
        result = execute_battle_action(pending, settings)
        log_event(
            f"BATTLE gatillo pasivo | "
            f"id={pending.get('target_id')} | "
            f"serial={state.get('trigger_serial')} | "
            f"action_ok={result.get('ok')} | executed={result.get('executed')} | "
            f"reason={result.get('reason')}"
        )
    if state.get("released"):
        log_event(
            "BATTLE listo para nuevo análisis | "
            f"reason={state.get('release_reason')}"
        )
    return jsonify({"ok": True, "state": state})


@app.post("/api/battle/monitor/start")
def battle_monitor_start():
    return jsonify({"ok": True, "monitor": start_battle_monitor()})


@app.post("/api/battle/monitor/stop")
def battle_monitor_stop():
    return jsonify({"ok": True, "monitor": stop_battle_monitor()})


@app.get("/api/battle/monitor/state")
def battle_monitor_state():
    return jsonify({"ok": True, "monitor": battle_monitor_status()})


@app.get("/api/battle/decision")
def battle_decision_get():
    state = battle_runtime_status()
    decision = decide(state, list_battle_targets())
    return jsonify({"ok": True, "decision": decision})


@app.post("/api/battle/decision")
def battle_decision_post():
    payload = request.get_json(silent=True) or {}
    telemetry = dict(payload.get("telemetry") or {})
    state = battle_runtime_status()
    decision = decide(state, list_battle_targets(), telemetry=telemetry)
    log_event(
        "DECISION advisory | "
        f"recommendation={decision.get('recommendation')} | "
        f"target={decision.get('target_id')} | confidence={decision.get('confidence')}"
    )
    return jsonify({"ok": True, "decision": decision})


@app.post("/api/battle/reset")
def battle_reset():
    return jsonify({"ok": True, "state": reset_battle_runtime()})


@app.get("/api/events")
def events_status():
    return jsonify({"ok": True, "events": list_events()})


@app.post("/api/events/capture-point")
def event_capture_point():
    try:
        point = wait_for_f12_position(timeout_seconds=30.0)
    except (RuntimeError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "point": point})


@app.post("/api/events/capture-region")
def event_capture_region():
    try:
        region = wait_for_f12_region(timeout_seconds=30.0)
    except (RuntimeError, TimeoutError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "region": region})


@app.post("/api/events")
def events_create():
    payload = request.get_json(silent=True) or {}
    try:
        event = create_event(
            name=str(payload.get("name") or ""),
            category=str(payload.get("category") or "detect_text"),
            region=dict(payload.get("region") or {}),
            action_code=str(payload.get("action_code") or ""),
            chain=list(payload.get("chain") or []),
            trigger=dict(payload.get("trigger") or {}) or None,
            actions=list(payload.get("actions") or []) if "actions" in payload else None,
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    log_event(
        f"Evento creado | {event['id']} | trigger={event.get('trigger', {}).get('type')} | "
        f"acciones={[a.get('type') for a in event.get('actions', [])]}"
    )
    return jsonify({"ok": True, "event": event, "events": list_events()})


@app.get("/api/events/<event_id>")
def events_get(event_id):
    event = get_event(event_id)
    if not event:
        return jsonify({"ok": False, "error": "Evento no encontrado."}), 404
    return jsonify({"ok": True, "event": event})


@app.put("/api/events/<event_id>")
def events_update(event_id):
    payload = request.get_json(silent=True) or {}
    try:
        event = update_event(event_id, payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    log_event(
        f"Evento actualizado | {event['id']} | trigger={event.get('trigger', {}).get('type')} | "
        f"acciones={[a.get('type') for a in event.get('actions', [])]}"
    )
    return jsonify({"ok": True, "event": event, "events": list_events()})


@app.delete("/api/events/<event_id>")
def events_delete(event_id):
    if not delete_event(event_id):
        return jsonify({"ok": False, "error": "Evento no encontrado."}), 404
    log_event(f"Evento eliminado | {event_id}")
    return jsonify({"ok": True, "events": list_events()})


@app.get("/api/routines")
def routines_status():
    return jsonify({"ok": True, "routines": list_routines()})


@app.post("/api/routines")
def routines_create():
    payload = request.get_json(silent=True) or {}
    try:
        routine = create_routine(
            str(payload.get("name") or ""),
            str(payload.get("version") or ""),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    log_event(f"Rutina creada | {routine['name']} | versión={routine['version']}")
    return jsonify({"ok": True, "routine": routine, "routines": list_routines()})


@app.get("/api/routines/<routine_id>")
def routines_get(routine_id):
    routine = get_routine(routine_id)
    if not routine:
        return jsonify({"ok": False, "error": "Rutina no encontrada."}), 404
    return jsonify({"ok": True, "routine": routine})


@app.put("/api/routines/<routine_id>")
def routines_update(routine_id):
    payload = request.get_json(silent=True) or {}
    try:
        routine = update_routine(
            routine_id,
            str(payload.get("name") or ""),
            str(payload.get("version") or ""),
            list(payload.get("steps") or []),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    log_event(f"Rutina editada | {routine['name']} | pasos={len(routine.get('steps') or [])}")
    return jsonify({"ok": True, "routine": routine, "routines": list_routines()})


@app.put("/api/routines/<routine_id>/event-config")
def routine_event_config_update(routine_id):
    payload = request.get_json(silent=True) or {}
    try:
        routine = set_routine_event_config(
            routine_id,
            bool(payload.get("detected_enabled", False)),
            list(payload.get("enabled_event_ids") or []),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    log_event(
        f"Configuración eventos rutina actualizada | rutina={routine_id} | "
        f"detected={routine.get('event_config', {}).get('detected_enabled')} | "
        f"eventos={routine.get('event_config', {}).get('enabled_event_ids')}"
    )
    return jsonify({"ok": True, "routine": routine, "routines": list_routines()})


@app.post("/api/routines/<routine_id>/steps")
def routines_insert_step(routine_id):
    payload = request.get_json(silent=True) or {}
    try:
        routine = insert_step(
            routine_id,
            int(payload.get("index", 0)),
            int(payload.get("x")),
            int(payload.get("y")),
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "routine": routine})


@app.delete("/api/routines/<routine_id>/steps/<int:index>")
def routines_delete_step(routine_id, index):
    try:
        routine = delete_step(routine_id, index)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "routine": routine})


@app.get("/api/routines/<routine_id>/steps/<int:index>/checkpoint")
def routine_checkpoint_get(routine_id, index):
    if not get_routine(routine_id):
        return jsonify({"ok": False, "error": "Rutina no encontrada."}), 404
    path = get_checkpoint_file(routine_id, index)
    if not path:
        return jsonify({"ok": False, "error": "El paso no tiene imagen de validación."}), 404
    return send_file(path, mimetype="image/png", max_age=0)


@app.post("/api/routines/<routine_id>/steps/<int:index>/checkpoint/capture")
def routine_checkpoint_capture(routine_id, index):
    routine = get_routine(routine_id)
    if not routine:
        return jsonify({"ok": False, "error": "Rutina no encontrada."}), 404
    if index < 0 or index >= len(routine.get("steps") or []):
        return jsonify({"ok": False, "error": "Paso no encontrado."}), 404

    payload = request.get_json(silent=True) or {}
    delay_seconds = min(10.0, max(0.0, float(payload.get("delay_seconds", 0))))
    if delay_seconds:
        time.sleep(delay_seconds)

    settings = get_settings()
    image_path = capture_checkpoint(
        routine_id,
        index,
        settings["map_validation_region"],
    )
    routine = set_step_validation_image(routine_id, index, image_path)
    log_event(f"Checkpoint capturado | rutina={routine_id} | paso={index + 1} | {image_path}")
    return jsonify({"ok": True, "routine": routine, "image": image_path})


@app.post("/api/routines/<routine_id>/steps/<int:index>/checkpoint/upload")
def routine_checkpoint_upload(routine_id, index):
    routine = get_routine(routine_id)
    if not routine:
        return jsonify({"ok": False, "error": "Rutina no encontrada."}), 404
    if index < 0 or index >= len(routine.get("steps") or []):
        return jsonify({"ok": False, "error": "Paso no encontrado."}), 404

    uploaded = request.files.get("image")
    try:
        image_path = save_uploaded_checkpoint(routine_id, index, uploaded)
        routine = set_step_validation_image(routine_id, index, image_path)
    except (OSError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    log_event(f"Checkpoint reemplazado | rutina={routine_id} | paso={index + 1} | {image_path}")
    return jsonify({"ok": True, "routine": routine, "image": image_path})


@app.post("/api/routines/<routine_id>/steps/<int:index>/checkpoint/compare")
def routine_checkpoint_compare(routine_id, index):
    routine = get_routine(routine_id)
    if not routine:
        return jsonify({"ok": False, "error": "Rutina no encontrada."}), 404

    settings = get_settings()
    result = compare_checkpoint(
        routine_id,
        index,
        settings["map_validation_region"],
        settings["validation_similarity_threshold"],
    )
    return jsonify(result)


@app.post("/api/routines/start")
def routines_start():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    routine = find_routine_by_name(name)
    if not routine:
        return jsonify({"ok": False, "error": "No existe una rutina con ese nombre."}), 404

    try:
        execution = execute_routine(routine["id"])
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({
        "ok": bool(execution.get("ok")),
        "routine": execution.get("routine"),
        "records": execution.get("records") or [],
        "results": execution.get("results") or [],
        "settings": execution.get("settings") or {},
        "event_config": execution.get("event_config") or {},
        "message": (
            f"Rutina {routine['name']} recorrida: "
            f"{len(execution.get('results') or [])}/{len(execution.get('records') or [])} registros procesados."
        ),
    })


@app.post("/api/recording/start")
def recording_start():
    payload = request.get_json(silent=True) or {}
    routine_id = str(payload.get("routine_id") or "").strip()
    try:
        current = start_recording(routine_id)
    except (RuntimeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "recording": current, "routine": get_routine(routine_id)})


@app.post("/api/recording/stop")
def recording_stop():
    previous = recording_status().get("routine_id")
    current = stop_recording()
    return jsonify({
        "ok": True,
        "recording": current,
        "routine": get_routine(previous) if previous else None,
    })


@app.post("/api/points")
def create_point():
    payload = request.get_json(silent=True) or {}
    label = str(payload.get("label") or "").strip()
    if not label:
        return jsonify({"ok": False, "error": "label es obligatorio"}), 400

    try:
        x = _to_int(payload.get("x"))
        y = _to_int(payload.get("y"))
        z = _to_int(payload.get("z"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "x, y y z deben ser enteros"}), 400

    note = str(payload.get("note") or "").strip() or None
    latest = get_latest_capture()
    screenshot = str(latest) if latest else None
    point_id = add_point(label=label, x=x, y=y, z=z, note=note, screenshot=screenshot)
    log_event(f"Punto guardado #{point_id} | {label} | x={x} y={y} z={z}")
    return jsonify({"ok": True, "id": point_id, "points": list_points()})


@app.delete("/api/points/<int:point_id>")
def remove_point(point_id):
    deleted = delete_point(point_id)
    if not deleted:
        return jsonify({"ok": False, "error": "Punto no encontrado"}), 404
    log_event(f"Punto eliminado #{point_id}")
    return jsonify({"ok": True, "points": list_points()})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)