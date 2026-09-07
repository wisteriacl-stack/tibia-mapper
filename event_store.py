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
EVENTS_DIR = BASE_DIR / "events"
EVENTS_DIR.mkdir(parents=True, exist_ok=True)

VALID_CATEGORIES = {"move_mouse", "click", "left_click", "write", "detect_text"}
VALID_TRIGGER_TYPES = {"detect_text", "battle_reference", "legacy_manual"}
VALID_ACTION_TYPES = {"left_click", "move_mouse", "write"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "event"


def _path(event_id: str) -> Path:
    return EVENTS_DIR / f"{slugify(event_id)}.json"


def list_events() -> list[dict[str, Any]]:
    result = []
    for path in sorted(EVENTS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["id"] = path.stem
            result.append(data)
        except Exception as exc:
            log_event(f"STORE ERROR | archivo ilegible: {path.name} | {type(exc).__name__}: {exc}")
            continue
    return result


def get_event(event_id: str) -> dict[str, Any] | None:
    path = _path(event_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["id"] = path.stem
    return data


def _region(value: dict[str, Any] | None) -> dict[str, int]:
    value = dict(value or {})
    return {
        "x": int(value.get("x", 0)),
        "y": int(value.get("y", 0)),
        "width": max(1, int(value.get("width", 1))),
        "height": max(1, int(value.get("height", 1))),
    }


def _normalize_trigger(trigger: dict[str, Any] | None, legacy: dict[str, Any]) -> dict[str, Any]:
    if trigger:
        data = dict(trigger)
        kind = str(data.get("type") or "").strip()
        if kind not in VALID_TRIGGER_TYPES:
            raise ValueError("Tipo de gatillo inválido.")
        data["type"] = kind
        if kind == "detect_text":
            data["region"] = _region(data.get("region"))
            data["text"] = str(data.get("text") or "").strip()
            if not data["text"]:
                raise ValueError("El gatillo detect_text necesita texto a detectar.")
        if kind == "battle_reference":
            data["reference_id"] = str(data.get("reference_id") or "").strip()
            if not data["reference_id"]:
                raise ValueError("El gatillo Battle necesita una referencia.")
        return data

    category = str(legacy.get("category") or "").strip()
    if category == "detect_text":
        return {
            "type": "detect_text",
            "text": str(legacy.get("action_code") or "").strip(),
            "region": _region(legacy.get("region")),
        }
    return {"type": "legacy_manual", "region": _region(legacy.get("region"))}


def _normalize_actions(actions: list[dict[str, Any]] | None, legacy: dict[str, Any]) -> list[dict[str, Any]]:
    if actions is None:
        category = str(legacy.get("category") or "")
        if category in {"click", "left_click"}:
            r = _region(legacy.get("region"))
            return [{"type": "left_click", "x": r["x"], "y": r["y"]}]
        if category == "move_mouse":
            r = _region(legacy.get("region"))
            return [{"type": "move_mouse", "x": r["x"], "y": r["y"]}]
        if category == "write":
            return [{"type": "write", "text": str(legacy.get("action_code") or "")}]
        return []

    result: list[dict[str, Any]] = []
    for raw in actions:
        action = dict(raw or {})
        kind = str(action.get("type") or "").strip()
        if kind not in VALID_ACTION_TYPES:
            raise ValueError(f"Acción inválida: {kind or '(vacía)' }.")
        if kind in {"left_click", "move_mouse"}:
            action = {"type": kind, "x": int(action.get("x", 0)), "y": int(action.get("y", 0))}
        elif kind == "write":
            text = str(action.get("text") or "")
            if not text:
                raise ValueError("La acción write necesita texto.")
            action = {"type": kind, "text": text}
        result.append(action)
    return result


def save_event(event_id: str, data: dict[str, Any]) -> dict[str, Any]:
    path = _path(event_id)
    payload = dict(data)
    payload["id"] = path.stem
    payload["name"] = str(payload.get("name") or "").strip()
    if not payload["name"]:
        raise ValueError("El nombre del evento es obligatorio.")

    # Nuevo modelo: un evento es un gatillo visual + una secuencia de acciones.
    payload["trigger"] = _normalize_trigger(payload.get("trigger"), payload)
    payload["actions"] = _normalize_actions(payload.get("actions"), payload)

    # Compatibilidad con eventos antiguos y con las pantallas existentes.
    payload["category"] = str(payload.get("category") or "detect_text").strip()
    if payload["category"] not in VALID_CATEGORIES:
        payload["category"] = "detect_text"
    payload["region"] = _region(payload.get("region") or payload["trigger"].get("region"))
    payload["action_code"] = str(payload.get("action_code") or payload["trigger"].get("text") or "")
    payload["chain"] = [str(item).strip() for item in (payload.get("chain") or []) if str(item).strip()]
    payload["enabled"] = bool(payload.get("enabled", True))
    payload["updated_at"] = _now()
    payload.setdefault("created_at", _now())

    write_json_atomic(path, payload)
    return get_event(path.stem)


def create_event(
    name: str,
    category: str = "detect_text",
    region: dict[str, Any] | None = None,
    action_code: str = "",
    chain=None,
    trigger: dict[str, Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("El nombre del evento es obligatorio.")
    event_id = slugify(clean_name)
    if _path(event_id).exists():
        raise ValueError("Ya existe un evento con ese nombre.")
    return save_event(event_id, {
        "name": clean_name,
        "category": category,
        "region": region or {},
        "action_code": action_code,
        "chain": chain or [],
        "trigger": trigger,
        "actions": actions,
        "enabled": True,
        "created_at": _now(),
    })


def update_event(event_id: str, data: dict[str, Any]) -> dict[str, Any]:
    current = get_event(event_id)
    if not current:
        raise ValueError("Evento no encontrado.")
    current.update(data)
    return save_event(event_id, current)


def delete_event(event_id: str) -> bool:
    path = _path(event_id)
    if not path.exists():
        return False
    path.unlink()
    return True
