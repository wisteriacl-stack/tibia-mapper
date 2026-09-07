from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app_paths import RUNTIME_ROOT
from atomic_json import write_json_atomic
from session_log import log_event

BASE_DIR = RUNTIME_ROOT
ROUTINES_DIR = BASE_DIR / "routines"
ROUTINES_DIR.mkdir(parents=True, exist_ok=True)

VALID_ACTION_TYPES = {"left_click", "move_mouse", "write"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(name: str) -> str:
    value = (name or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "routine"


def _path(routine_id: str) -> Path:
    safe_id = slugify(routine_id)
    return ROUTINES_DIR / f"{safe_id}.json"


def _normalize_action(value: dict[str, Any] | None) -> dict[str, Any]:
    action = dict(value or {})
    action_type = str(action.get("type") or "").strip()
    if action_type not in VALID_ACTION_TYPES:
        raise ValueError("Tipo de acción de rutina inválido.")

    if action_type in {"left_click", "move_mouse"}:
        return {
            "type": action_type,
            "x": int(action.get("x", 0)),
            "y": int(action.get("y", 0)),
        }

    text = str(action.get("text") or "")
    if not text:
        raise ValueError("La acción write necesita texto.")
    return {"type": "write", "text": text}


def _normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    if str(step.get("type") or "").strip() == "action" or step.get("action"):
        return {
            "type": "action",
            "action": _normalize_action(step.get("action")),
        }

    normalized = {
        "type": "coordinate",
        "x": int(step.get("x", 0)),
        "y": int(step.get("y", 0)),
    }
    validation_image = str(step.get("validation_image") or "").strip()
    if validation_image:
        normalized["validation_image"] = validation_image
    return normalized


def _normalize_event_config(value: dict[str, Any] | None) -> dict[str, Any]:
    value = dict(value or {})
    enabled_ids = []
    for item in value.get("enabled_event_ids") or []:
        event_id = str(item or "").strip()
        if event_id and event_id not in enabled_ids:
            enabled_ids.append(event_id)
    return {
        "detected_enabled": bool(value.get("detected_enabled", False)),
        "enabled_event_ids": enabled_ids,
    }


def list_routines() -> list[dict[str, Any]]:
    routines: list[dict[str, Any]] = []
    for path in sorted(ROUTINES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["id"] = path.stem
            data["steps"] = [_normalize_step(step) for step in (data.get("steps") or [])]
            data["step_count"] = len(data.get("steps") or [])
            data["checkpoint_count"] = sum(
                1 for step in (data.get("steps") or []) if step.get("validation_image")
            )
            data["action_step_count"] = sum(
                1 for step in (data.get("steps") or []) if step.get("type") == "action"
            )
            data["event_config"] = _normalize_event_config(data.get("event_config"))
            routines.append(data)
        except Exception as exc:
            log_event(f"STORE ERROR | archivo ilegible: {path.name} | {type(exc).__name__}: {exc}")
            continue
    return routines


def get_routine(routine_id: str) -> dict[str, Any] | None:
    path = _path(routine_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["id"] = path.stem
    data["steps"] = [_normalize_step(step) for step in (data.get("steps") or [])]
    data["event_config"] = _normalize_event_config(data.get("event_config"))
    return data


def find_routine_by_name(name: str) -> dict[str, Any] | None:
    target = (name or "").strip().casefold()
    for routine in list_routines():
        if str(routine.get("name") or "").strip().casefold() == target:
            return get_routine(routine["id"])
    return None


def create_routine(name: str, version: str) -> dict[str, Any]:
    clean_name = (name or "").strip()
    clean_version = (version or "").strip()
    if not clean_name:
        raise ValueError("El nombre de la rutina es obligatorio.")
    if not clean_version:
        raise ValueError("La versión es obligatoria.")

    routine_id = slugify(clean_name)
    path = _path(routine_id)
    if path.exists():
        raise ValueError("Ya existe una rutina con ese nombre.")

    data = {
        "id": routine_id,
        "name": clean_name,
        "version": clean_version,
        "created_at": _now(),
        "updated_at": _now(),
        "steps": [],
        "event_config": _normalize_event_config(None),
    }
    save_routine(routine_id, data)
    return get_routine(routine_id)


def save_routine(routine_id: str, data: dict[str, Any]) -> None:
    path = _path(routine_id)
    payload = dict(data)
    payload["id"] = path.stem
    payload["updated_at"] = _now()
    payload["steps"] = [_normalize_step(step) for step in (payload.get("steps") or [])]
    payload["event_config"] = _normalize_event_config(payload.get("event_config"))
    write_json_atomic(path, payload)


def update_routine(routine_id: str, name: str, version: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    current = get_routine(routine_id)
    if not current:
        raise ValueError("Rutina no encontrada.")
    current["name"] = (name or "").strip() or current["name"]
    current["version"] = (version or "").strip() or current["version"]
    current["steps"] = steps
    save_routine(routine_id, current)
    return get_routine(routine_id)


def set_routine_event_config(
    routine_id: str,
    detected_enabled: bool,
    enabled_event_ids: list[str],
) -> dict[str, Any]:
    routine = get_routine(routine_id)
    if not routine:
        raise ValueError("Rutina no encontrada.")
    routine["event_config"] = _normalize_event_config({
        "detected_enabled": detected_enabled,
        "enabled_event_ids": enabled_event_ids,
    })
    save_routine(routine_id, routine)
    return get_routine(routine_id)


def append_step(routine_id: str, x: int, y: int) -> dict[str, Any]:
    routine = get_routine(routine_id)
    if not routine:
        raise ValueError("Rutina no encontrada.")
    routine.setdefault("steps", []).append({"type": "coordinate", "x": int(x), "y": int(y)})
    save_routine(routine_id, routine)
    return get_routine(routine_id)


def append_action_step(routine_id: str, action: dict[str, Any]) -> dict[str, Any]:
    routine = get_routine(routine_id)
    if not routine:
        raise ValueError("Rutina no encontrada.")
    routine.setdefault("steps", []).append({"type": "action", "action": _normalize_action(action)})
    save_routine(routine_id, routine)
    return get_routine(routine_id)


def insert_step(routine_id: str, index: int, x: int, y: int) -> dict[str, Any]:
    routine = get_routine(routine_id)
    if not routine:
        raise ValueError("Rutina no encontrada.")
    steps = routine.setdefault("steps", [])
    safe_index = max(0, min(int(index), len(steps)))
    steps.insert(safe_index, {"type": "coordinate", "x": int(x), "y": int(y)})
    save_routine(routine_id, routine)
    return get_routine(routine_id)


def set_step_validation_image(routine_id: str, index: int, image_path: str) -> dict[str, Any]:
    routine = get_routine(routine_id)
    if not routine:
        raise ValueError("Rutina no encontrada.")
    steps = routine.setdefault("steps", [])
    if index < 0 or index >= len(steps):
        raise ValueError("Paso no encontrado.")
    if steps[index].get("type") == "action":
        raise ValueError("Un paso de acción no usa imagen de validación.")
    steps[index]["validation_image"] = str(image_path)
    save_routine(routine_id, routine)
    return get_routine(routine_id)


def delete_step(routine_id: str, index: int) -> dict[str, Any]:
    routine = get_routine(routine_id)
    if not routine:
        raise ValueError("Rutina no encontrada.")
    steps = routine.setdefault("steps", [])
    if index < 0 or index >= len(steps):
        raise ValueError("Paso no encontrado.")
    del steps[index]
    save_routine(routine_id, routine)
    return get_routine(routine_id)
