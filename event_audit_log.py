from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app_paths import RUNTIME_ROOT

LOG_DIR = RUNTIME_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
EVENT_LOG_PATH = LOG_DIR / "action_events.jsonl"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def log_action_event(
    *,
    event_type: str,
    phase: str,
    event_id: str,
    target_id: str | None = None,
    target_name: str | None = None,
    duration_seconds: float | None = None,
    action: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "timestamp": _now_iso(),
        "event_type": str(event_type),
        "phase": str(phase),
        "event_id": str(event_id),
        "target_id": target_id,
        "target_name": target_name,
        "duration_seconds": round(float(duration_seconds), 3) if duration_seconds is not None else None,
        "action": dict(action or {}),
        "details": dict(details or {}),
    }
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return record


def get_event_log_path() -> str:
    return str(EVENT_LOG_PATH)
