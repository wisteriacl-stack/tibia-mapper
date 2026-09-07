from __future__ import annotations

import threading
import time
import uuid
from typing import Any

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_events: dict[str, threading.Event] = {}


def create_job(job_type: str) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "type": job_type,
        "status": "pending",
        "created_at": time.time(),
        "finished_at": None,
        "progress": None,
        "result": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = dict(job)
        _events[job_id] = threading.Event()
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def list_jobs() -> list[dict[str, Any]]:
    with _lock:
        return [dict(job) for job in _jobs.values()]


def update_job(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(fields)


def cancel_job(job_id: str) -> bool:
    with _lock:
        event = _events.get(job_id)
        job = _jobs.get(job_id)
        if event is None or job is None:
            return False
        if job.get("status") in ("done", "error", "cancelled"):
            return False
        event.set()
    return True


def get_cancel_event(job_id: str) -> threading.Event | None:
    with _lock:
        return _events.get(job_id)
