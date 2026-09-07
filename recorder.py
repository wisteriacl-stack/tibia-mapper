from __future__ import annotations

import ctypes
import sys
import threading
import time

from checkpoint_store import capture_checkpoint
from routine_store import append_step, get_routine, set_step_validation_image
from session_log import log_event
from settings_store import get_settings

VK_F9 = 0x78
VK_F11 = 0x7A
VK_F12 = 0x7B
POLL_SECONDS = 0.05
TIMED_SAMPLE_SECONDS = 2.0

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_recording_id: str | None = None
_last_position: dict | None = None
_last_checkpoint: dict | None = None
_timed_active = False
_timed_last_sample_at: float | None = None
_timed_sample_count = 0


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _cursor_position() -> tuple[int, int]:
    point = POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
        raise OSError("No se pudo leer la posición del mouse.")
    return int(point.x), int(point.y)


def _wait_key_release(user32, virtual_key: int) -> None:
    while user32.GetAsyncKeyState(virtual_key) & 0x8000:
        if _stop_event.is_set():
            return
        time.sleep(POLL_SECONDS)


def _append_position(routine_id: str, source: str) -> dict:
    global _last_position, _timed_sample_count
    x, y = _cursor_position()
    routine = append_step(routine_id, x, y)
    step_count = len(routine.get("steps") or [])
    with _lock:
        _last_position = {
            "x": x,
            "y": y,
            "step_count": step_count,
            "source": source,
        }
        if source == "timed_2s":
            _timed_sample_count += 1
    log_event(
        f"GRABACIÓN POSICIÓN | rutina={routine_id} | paso={step_count} | "
        f"x={x} y={y} | source={source}"
    )
    return routine


def _worker(routine_id: str) -> None:
    global _last_checkpoint, _timed_active, _timed_last_sample_at
    user32 = ctypes.windll.user32
    settings = get_settings()
    region = dict(settings.get("map_validation_region") or {})
    tibia_title = str(settings.get("tibia_window_title") or "Tibia")
    output_idx = int(settings.get("dxgi_output_idx", 0))

    log_event(
        f"GRABACIÓN iniciada | rutina={routine_id} | "
        f"F12 agrega coordenada | F11 guarda validación desde OBS/DXGI output={output_idx} | "
        f"F9 activa/desactiva muestreo automático cada {TIMED_SAMPLE_SECONDS:.0f}s"
    )

    _wait_key_release(user32, VK_F9)
    _wait_key_release(user32, VK_F12)
    _wait_key_release(user32, VK_F11)

    while not _stop_event.is_set():
        if user32.GetAsyncKeyState(VK_F9) & 0x8000:
            with _lock:
                _timed_active = not _timed_active
                enabled = _timed_active
                _timed_last_sample_at = None
            log_event(
                f"GRABACIÓN MODO 2S | rutina={routine_id} | "
                f"estado={'activo' if enabled else 'detenido'} | intervalo={TIMED_SAMPLE_SECONDS:.1f}s"
            )
            _wait_key_release(user32, VK_F9)

        if user32.GetAsyncKeyState(VK_F12) & 0x8000:
            _append_position(routine_id, "manual_f12")
            _wait_key_release(user32, VK_F12)

        now = time.monotonic()
        with _lock:
            timed_active = _timed_active
            last_sample = _timed_last_sample_at
        if timed_active and (last_sample is None or now - last_sample >= TIMED_SAMPLE_SECONDS):
            try:
                _append_position(routine_id, "timed_2s")
            except Exception as exc:
                log_event(
                    f"ERROR GRABACIÓN MODO 2S | rutina={routine_id} | "
                    f"{type(exc).__name__}: {exc}"
                )
            finally:
                with _lock:
                    _timed_last_sample_at = time.monotonic()

        if user32.GetAsyncKeyState(VK_F11) & 0x8000:
            routine = get_routine(routine_id)
            steps = list((routine or {}).get("steps") or [])
            if not steps:
                log_event(f"GRABACIÓN F11 ignorado | rutina={routine_id} | todavía no hay pasos")
            else:
                step_index = len(steps) - 1
                try:
                    image_path = capture_checkpoint(
                        routine_id,
                        step_index,
                        region,
                        tibia_title=tibia_title,
                    )
                    routine = set_step_validation_image(routine_id, step_index, image_path)
                    with _lock:
                        _last_checkpoint = {
                            "step_index": step_index,
                            "step_number": step_index + 1,
                            "image": image_path,
                            "region": dict(region),
                            "source": "obs_dxgi",
                            "output_idx": output_idx,
                        }
                    log_event(
                        f"GRABACIÓN F11 OBS/DXGI | rutina={routine_id} | paso={step_index + 1} | "
                        f"checkpoint={image_path} | region={region} | output={output_idx}"
                    )
                except Exception as exc:
                    log_event(
                        f"ERROR GRABACIÓN F11 | rutina={routine_id} | paso={step_index + 1} | "
                        f"{type(exc).__name__}: {exc}"
                    )
            _wait_key_release(user32, VK_F11)

        time.sleep(POLL_SECONDS)


def start_recording(routine_id: str) -> dict:
    global _thread, _recording_id, _last_position, _last_checkpoint
    global _timed_active, _timed_last_sample_at, _timed_sample_count

    if sys.platform != "win32":
        raise RuntimeError("La grabación con F9/F11/F12 está disponible solo en Windows.")
    if not get_routine(routine_id):
        raise ValueError("Rutina no encontrada.")

    with _lock:
        if _thread is not None and _thread.is_alive():
            raise RuntimeError("Ya hay una grabación activa.")

        _stop_event.clear()
        _recording_id = routine_id
        _last_position = None
        _last_checkpoint = None
        _timed_active = False
        _timed_last_sample_at = None
        _timed_sample_count = 0
        _thread = threading.Thread(target=_worker, args=(routine_id,), daemon=True)
        _thread.start()

    return recording_status()


def stop_recording() -> dict:
    global _thread, _recording_id, _timed_active, _timed_last_sample_at
    with _lock:
        thread = _thread
        routine_id = _recording_id
        _stop_event.set()
        _timed_active = False
        _timed_last_sample_at = None

    if thread is not None and thread.is_alive():
        thread.join(timeout=1.0)

    with _lock:
        _thread = None
        _recording_id = None

    if routine_id:
        log_event(f"GRABACIÓN detenida | rutina={routine_id}")

    return recording_status()


def recording_status() -> dict:
    with _lock:
        active = _thread is not None and _thread.is_alive()
        routine_id = _recording_id if active else None
        last_position = dict(_last_position) if _last_position else None
        last_checkpoint = dict(_last_checkpoint) if _last_checkpoint else None
        timed_active = bool(_timed_active and active)
        timed_sample_count = int(_timed_sample_count)

    return {
        "active": active,
        "routine_id": routine_id,
        "last_position": last_position,
        "last_checkpoint": last_checkpoint,
        "timed_active": timed_active,
        "timed_interval_seconds": TIMED_SAMPLE_SECONDS,
        "timed_sample_count": timed_sample_count,
    }
