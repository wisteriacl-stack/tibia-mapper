from __future__ import annotations

from typing import Any
import pyautogui


def click_mouse(
    current,
    button="left",
    clicks=1,
    interval=0.0
):
    if current["x"] is None or current["y"] is None:
        return False
    pyautogui.moveTo(current["x"], current["y"], duration=0.25)
    pyautogui.click(button=button, clicks=clicks, interval=interval)
    return True

def click_atack_on_battle(      
    x=3196,y=681,
    button="left",
    clicks=1,
    interval=0.0):
    
    pyautogui.moveTo(x, y, duration=0.25)
    pyautogui.click(button=button, clicks=clicks, interval=interval)
    pyautogui.press("a")

    return {
        "ok": "ok",
    }
    


def normalize_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": int(index),
        "x": int(step.get("x", 0)),
        "y": int(step.get("y", 0)),
    }


def execute_step(step: dict[str, Any], index: int) -> dict[str, Any]:
    current = normalize_step(step, index)

    ok = click_mouse(current)

    print(
        "EJECUTANDO REGISTRO "
        f"#{current['index'] + 1} | x={current['x']} y={current['y']}"
    )

    return {
        "ok": ok,
        "step": current,
        "action": "click",
    }


# -----------------------------------------------------------------------------
# EVENTOS
# -----------------------------------------------------------------------------
# execute_event_action() solo decide qué handler corresponde a la categoría.
# La lógica particular de cada acción debe vivir en su handler específico:
#   click       -> _prepare_click
#   move_mouse  -> _prepare_move_mouse
#   write       -> _prepare_write
#   detect_text -> _prepare_detect_text
#   custom      -> _prepare_custom
#
# _base_event_result() NO ejecuta la acción. Solo construye la respuesta común.


def execute_event_action(
    event: dict[str, Any],
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lee la categoría del evento y deriva al handler correspondiente."""
    category = str(event.get("category") or "custom").strip()
    action_code = str(event.get("action_code") or "")
    current_analysis = analysis or {}

    handlers = {
        "move_mouse": _prepare_move_mouse,
        "click": _prepare_click,
        "write": _prepare_write,
        "detect_text": _prepare_detect_text,
        "custom": _prepare_custom,
    }

    handler = handlers.get(category, _prepare_custom)

    print(
        "EVENTO -> HANDLER | "
        f"id={event.get('id')} | categoria={category} | handler={handler.__name__}"
    )

    return handler(event, action_code, current_analysis)


def _base_event_result(
    event: dict[str, Any],
    category: str,
    action_code: str,
    analysis: dict[str, Any],
    *,
    ok: bool = True,
    status: str = "prepared",
    action_result: Any = None,
) -> dict[str, Any]:
    """Respuesta común de todos los handlers. No ejecuta acciones."""
    return {
        "ok": ok,
        "event_id": event.get("id"),
        "event_name": event.get("name"),
        "category": category,
        "action_code": action_code,
        "analysis": analysis,
        "status": status,
        "action_result": action_result,
    }


def _prepare_move_mouse(event, action_code, analysis):
    """Handler de categoría move_mouse.

    La lógica específica de esta categoría debe ir aquí.
    """
    # TODO: implementar la acción de esta categoría.
    action_result = {
        "prepared": True,
        "message": "Lógica move_mouse pendiente.",
    }

    return _base_event_result(
        event,
        "move_mouse",
        action_code,
        analysis,
        action_result=action_result,
    )


def _prepare_click(event, action_code, analysis):
    """Handler de categoría click.

    La lógica específica de la acción click debe ir aquí, no en
    _base_event_result().
    """
    # TODO: interpretar la configuración del evento para esta acción.
    # Ejemplo de datos disponibles:
    #   event["region"]
    #   event["action_code"]
    #   analysis
    action_result = {
        "prepared": True,
        "message": "Lógica click pendiente.",
    }

    return _base_event_result(
        event,
        "click",
        action_code,
        analysis,
        action_result=action_result,
    )


def _prepare_write(event, action_code, analysis):
    """Handler de categoría write."""
    # TODO: implementar la lógica de esta categoría.
    action_result = {
        "prepared": True,
        "message": "Lógica write pendiente.",
    }

    return _base_event_result(
        event,
        "write",
        action_code,
        analysis,
        action_result=action_result,
    )


def _prepare_detect_text(event, action_code, analysis):
    """Handler reservado para la categoría detect_text."""
    # La detección visual real ocurre en screen_event_monitor.py.
    # Aquí solo se procesa la acción asociada a esta categoría, si corresponde.
    action_result = {
        "prepared": True,
        "message": "Acción detect_text pendiente.",
    }

    return _base_event_result(
        event,
        "detect_text",
        action_code,
        analysis,
        action_result=action_result,
    )


def _prepare_custom(event, action_code, analysis):
    """Fallback para categorías personalizadas o desconocidas."""
    action_result = {
        "prepared": True,
        "message": "Lógica custom pendiente.",
    }

    return _base_event_result(
        event,
        "custom",
        action_code,
        analysis,
        action_result=action_result,
    )
