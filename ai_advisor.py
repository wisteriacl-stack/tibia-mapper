from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

OLLAMA_BASE_URL = str(os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = str(os.getenv("OLLAMA_MODEL") or "qwen2.5:3b").strip()


def _recent_log_lines(log_path: str | None, limit: int = 80) -> list[str]:
    if not log_path:
        return []
    path = Path(log_path)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max(1, int(limit)):]


def _coordinate_steps(routine: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not routine:
        return []
    return [
        step
        for step in (routine.get("steps") or [])
        if step.get("type", "coordinate") == "coordinate"
        and step.get("x") is not None
        and step.get("y") is not None
    ]


def analyze_routine_path(routine: dict[str, Any] | None) -> dict[str, Any]:
    points = _coordinate_steps(routine)
    if not points:
        return {
            "coordinate_count": 0,
            "total_distance_px": 0.0,
            "near_duplicate_pairs": 0,
            "large_jumps": 0,
            "segments": [],
        }

    total_distance = 0.0
    near_duplicates = 0
    large_jumps = 0
    distances: list[float] = []

    for previous, current in zip(points, points[1:]):
        dx = int(current["x"]) - int(previous["x"])
        dy = int(current["y"]) - int(previous["y"])
        distance = math.hypot(dx, dy)
        distances.append(distance)
        total_distance += distance
        if distance <= 8:
            near_duplicates += 1
        if distance >= 250:
            large_jumps += 1

    segments: list[dict[str, Any]] = []
    if distances:
        start = 0
        current_kind = "quiet" if distances[0] <= 12 else "move"
        for index, distance in enumerate(distances[1:], start=1):
            kind = "quiet" if distance <= 12 else "move"
            if kind != current_kind:
                segments.append({
                    "kind": current_kind,
                    "from_step": start + 1,
                    "to_step": index + 1,
                })
                start = index
                current_kind = kind
        segments.append({
            "kind": current_kind,
            "from_step": start + 1,
            "to_step": len(points),
        })

    return {
        "coordinate_count": len(points),
        "total_distance_px": round(total_distance, 1),
        "near_duplicate_pairs": near_duplicates,
        "large_jumps": large_jumps,
        "segments": segments[:30],
    }


def build_context(
    *,
    battle_state: dict[str, Any] | None,
    health_state: dict[str, Any] | None,
    recording_state: dict[str, Any] | None,
    routine: dict[str, Any] | None,
    log_path: str | None,
) -> dict[str, Any]:
    return {
        "battle": dict(battle_state or {}),
        "health": dict(health_state or {}),
        "recording": dict(recording_state or {}),
        "routine": {
            "id": (routine or {}).get("id"),
            "name": (routine or {}).get("name"),
            "version": (routine or {}).get("version"),
            "step_count": len((routine or {}).get("steps") or []),
            "path_analysis": analyze_routine_path(routine),
        } if routine else None,
        "recent_logs": _recent_log_lines(log_path),
    }


def _heuristic_advice(context: dict[str, Any], *, provider_error: str | None = None) -> dict[str, Any]:
    findings: list[str] = []
    severity = "ok"

    if provider_error:
        findings.append(f"IA local no disponible: {provider_error}")
        severity = "warning"

    health = dict(context.get("health") or {})
    hp = health.get("last_value")
    if health.get("last_error"):
        findings.append(f"Health Monitor reporta error: {health['last_error']}")
        severity = "warning"
    elif hp is not None:
        findings.append(f"Última lectura de vida: {hp} HP.")
        if health.get("below_threshold"):
            severity = "warning"

    battle = dict(context.get("battle") or {})
    if battle.get("action_locked"):
        findings.append(
            f"Battle está esperando cierre de la acción actual; fase={battle.get('phase', 'desconocida')}."
        )
    if battle.get("last_timeout_forced"):
        findings.append("La última liberación Battle ocurrió por timeout.")
        severity = "warning"

    routine = context.get("routine") or {}
    path = routine.get("path_analysis") or {}
    if path.get("coordinate_count"):
        findings.append(
            f"Rutina {routine.get('name') or routine.get('id')}: "
            f"{path.get('coordinate_count')} coordenadas, "
            f"{path.get('near_duplicate_pairs')} pares casi repetidos y "
            f"{path.get('large_jumps')} saltos grandes."
        )

    error_logs = [
        line for line in (context.get("recent_logs") or [])
        if " ERROR " in line.upper() or "ERROR |" in line.upper() or "TRACEBACK" in line.upper()
    ]
    if error_logs:
        findings.append(f"Hay {len(error_logs)} entradas de error entre los logs recientes.")
        severity = "warning"

    if not findings:
        findings.append("No se detectaron anomalías claras con las reglas locales actuales.")

    recommendation = (
        "Revisar primero los hallazgos marcados antes de cambiar la automatización o los umbrales."
        if severity == "warning"
        else "El estado observado se ve estable; continuar recopilando telemetría antes de automatizar nuevas decisiones."
    )

    return {
        "provider": "local-fallback",
        "model": None,
        "status": severity,
        "summary": "Análisis local del estado actual, logs y rutina.",
        "findings": findings,
        "recommendation": recommendation,
        "confidence": 0.72 if severity == "warning" else 0.66,
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def ollama_status() -> dict[str, Any]:
    request = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "available": False,
            "provider": "ollama",
            "base_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "model_installed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    models = [str(item.get("name") or "") for item in (payload.get("models") or []) if isinstance(item, dict)]
    installed = any(name == OLLAMA_MODEL or name.startswith(f"{OLLAMA_MODEL}:") for name in models)
    return {
        "available": True,
        "provider": "ollama",
        "base_url": OLLAMA_BASE_URL,
        "model": OLLAMA_MODEL,
        "model_installed": installed,
        "installed_models": models[:30],
        "error": None if installed else f"Modelo {OLLAMA_MODEL} no está descargado.",
    }


def _ollama_advice(context: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    prompt = (
        "Analiza la telemetría de una aplicación de escritorio. "
        "Tu función es solamente observar, explicar errores y recomendar qué revisar; no propongas ni ejecutes entradas automáticas. "
        "Responde EXCLUSIVAMENTE como JSON válido con estas claves: "
        "status ('ok', 'info' o 'warning'), summary (string), findings (array de strings), "
        "recommendation (string), confidence (número entre 0 y 1).\n\n"
        "Contexto:\n" + json.dumps(context, ensure_ascii=False)
    )
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.15,
            "num_ctx": 8192,
        },
        "messages": [
            {
                "role": "system",
                "content": "Eres un analista técnico conciso. Responde en español y solamente con JSON válido.",
            },
            {"role": "user", "content": prompt},
        ],
    }, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(exc)
        return None, f"Ollama HTTP {exc.code}: {detail}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    content = str(((raw.get("message") or {}).get("content")) or "")
    result = _extract_json_object(content)
    if not result:
        return None, "Ollama respondió, pero no entregó JSON válido."

    try:
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "provider": "ollama",
        "model": OLLAMA_MODEL,
        "status": str(result.get("status") or "info"),
        "summary": str(result.get("summary") or "Análisis local completado."),
        "findings": [str(item) for item in (result.get("findings") or [])][:20],
        "recommendation": str(result.get("recommendation") or ""),
        "confidence": confidence,
    }, None


def analyze_context(context: dict[str, Any]) -> dict[str, Any]:
    result, provider_error = _ollama_advice(context)
    result = result or _heuristic_advice(context, provider_error=provider_error)
    result["provider_error"] = provider_error
    result["context_snapshot"] = {
        "hp": (context.get("health") or {}).get("last_value"),
        "battle_phase": (context.get("battle") or {}).get("phase"),
        "recording_active": bool((context.get("recording") or {}).get("active")),
        "routine_id": (context.get("routine") or {}).get("id"),
        "recent_log_count": len(context.get("recent_logs") or []),
    }
    return result
