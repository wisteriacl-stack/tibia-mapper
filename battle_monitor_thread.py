from __future__ import annotations

import threading
import time
from typing import Any

from battle_action_executor import execute_battle_action
from battle_monitor import update_battle_runtime, battle_runtime_status
from session_log import log_event

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last_state: dict[str, Any] = {}
_last_error: str | None = None
_cycle_count = 0


def _worker() -> None:
    global _last_state, _last_error, _cycle_count
    while not _stop_event.is_set():
        started = time.monotonic()
        try:
            from settings_store import get_settings
            settings = get_settings()
            if bool(settings.get("battle_detection_enabled", False)):
                state = update_battle_runtime(settings)
                pending = state.get("pending_target")
                if state.get("action_triggered") and pending:
                    state["action_result"] = execute_battle_action(pending, settings)
                with _lock:
                    _last_state = state
                    _last_error = None
                    _cycle_count += 1
            interval = max(0.1, float(settings.get("battle_poll_seconds", 1.0)))
        except Exception as exc:
            with _lock:
                _last_error = f"{type(exc).__name__}: {exc}"
            log_event(f"BATTLE MONITOR ERROR | {_last_error}")
            interval = 1.0

        elapsed = time.monotonic() - started
        _stop_event.wait(max(0.05, interval - elapsed))


def start_battle_monitor() -> dict[str, Any]:
    global _thread
    with _lock:
        already_running = _thread is not None and _thread.is_alive()
        if not already_running:
            _stop_event.clear()
            _thread = threading.Thread(target=_worker, name="battle-monitor", daemon=True)
            _thread.start()
    if not already_running:
        log_event("BATTLE MONITOR iniciado | bucle en backend")
    return battle_monitor_status()


def stop_battle_monitor() -> dict[str, Any]:
    global _thread
    with _lock:
        thread = _thread
        _stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    with _lock:
        _thread = None
    log_event("BATTLE MONITOR detenido")
    return battle_monitor_status()


def battle_monitor_status() -> dict[str, Any]:
    with _lock:
        active = _thread is not None and _thread.is_alive()
        return {
            "active": active,
            "last_state": dict(_last_state),
            "last_error": _last_error,
            "cycle_count": _cycle_count,
            "runtime": battle_runtime_status(),
        }
