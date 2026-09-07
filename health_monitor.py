from __future__ import annotations

import threading
import time
from typing import Any

from bestiary_reader import read_health_number
from capture_utils import get_live_frame
from session_log import log_event

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last_value: int | None = None
_last_below_threshold = False
_last_error: str | None = None
_last_read_at: float | None = None
_last_read_valid = False
_last_ocr_score: float | None = None
_last_raw: str | None = None
_last_raw_tokens: list[str] = []
_last_rejected_tokens: list[dict[str, Any]] = []


def _scan_once(settings: dict[str, Any]) -> None:
    global _last_value, _last_below_threshold, _last_error, _last_read_at, _last_read_valid
    global _last_ocr_score, _last_raw, _last_raw_tokens, _last_rejected_tokens

    region = dict(settings.get("health_value_region") or {})
    threshold = int(settings.get("health_log_threshold", 60))
    max_value = max(1, int(settings.get("health_ocr_max_value", 50000)))
    output_idx = max(0, int(settings.get("dxgi_output_idx", 0)))

    try:
        image, meta = get_live_frame(
            tibia_title=str(settings.get("tibia_window_title") or "Tibia"),
            timeout_seconds=2.0,
            target_fps=30,
            output_idx=output_idx,
        )
        result = read_health_number(
            image,
            region,
            scale_override=2,
            max_value=max_value,
        )
        _last_read_at = time.time()
        _last_raw_tokens = [str(item) for item in (result.get("raw_tokens") or [])]
        _last_rejected_tokens = [dict(item) for item in (result.get("rejected_tokens") or []) if isinstance(item, dict)]

        if not result.get("ok") or result.get("value") is None:
            _last_read_valid = False
            _last_ocr_score = None
            _last_raw = None
            raise RuntimeError(
                f"{result.get('error') or 'OCR no encontró la vida'} | "
                f"ocr_scale={result.get('ocr_scale')} | raw_tokens={result.get('raw_tokens')} | "
                f"rejected_tokens={result.get('rejected_tokens')} | max_value={max_value}"
            )

        value = int(result["value"])
        below = value < threshold
        _last_value = value
        _last_read_valid = True
        _last_ocr_score = float(result.get("score")) if result.get("score") is not None else None
        _last_raw = str(result.get("raw") or "") or None
        _last_error = None

        if below and not _last_below_threshold:
            log_event(
                "HEALTH ALERT | "
                f"hp={value} | threshold={threshold} | "
                f"ocr_score={result.get('score')} | raw={result.get('raw')} | "
                f"source={meta.get('source')} | output_idx={meta.get('output_idx')} | region={region}"
            )
        elif not below and _last_below_threshold:
            log_event(f"HEALTH RECOVERY | hp={value} | threshold={threshold}")

        _last_below_threshold = below
    except Exception as exc:
        _last_read_valid = False
        error = f"{type(exc).__name__}: {exc}"
        if error != _last_error:
            log_event(
                f"HEALTH MONITOR ERROR | {error} | "
                f"output_idx={output_idx} | region={region}"
            )
            _last_error = error


def _worker() -> None:
    while not _stop_event.is_set():
        started = time.monotonic()
        try:
            from settings_store import get_settings

            settings = get_settings()
            if bool(settings.get("health_monitor_enabled", True)):
                _scan_once(settings)
            interval = max(1.0, float(settings.get("health_poll_seconds", 5.0)))
        except Exception as exc:
            log_event(f"HEALTH MONITOR ERROR | {type(exc).__name__}: {exc}")
            interval = 5.0

        elapsed = time.monotonic() - started
        _stop_event.wait(max(0.1, interval - elapsed))


def start_health_monitor() -> None:
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop_event.clear()
        _thread = threading.Thread(target=_worker, name="health-monitor", daemon=True)
        _thread.start()
    log_event("HEALTH MONITOR iniciado | intervalo=5s | threshold=60 | source=obs_dxgi | ocr_scale=2")


def stop_health_monitor() -> None:
    global _thread
    with _lock:
        thread = _thread
        _stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=1.0)
    with _lock:
        _thread = None


def health_monitor_status() -> dict[str, Any]:
    with _lock:
        active = _thread is not None and _thread.is_alive()
    return {
        "active": active,
        "last_value": _last_value,
        "last_read_valid": _last_read_valid,
        "below_threshold": _last_below_threshold if _last_read_valid else False,
        "last_error": _last_error,
        "last_read_at": _last_read_at,
        "last_ocr_score": _last_ocr_score,
        "last_raw": _last_raw,
        "last_raw_tokens": list(_last_raw_tokens),
        "last_rejected_tokens": list(_last_rejected_tokens),
    }
