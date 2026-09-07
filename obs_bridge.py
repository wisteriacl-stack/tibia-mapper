from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from session_log import log_event

DEFAULT_OBS_PATHS = (
    r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe",
)


def _obs_settings() -> dict[str, Any]:
    from settings_store import get_settings

    return get_settings()


def _find_obs_executable(settings: dict[str, Any]) -> Path | None:
    configured = str(settings.get("obs_executable_path") or "").strip()
    candidates = ([configured] if configured else []) + list(DEFAULT_OBS_PATHS)
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _connect(settings: dict[str, Any], timeout: float = 3.0):
    import obsws_python as obsws

    return obsws.ReqClient(
        host=str(settings.get("obs_ws_host") or "localhost"),
        port=int(settings.get("obs_ws_port") or 4455),
        password=str(settings.get("obs_ws_password") or ""),
        timeout=timeout,
    )


def _is_obs_running_tasklist() -> bool:
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq obs64.exe"], text=True, timeout=5,
        )
        return "obs64.exe" in output.lower()
    except Exception:
        return False


def launch_obs_if_needed(settings: dict[str, Any] | None = None) -> bool:
    """Lanza OBS en segundo plano (minimizado) si no está corriendo.

    Devuelve True si OBS ya estaba corriendo o se lanzó, False si no se
    encontró el ejecutable.
    """
    settings = settings or _obs_settings()
    if _is_obs_running_tasklist():
        return True

    exe = _find_obs_executable(settings)
    if exe is None:
        log_event("OBS BRIDGE | no se encontró obs64.exe; configura obs_executable_path en settings")
        return False

    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    log_event(f"OBS BRIDGE | OBS lanzado desde {exe}")
    return True


def ensure_capture_ready(settings: dict[str, Any] | None = None, *, connect_retries: int = 8, retry_wait: float = 1.5) -> dict[str, Any]:
    """Se asegura de que OBS esté corriendo, conectado por websocket y con la
    Cámara Virtual activa. Pensado para llamarse una vez al arrancar la app
    (o bajo demanda desde /api/capture/obs/ensure) cuando capture_backend
    es "obs_camera".
    """
    settings = settings or _obs_settings()
    result: dict[str, Any] = {"ok": False, "obs_launched": False, "connected": False, "virtual_cam_active": False, "error": None}

    launched = launch_obs_if_needed(settings)
    result["obs_launched"] = launched
    if not launched:
        result["error"] = "obs_not_found"
        return result

    client = None
    for _ in range(max(1, connect_retries)):
        try:
            client = _connect(settings)
            break
        except Exception:
            time.sleep(retry_wait)
    if client is None:
        result["error"] = "websocket_connect_failed"
        log_event("OBS BRIDGE | no se pudo conectar a obs-websocket tras varios intentos")
        return result

    result["connected"] = True
    try:
        status = client.get_virtual_cam_status()
        if not status.output_active:
            client.start_virtual_cam()
            log_event("OBS BRIDGE | Cámara Virtual iniciada")
        result["virtual_cam_active"] = True
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        log_event(f"OBS BRIDGE ERROR | {result['error']}")

    return result
