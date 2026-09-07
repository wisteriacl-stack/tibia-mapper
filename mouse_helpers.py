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


def click_attack_on_battle(
    x: int,
    y: int,
    *,
    press_key: str | None = "a",
    button: str = "left",
    clicks: int = 1,
) -> dict[str, Any]:
    """Click en la fila Battle detectada, en coordenadas reales de Windows.

    x/y deben venir de screen_x/screen_y del match, no de una región DXGI.
    """
    pyautogui.moveTo(int(x), int(y), duration=0.25)
    pyautogui.click(button=button, clicks=clicks)
    if press_key:
        pyautogui.press(press_key)
    return {"ok": True, "x": int(x), "y": int(y), "key": press_key}



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


def _events_action_allowed() -> tuple[bool, str | None]:
    """Guardia de seguridad para input real disparado por eventos.

    Mismo patron que battle_auto_action_enabled (T2): un flag transitorio
    apagado por defecto, mas exigir que Tibia este en primer plano. El
    subsistema de Eventos nunca se probo en produccion; no tiene sentido que
    genere clicks/teclas reales sin que el usuario lo habilite explicitamente.
    """
    from settings_store import get_settings

    settings = get_settings()
    if not bool(settings.get("events_auto_action_enabled", False)):
        return False, "auto_action_disabled"

    from capture_utils import tibia_is_foreground

    title = str(settings.get("tibia_window_title") or "Tibia")
    if not tibia_is_foreground(title):
        return False, "not_foreground"
    return True, None


def _region_center(event: dict[str, Any]) -> tuple[int, int]:
    region = event.get("region") or {}
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    return x + width // 2, y + height // 2


def _prepare_move_mouse(event, action_code, analysis):
    """Mueve el mouse al centro de event['region']."""
    allowed, reason = _events_action_allowed()
    if not allowed:
        return _base_event_result(
            event, "move_mouse", action_code, analysis, ok=False,
            action_result={"executed": False, "reason": reason},
        )

    x, y = _region_center(event)
    pyautogui.moveTo(x, y, duration=0.2)
    return _base_event_result(
        event, "move_mouse", action_code, analysis,
        action_result={"executed": True, "x": x, "y": y},
    )


def _prepare_click(event, action_code, analysis):
    """Click en el centro de event['region']."""
    allowed, reason = _events_action_allowed()
    if not allowed:
        return _base_event_result(
            event, "click", action_code, analysis, ok=False,
            action_result={"executed": False, "reason": reason},
        )

    x, y = _region_center(event)
    pyautogui.moveTo(x, y, duration=0.2)
    pyautogui.click()
    return _base_event_result(
        event, "click", action_code, analysis,
        action_result={"executed": True, "x": x, "y": y},
    )


def _prepare_write(event, action_code, analysis):
    """Escribe action_code como texto via teclado."""
    text = str(action_code or "")
    if not text:
        return _base_event_result(
            event, "write", action_code, analysis, ok=False,
            action_result={"executed": False, "reason": "sin_texto_configurado"},
        )

    allowed, reason = _events_action_allowed()
    if not allowed:
        return _base_event_result(
            event, "write", action_code, analysis, ok=False,
            action_result={"executed": False, "reason": reason},
        )

    pyautogui.typewrite(text, interval=0.02)
    return _base_event_result(
        event, "write", action_code, analysis,
        action_result={"executed": True, "text": text},
    )


def _prepare_detect_text(event, action_code, analysis):
    """La deteccion visual ya ocurrio en screen_event_monitor.analyze_event_region().

    Esta categoria es de solo deteccion: no genera input propio, solo confirma
    que la condicion se cumplio (para que encadenar a otro evento tenga sentido).
    """
    return _base_event_result(
        event, "detect_text", action_code, analysis,
        action_result={"executed": False, "detected": bool(analysis.get("detected")),
                       "message": "Categoría detect_text es de solo detección; no genera input."},
    )


def _prepare_custom(event, action_code, analysis):
    """Fallback para categorías personalizadas o desconocidas: sin accion automatica."""
    return _base_event_result(
        event, "custom", action_code, analysis,
        action_result={"executed": False,
                       "message": "Categoría 'custom' no tiene una acción automática definida."},
    )
