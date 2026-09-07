from __future__ import annotations
from mouse_helpers import click_atack_on_battle
from session_log import log_event


def execute_battle_action(target, settings):
    target_id = str(target.get("target_id") or "")
    name = str(target.get("name") or target_id)
    similarity = float(target.get("similarity") or 0)

    log_event(
        f"BATTLE ACTION | id={target_id} | "
        f"name={name} | similarity={similarity:.4f}"
    )

    # Aquí va la acción Battle propia.
    resultAction= click_atack_on_battle()
    result = {
        "ok": {resultAction.get('ok')},
        "target_id": target_id,
    }

    return result