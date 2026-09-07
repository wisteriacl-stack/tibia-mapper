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
