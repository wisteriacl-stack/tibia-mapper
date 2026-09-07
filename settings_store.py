from __future__ import annotations

import json
from typing import Any

from app_paths import RUNTIME_ROOT
from atomic_json import write_json_atomic

SETTINGS_PATH = RUNTIME_ROOT / "settings.json"

# Estado transitorio: siempre parte apagado al iniciar el proceso.
# No se persiste en settings.json para evitar que una sesión anterior
# reactive la detección Battle al volver a abrir la aplicación.
_battle_detection_enabled = False

# Igual que _battle_detection_enabled: transitorio y apagado por defecto.
# Un flag que genera clicks reales no debe reactivarse solo porque el
# proceso se reinició con un settings.json de una sesión anterior.
_battle_auto_action_enabled = False

DEFAULT_SETTINGS: dict[str, Any] = {
    "dxgi_output_idx": 0,
    "map_validation_region": {"x": 1752, "y": 27, "width": 107, "height": 110},
    "battle_event_region": {"x": 466, "y": 60, "width": 420, "height": 480},
    "battle_reference_region": {"x": 466, "y": 60, "width": 420, "height": 55},
    "battle_action_region": {"x": 1378, "y": 41, "width": 40, "height": 40},
    "loot_tracker_region": {"x": 940, "y": 260, "width": 360, "height": 295},
    "loot_similarity_threshold": 0.975,
    "loot_change_confirmations": 1,
    "health_value_region": {"x": 800, "y": 300, "width": 180, "height": 80},
    "health_monitor_enabled": True,
    "health_poll_seconds": 5.0,
    "health_log_threshold": 60,
    "health_ocr_max_value": 50000,
    "validation_similarity_threshold": 0.90,
    "validation_timeout_seconds": 5.0,
    "validation_poll_seconds": 0.5,
    "validation_failure_continues": False,
    "step_delay_seconds": 2.0,
    "battle_similarity_threshold": 0.90,
    "battle_poll_seconds": 1.0,
    "battle_scan_step": 2,
    # Loot debería liberar antes; 5s queda solo como fallback de seguridad.
    "battle_action_timeout_seconds": 5.0,
    "nvidia_capture_timeout_seconds": 8.0,
    "tibia_window_title": "Tibia",
    "record_step_key": "F12",
    "record_checkpoint_key": "F11",
}


def _normalize_region(value: dict[str, Any] | None, default_key: str) -> dict[str, int]:
    region = dict(value or {})
    default = DEFAULT_SETTINGS[default_key]
    return {
        "x": int(region.get("x", default["x"])),
        "y": int(region.get("y", default["y"])),
        "width": max(1, int(region.get("width", default["width"]))),
        "height": max(1, int(region.get("height", default["height"]))),
    }


def _normalize_settings(data: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(data or {})
    return {
        "dxgi_output_idx": max(0, int(data.get("dxgi_output_idx", DEFAULT_SETTINGS["dxgi_output_idx"]))),
        "map_validation_region": _normalize_region(data.get("map_validation_region"), "map_validation_region"),
        "battle_event_region": _normalize_region(data.get("battle_event_region"), "battle_event_region"),
        "battle_reference_region": _normalize_region(data.get("battle_reference_region"), "battle_reference_region"),
        "battle_action_region": _normalize_region(data.get("battle_action_region"), "battle_action_region"),
        "loot_tracker_region": _normalize_region(data.get("loot_tracker_region"), "loot_tracker_region"),
        "health_value_region": _normalize_region(data.get("health_value_region"), "health_value_region"),
        "loot_similarity_threshold": min(1.0, max(0.0, float(data.get("loot_similarity_threshold", DEFAULT_SETTINGS["loot_similarity_threshold"])))),
        "loot_change_confirmations": max(1, int(data.get("loot_change_confirmations", DEFAULT_SETTINGS["loot_change_confirmations"]))),
        "health_monitor_enabled": bool(data.get("health_monitor_enabled", DEFAULT_SETTINGS["health_monitor_enabled"])),
        "health_poll_seconds": max(1.0, float(data.get("health_poll_seconds", DEFAULT_SETTINGS["health_poll_seconds"]))),
        "health_log_threshold": max(0, int(data.get("health_log_threshold", DEFAULT_SETTINGS["health_log_threshold"]))),
        "health_ocr_max_value": max(1, int(data.get("health_ocr_max_value", DEFAULT_SETTINGS["health_ocr_max_value"]))),
        "validation_similarity_threshold": min(1.0, max(0.0, float(data.get("validation_similarity_threshold", DEFAULT_SETTINGS["validation_similarity_threshold"])))),
        "validation_timeout_seconds": max(0.5, float(data.get("validation_timeout_seconds", DEFAULT_SETTINGS["validation_timeout_seconds"]))),
        "validation_poll_seconds": max(0.05, float(data.get("validation_poll_seconds", DEFAULT_SETTINGS["validation_poll_seconds"]))),
        "validation_failure_continues": bool(data.get("validation_failure_continues", DEFAULT_SETTINGS["validation_failure_continues"])),
        "step_delay_seconds": max(0.0, float(data.get("step_delay_seconds", DEFAULT_SETTINGS["step_delay_seconds"]))),
        "battle_similarity_threshold": min(1.0, max(0.0, float(data.get("battle_similarity_threshold", DEFAULT_SETTINGS["battle_similarity_threshold"])))),
        "battle_poll_seconds": max(0.1, float(data.get("battle_poll_seconds", DEFAULT_SETTINGS["battle_poll_seconds"]))),
        "battle_scan_step": max(1, int(data.get("battle_scan_step", DEFAULT_SETTINGS["battle_scan_step"]))),
        "battle_action_timeout_seconds": max(1.0, float(data.get("battle_action_timeout_seconds", DEFAULT_SETTINGS["battle_action_timeout_seconds"]))),
        "nvidia_capture_timeout_seconds": max(1.0, float(data.get("nvidia_capture_timeout_seconds", DEFAULT_SETTINGS["nvidia_capture_timeout_seconds"]))),
        "tibia_window_title": str(data.get("tibia_window_title") or DEFAULT_SETTINGS["tibia_window_title"]).strip(),
        "record_step_key": "F12",
        "record_checkpoint_key": "F11",
    }


def _with_runtime_flags(settings: dict[str, Any]) -> dict[str, Any]:
    result = dict(settings)
    result["battle_detection_enabled"] = bool(_battle_detection_enabled)
    result["battle_auto_action_enabled"] = bool(_battle_auto_action_enabled)
    return result


def get_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw = DEFAULT_SETTINGS
    return _with_runtime_flags(_normalize_settings(raw))


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_settings(data)
    write_json_atomic(SETTINGS_PATH, normalized)
    return _with_runtime_flags(normalized)


def update_settings(data: dict[str, Any]) -> dict[str, Any]:
    global _battle_detection_enabled, _battle_auto_action_enabled

    current = get_settings()
    incoming = dict(data or {})

    if "battle_detection_enabled" in incoming:
        _battle_detection_enabled = bool(incoming.get("battle_detection_enabled"))
        if not _battle_detection_enabled:
            try:
                from battle_monitor_thread import stop_battle_monitor

                stop_battle_monitor()
            except Exception as exc:
                print(f"BATTLE MONITOR no pudo detenerse: {type(exc).__name__}: {exc}")
    if "battle_auto_action_enabled" in incoming:
        _battle_auto_action_enabled = bool(incoming.get("battle_auto_action_enabled"))

    for region_key in (
        "map_validation_region",
        "battle_event_region",
        "battle_reference_region",
        "battle_action_region",
        "loot_tracker_region",
        "health_value_region",
    ):
        if region_key in incoming:
            current[region_key] = incoming[region_key]
    for key in (
        "dxgi_output_idx",
        "loot_similarity_threshold",
        "loot_change_confirmations",
        "health_monitor_enabled",
        "health_poll_seconds",
        "health_log_threshold",
        "health_ocr_max_value",
        "validation_similarity_threshold",
        "validation_timeout_seconds",
        "validation_poll_seconds",
        "validation_failure_continues",
        "step_delay_seconds",
        "battle_similarity_threshold",
        "battle_poll_seconds",
        "battle_scan_step",
        "battle_action_timeout_seconds",
        "nvidia_capture_timeout_seconds",
        "tibia_window_title",
    ):
        if key in incoming:
            current[key] = incoming[key]
    return save_settings(current)
