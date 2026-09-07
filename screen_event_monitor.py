from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Any

from PIL import ImageGrab

from event_store import get_event, list_events
from mouse_helpers import execute_event_action
from session_log import log_event

TIBIA_TITLE_TEXT = "Tibia"
EVENT_SCAN_SECONDS = 2.0
EVENT_FINISH_POLL_SECONDS = 0.5
VK_F12 = 0x7B


class EventRuntimeState:
    def __init__(self, event_busy: threading.Event | None = None):
        self.event_busy = event_busy or threading.Event()
        self._lock = threading.Lock()
        self._active_ids: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}

    def is_active(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._active_ids

    def start(self, event_id: str, thread: threading.Thread) -> bool:
        with self._lock:
            if event_id in self._active_ids:
                return False
            self._active_ids.add(event_id)
            self._threads[event_id] = thread
            self.event_busy.set()
            return True

    def finish(self, event_id: str) -> None:
        with self._lock:
            self._active_ids.discard(event_id)
            self._threads.pop(event_id, None)
            if not self._active_ids:
                self.event_busy.clear()

    def active_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._active_ids)

    def active_count(self) -> int:
        with self._lock:
            return len(self._active_ids)

    def wait_workers(self, timeout_per_worker: float = 1.0) -> None:
        with self._lock:
            workers = list(self._threads.values())
        for worker in workers:
            worker.join(timeout=timeout_per_worker)


def get_foreground_title() -> str:
    if sys.platform != "win32":
        return ""
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value or ""


def tibia_is_foreground() -> bool:
    return TIBIA_TITLE_TEXT.casefold() in get_foreground_title().casefold()


def _f12_is_down() -> bool:
    if sys.platform != "win32":
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_F12) & 0x8000)


def wait_for_tibia_foreground(poll_seconds: float = 0.25) -> None:
    log_event("RUTINA: esperando que Tibia esté en primer plano")
    while not tibia_is_foreground():
        time.sleep(poll_seconds)
    log_event("RUTINA: Tibia detectado en primer plano")


def wait_for_tibia_and_f12(poll_seconds: float = 0.05) -> None:
    log_event("RUTINA: pon Tibia en primer plano y presiona F12 para comenzar")

    while _f12_is_down():
        time.sleep(poll_seconds)

    while True:
        if tibia_is_foreground() and _f12_is_down():
            log_event("RUTINA: F12 detectado con Tibia en primer plano")
            while _f12_is_down():
                time.sleep(poll_seconds)
            return
        time.sleep(poll_seconds)


def capture_event_region(event: dict[str, Any]):
    region = event.get("region") or {}
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    return ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)


def analyze_event_region(event: dict[str, Any], image) -> dict[str, Any]:
    """Punto de extensión del detector. Por ahora no marca eventos como detectados."""
    grayscale = image.convert("L")
    histogram = grayscale.histogram()
    total = sum(histogram) or 1
    mean_brightness = sum(value * count for value, count in enumerate(histogram)) / total

    return {
        "detected": False,
        "event_id": event.get("id"),
        "mean_brightness": round(mean_brightness, 2),
        "size": image.size,
        "reason": "Detector todavía no definido para este evento.",
    }


def wait_for_event_to_finish(
    event: dict[str, Any],
    stop_event: threading.Event | None = None,
    poll_seconds: float = EVENT_FINISH_POLL_SECONDS,
) -> dict[str, Any]:
    event_id = str(event.get("id") or "")
    log_event(f"EVENTO esperando finalización | id={event_id}")

    while True:
        if stop_event and stop_event.is_set():
            return {"finished": False, "stopped": True}

        if not tibia_is_foreground():
            time.sleep(poll_seconds)
            continue

        image = capture_event_region(event)
        analysis = analyze_event_region(event, image)
        if not analysis.get("detected"):
            log_event(f"EVENTO terminado | id={event_id}")
            return {"finished": True, "analysis": analysis}

        time.sleep(poll_seconds)


def execute_chain_actions(
    event: dict[str, Any],
    analysis: dict[str, Any],
    seen: set[str] | None = None,
    allowed_categories: set[str] | None = None,
) -> list[dict[str, Any]]:
    seen = set(seen or set())
    event_id = str(event.get("id") or "")
    if not event_id or event_id in seen:
        return []
    seen.add(event_id)

    category = str(event.get("category") or "")
    allowed = set(allowed_categories or set())
    results: list[dict[str, Any]] = []

    if not allowed or category in allowed:
        results.append({
            "event_id": event_id,
            "action": execute_event_action(event, analysis),
        })
    else:
        results.append({
            "event_id": event_id,
            "skipped": True,
            "reason": f"Categoría '{category}' no habilitada para esta ejecución.",
        })

    for next_id in event.get("chain") or []:
        chained = get_event(next_id)
        if chained and chained.get("enabled", True):
            chained_analysis = {
                "detected": True,
                "event_id": chained.get("id"),
                "triggered_by_chain": event_id,
            }
            results.extend(execute_chain_actions(
                chained,
                chained_analysis,
                seen,
                allowed_categories=allowed,
            ))

    return results


def event_worker(
    event: dict[str, Any],
    first_analysis: dict[str, Any],
    runtime: EventRuntimeState,
    stop_event: threading.Event,
    allowed_categories: set[str] | None = None,
) -> None:
    event_id = str(event.get("id") or "")
    try:
        log_event(
            f"EVENTO worker iniciado | id={event_id} | categoria={event.get('category')} | "
            f"activos={runtime.active_count()}"
        )

        first_analysis["actions"] = execute_chain_actions(
            event,
            first_analysis,
            allowed_categories=allowed_categories,
        )
        first_analysis["completion"] = wait_for_event_to_finish(
            event,
            stop_event=stop_event,
        )
    except Exception as exc:
        log_event(f"ERROR EVENTO worker {event_id}: {type(exc).__name__}: {exc}")
    finally:
        runtime.finish(event_id)
        log_event(
            f"EVENTO worker finalizado | id={event_id} | "
            f"eventos_activos={runtime.active_count()} | activos={runtime.active_ids()}"
        )


def try_start_event_worker(
    event: dict[str, Any],
    runtime: EventRuntimeState,
    stop_event: threading.Event,
    allowed_categories: set[str] | None = None,
) -> dict[str, Any]:
    event_id = str(event.get("id") or "")
    if not event_id:
        return {"detected": False, "reason": "Evento sin id."}

    if runtime.is_active(event_id):
        return {
            "detected": True,
            "event_id": event_id,
            "already_active": True,
        }

    image = capture_event_region(event)
    analysis = analyze_event_region(event, image)
    if not analysis.get("detected"):
        return analysis

    worker = threading.Thread(
        target=event_worker,
        args=(event, analysis, runtime, stop_event, allowed_categories),
        daemon=True,
        name=f"event-worker-{event_id}",
    )

    if not runtime.start(event_id, worker):
        return {
            "detected": True,
            "event_id": event_id,
            "already_active": True,
        }

    log_event(
        f"EVENTO detectado | id={event_id} | categoria={event.get('category')} | "
        f"worker independiente | activos={runtime.active_ids()}"
    )
    worker.start()

    return {
        **analysis,
        "worker_started": True,
        "active_events": runtime.active_ids(),
    }


def scan_events_once(
    runtime: EventRuntimeState,
    stop_event: threading.Event,
    enabled_event_ids: list[str] | None = None,
    allowed_categories: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not tibia_is_foreground():
        return []

    enabled_ids = {str(x) for x in (enabled_event_ids or []) if str(x)}
    allowed = set(allowed_categories or set())
    results = []
    for event in list_events():
        if stop_event.is_set():
            break
        event_id = str(event.get("id") or "")
        category = str(event.get("category") or "")
        if not event.get("enabled", True):
            continue
        if enabled_ids and event_id not in enabled_ids:
            continue
        if allowed and category not in allowed:
            continue
        try:
            results.append(try_start_event_worker(
                event,
                runtime,
                stop_event,
                allowed_categories=allowed,
            ))
        except Exception as exc:
            log_event(f"ERROR EVENTO {event.get('id')}: {type(exc).__name__}: {exc}")
    return results


def monitor_events(
    stop_event: threading.Event,
    event_busy: threading.Event | None = None,
    interval_seconds: float = EVENT_SCAN_SECONDS,
    enabled_event_ids: list[str] | None = None,
    allowed_categories: set[str] | None = None,
) -> None:
    runtime = EventRuntimeState(event_busy)
    log_event(
        f"MONITOR EVENTOS iniciado | intervalo={interval_seconds:.1f}s | "
        f"seleccionados={enabled_event_ids or []} | permitidos={sorted(allowed_categories or set())}"
    )

    try:
        while not stop_event.is_set():
            scan_events_once(
                runtime=runtime,
                stop_event=stop_event,
                enabled_event_ids=enabled_event_ids,
                allowed_categories=allowed_categories,
            )
            stop_event.wait(interval_seconds)
    finally:
        stop_event.set()
        runtime.wait_workers(timeout_per_worker=1.0)
        if runtime.active_count() == 0:
            runtime.event_busy.clear()
        log_event(
            f"MONITOR EVENTOS detenido | eventos_activos_restantes={runtime.active_ids()}"
        )
