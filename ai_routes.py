from __future__ import annotations

from flask import jsonify, request

from ai_advisor import analyze_context, build_context, ollama_status
from battle_monitor import battle_runtime_status
from health_monitor import health_monitor_status
from recorder import recording_status
from routine_store import get_routine
from session_log import get_log_path, log_event
from tibia_map_service import get_position_info, map_data_status


def _optional_map_context(payload):
    position = payload.get("position")
    if not isinstance(position, dict):
        return None, None
    try:
        x = int(position.get("x"))
        y = int(position.get("y"))
        z = int(position.get("z"))
        return get_position_info(x, y, z), None
    except (TypeError, ValueError, FileNotFoundError, OSError) as exc:
        return None, str(exc)


def _health_context_for_ai() -> dict:
    health = dict(health_monitor_status())
    # Mantener last_value en el monitor sirve para diagnóstico, pero una lectura
    # vieja no debe presentarse a la IA como HP actual si el último OCR falló.
    if not bool(health.get("last_read_valid")):
        health["last_value"] = None
        health["below_threshold"] = False
    return health


def register_ai_routes(app) -> None:
    @app.post("/api/ai/analyze")
    def ai_analyze():
        payload = request.get_json(silent=True) or {}
        routine_id = str(payload.get("routine_id") or "").strip()
        routine = get_routine(routine_id) if routine_id else None
        map_context, map_error = _optional_map_context(payload)

        context = build_context(
            battle_state=battle_runtime_status(),
            health_state=_health_context_for_ai(),
            recording_state=recording_status(),
            routine=routine,
            log_path=get_log_path(),
        )
        if map_context is not None:
            context["map"] = map_context
        elif map_error:
            context["map"] = {"error": map_error, "status": map_data_status()}

        analysis = analyze_context(context)
        analysis["map_context"] = map_context
        analysis["map_error"] = map_error
        log_event(
            "AI ADVISOR | "
            f"provider={analysis.get('provider')} | model={analysis.get('model')} | "
            f"status={analysis.get('status')} | routine={routine_id or '-'} | "
            f"map={'yes' if map_context else 'no'} | "
            f"confidence={analysis.get('confidence')} | provider_error={analysis.get('provider_error')}"
        )
        return jsonify({"ok": True, "analysis": analysis})

    @app.get("/api/ai/status")
    def ai_status():
        return jsonify({
            "ok": True,
            "provider": ollama_status(),
            "map": map_data_status(),
            "health": health_monitor_status(),
            "battle": battle_runtime_status(),
            "recording": recording_status(),
        })
