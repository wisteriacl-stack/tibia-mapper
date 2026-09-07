from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class Decision:
    recommendation: str
    target_id: str | None
    target_name: str | None
    confidence: float
    reason: str
    engine: str = "hybrid_rules_v1"
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _candidate_from_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_id": str(match.get("target_id") or "") or None,
        "name": str(match.get("name") or match.get("target_id") or "") or None,
        "priority": int(match.get("priority", 100)),
        "similarity": float(match.get("similarity", 0.0)),
        "loot_enabled": bool(match.get("loot_enabled", False)),
    }


def _known_target(targets: list[dict[str, Any]], target_id: str | None) -> dict[str, Any] | None:
    if not target_id:
        return None
    for target in targets:
        if str(target.get("id") or "") == str(target_id):
            return target
    return None


def build_context(
    battle_state: dict[str, Any] | None,
    targets: list[dict[str, Any]] | None,
    telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convierte el estado de ejecución en un contexto pequeño y estable.

    El motor solo recomienda. No mueve mouse, no pulsa teclas y no ejecuta
    acciones sobre ninguna aplicación.
    """
    state = dict(battle_state or {})
    configured_targets = [dict(item) for item in (targets or []) if item.get("enabled", True)]

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in [state.get("pending_target"), *(state.get("queue") or [])]:
        if not isinstance(raw, dict):
            continue
        candidate = _candidate_from_match(raw)
        key = str(candidate.get("target_id") or candidate.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    scan = state.get("scan") or {}
    for raw in (scan.get("matches") or []):
        if not isinstance(raw, dict):
            continue
        candidate = _candidate_from_match(raw)
        key = str(candidate.get("target_id") or candidate.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)

    # En Battle el número menor representa mayor prioridad porque el monitor
    # ordena por (priority, y, x).
    candidates.sort(key=lambda item: (int(item.get("priority", 100)), -float(item.get("similarity", 0.0))))

    current_target_id = state.get("current_target_id")
    current_target = _known_target(configured_targets, current_target_id)

    return {
        "phase": str(state.get("phase") or "idle"),
        "busy": bool(state.get("busy", False)),
        "action_locked": bool(state.get("action_locked", False)),
        "current_target_id": current_target_id,
        "current_target_name": (
            (current_target or {}).get("name")
            or state.get("bestiary_target_name")
            or (state.get("current_match") or {}).get("name")
        ),
        "action_elapsed_seconds": state.get("action_elapsed_seconds"),
        "bestiary_before": state.get("bestiary_target_before"),
        "bestiary_current": state.get("bestiary_target_current"),
        "candidates": candidates,
        "telemetry": dict(telemetry or {}),
    }


def decide(
    battle_state: dict[str, Any] | None,
    targets: list[dict[str, Any]] | None,
    telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Devuelve una recomendación explicable y sin efectos secundarios.

    Esta es la primera capa del motor híbrido. Las reglas resuelven estados
    obvios y dejan una interfaz estable para incorporar un modelo local/LLM más
    adelante sin conectar su salida a ejecución automática.
    """
    context = build_context(battle_state, targets, telemetry)

    hp = context["telemetry"].get("hp_percent")
    try:
        hp_value = float(hp) if hp is not None else None
    except (TypeError, ValueError):
        hp_value = None

    if hp_value is not None and hp_value < 30.0:
        decision = Decision(
            recommendation="attention_required",
            target_id=context.get("current_target_id"),
            target_name=context.get("current_target_name"),
            confidence=0.99,
            reason=f"HP informado en {hp_value:.0f}%. Conviene priorizar revisión humana antes de cualquier otra decisión.",
        )
    elif context["busy"]:
        decision = Decision(
            recommendation="wait_for_scan",
            target_id=context.get("current_target_id"),
            target_name=context.get("current_target_name"),
            confidence=0.98,
            reason="Hay un análisis visual en curso; es mejor esperar un estado consistente.",
        )
    elif context["action_locked"] and context.get("current_target_id"):
        before = context.get("bestiary_before")
        current = context.get("bestiary_current")
        progress = ""
        if before is not None and current is not None:
            progress = f" Bestiary observado: {before} → {current}."
        decision = Decision(
            recommendation="keep_observing_current",
            target_id=str(context["current_target_id"]),
            target_name=str(context.get("current_target_name") or context["current_target_id"]),
            confidence=0.97,
            reason="Ya existe un objetivo bloqueado por el estado Battle; no conviene cambiar la recomendación hasta que el ciclo termine." + progress,
        )
    elif context["candidates"]:
        first = context["candidates"][0]
        confidence = max(0.50, min(0.99, float(first.get("similarity", 0.0))))
        decision = Decision(
            recommendation="prioritize_target",
            target_id=first.get("target_id"),
            target_name=first.get("name"),
            confidence=confidence,
            reason=(
                f"Es el candidato visual con mayor prioridad configurada ({first.get('priority', 100)}) "
                f"y similitud {float(first.get('similarity', 0.0)):.3f}."
            ),
        )
    else:
        decision = Decision(
            recommendation="no_target",
            target_id=None,
            target_name=None,
            confidence=0.95,
            reason="No hay candidatos Battle detectados en el estado actual.",
        )

    result = decision.to_dict()
    result["context"] = context
    return result
