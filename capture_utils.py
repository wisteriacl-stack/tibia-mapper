from __future__ import annotations

import ctypes
import sys
import threading
import time
from pathlib import Path

import pyautogui
from PIL import Image

NVIDIA_CAPTURE_DIR = Path.home() / "Videos" / "Desktop"
NVIDIA_SCREENSHOT_HOTKEY = ("alt", "f1")
DEFAULT_TIBIA_TITLE = "Tibia"
VK_F10 = 0x79
VK_F12 = 0x7B

_LIVE_CAPTURE_LOCK = threading.Lock()
_LIVE_CAMERA = None
_LIVE_CAMERA_OUTPUT_IDX: int | None = None
_LIVE_CAPTURE_ERROR: str | None = None
_LIVE_CAPTURE_ERROR_AT: float = 0.0
_LIVE_CAPTURE_FAILURES: int = 0
_LIVE_CAPTURE_FPS = 30
_RETRY_BASE_SECONDS = 2.0

_RETRY_MAX_SECONDS = 60.0

_OBS_CAMERA_LOCK = threading.Lock()
_OBS_CAMERA = None
_OBS_CAMERA_INDEX: int | None = None


def get_capture_files():
    if not NVIDIA_CAPTURE_DIR.exists():
        return []

    files = [
        path
        for path in NVIDIA_CAPTURE_DIR.glob("*.png")
        if not path.name.lower().startswith("tibia auto screenshot")
    ]
    return sorted(files, key=lambda path: path.stat().st_mtime_ns, reverse=True)


def get_latest_capture():
    files = get_capture_files()
    return files[0] if files else None


def capture_info(path):
    if path is None:
        return None

    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }


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


def tibia_is_foreground(title_text: str = DEFAULT_TIBIA_TITLE) -> bool:
    expected = str(title_text or DEFAULT_TIBIA_TITLE).strip().casefold()
    return expected in get_foreground_title().casefold()


def wait_for_tibia_foreground(
    title_text: str = DEFAULT_TIBIA_TITLE,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.10,
) -> str:
    """Espera hasta que Tibia quede en primer plano o expire el timeout."""
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    expected = str(title_text or DEFAULT_TIBIA_TITLE).strip()

    while time.monotonic() < deadline:
        current_title = get_foreground_title()
        if expected.casefold() in current_title.casefold():
            return current_title
        time.sleep(max(0.05, float(poll_seconds)))

    current_title = get_foreground_title()
    raise TimeoutError(
        f"Tibia no quedó en primer plano dentro de {timeout_seconds:.1f}s. "
        f"Se esperaba una ventana que contenga '{expected}'. "
        f"Ventana actual: '{current_title}'."
    )


def _wait_for_key_press(vk_code: int, timeout_seconds: float = 30.0, poll_seconds: float = 0.05) -> None:
    if sys.platform != "win32":
        raise RuntimeError("La captura por hotkey está disponible solo en Windows.")
    user32 = ctypes.windll.user32
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))

    while time.monotonic() < deadline and (user32.GetAsyncKeyState(vk_code) & 0x8000):
        time.sleep(max(0.02, float(poll_seconds)))

    while time.monotonic() < deadline:
        if user32.GetAsyncKeyState(vk_code) & 0x8000:
            while user32.GetAsyncKeyState(vk_code) & 0x8000:
                time.sleep(max(0.02, float(poll_seconds)))
            return
        time.sleep(max(0.02, float(poll_seconds)))
    raise TimeoutError("No se recibió la tecla solicitada dentro del tiempo de espera.")


def wait_for_f12_position(timeout_seconds: float = 30.0) -> dict[str, int]:
    """Espera una pulsación nueva de F12 y devuelve la posición actual del cursor."""
    _wait_for_key_press(VK_F12, timeout_seconds=timeout_seconds)
    point = pyautogui.position()
    return {"x": int(point.x), "y": int(point.y)}


def wait_for_f12_region(timeout_seconds: float = 30.0) -> dict[str, int]:
    """Captura X, Y, ancho y alto mediante cuatro pulsaciones de F12."""
    p1 = wait_for_f12_position(timeout_seconds)
    p2 = wait_for_f12_position(timeout_seconds)
    p3 = wait_for_f12_position(timeout_seconds)
    p4 = wait_for_f12_position(timeout_seconds)
    x = int(p1["x"])
    y = int(p2["y"])
    width = max(1, abs(int(p3["x"]) - x))
    height = max(1, abs(int(p4["y"]) - y))
    return {"x": x, "y": y, "width": width, "height": height}


def wait_for_tibia_f10(
    title_text: str = DEFAULT_TIBIA_TITLE,
    timeout_seconds: float = 30.0,
    poll_seconds: float = 0.05,
) -> str:
    """Espera una pulsación nueva de F10 mientras Tibia está en primer plano."""
    if sys.platform != "win32":
        raise RuntimeError("La espera de F10 está disponible solo en Windows.")

    user32 = ctypes.windll.user32
    expected = str(title_text or DEFAULT_TIBIA_TITLE).strip()
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))

    while time.monotonic() < deadline and (user32.GetAsyncKeyState(VK_F10) & 0x8000):
        time.sleep(max(0.02, float(poll_seconds)))

    while time.monotonic() < deadline:
        pressed = bool(user32.GetAsyncKeyState(VK_F10) & 0x8000)
        if pressed:
            current_title = get_foreground_title()
            if expected.casefold() in current_title.casefold():
                while user32.GetAsyncKeyState(VK_F10) & 0x8000:
                    time.sleep(max(0.02, float(poll_seconds)))
                return current_title

            while user32.GetAsyncKeyState(VK_F10) & 0x8000:
                time.sleep(max(0.02, float(poll_seconds)))

        time.sleep(max(0.02, float(poll_seconds)))

    current_title = get_foreground_title()
    raise TimeoutError(
        f"No se recibió F10 con '{expected}' en primer plano dentro de {timeout_seconds:.1f}s. "
        f"Ventana actual: '{current_title}'."
    )


def _fingerprint(path: Path | None):
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _wait_file_stable(path: Path, poll_seconds: float = 0.10, checks: int = 2) -> Path:
    last_size = -1
    stable = 0
    while stable < checks:
        size = path.stat().st_size
        if size > 0 and size == last_size:
            stable += 1
        else:
            stable = 0
        last_size = size
        time.sleep(poll_seconds)
    return path


def _configured_output_idx() -> int:
    """Output DXGI usado por toda la captura pasiva.

    Se lee desde settings para que el detector pueda apuntar al monitor donde se
    proyecta la escena OBS sin cambiar cada consumidor de get_live_frame().
    """
    try:
        from settings_store import get_settings

        return max(0, int(get_settings().get("dxgi_output_idx", 0)))
    except Exception:
        return 0


def _start_live_camera(target_fps: int = _LIVE_CAPTURE_FPS, output_idx: int | None = None):
    global _LIVE_CAMERA, _LIVE_CAMERA_OUTPUT_IDX, _LIVE_CAPTURE_ERROR
    global _LIVE_CAPTURE_ERROR_AT, _LIVE_CAPTURE_FAILURES
    if sys.platform != "win32":
        raise RuntimeError("La captura continua DXGI está disponible solo en Windows.")

    selected_output = _configured_output_idx() if output_idx is None else max(0, int(output_idx))

    with _LIVE_CAPTURE_LOCK:
        if _LIVE_CAMERA is not None and _LIVE_CAMERA_OUTPUT_IDX == selected_output:
            return _LIVE_CAMERA

        if _LIVE_CAMERA is not None and _LIVE_CAMERA_OUTPUT_IDX != selected_output:
            try:
                _LIVE_CAMERA.stop()
            except Exception:
                pass
            _LIVE_CAMERA = None
            _LIVE_CAMERA_OUTPUT_IDX = None
            _LIVE_CAPTURE_ERROR = None
            _LIVE_CAPTURE_FAILURES = 0

        if _LIVE_CAPTURE_ERROR:
            wait = min(_RETRY_MAX_SECONDS, _RETRY_BASE_SECONDS * (2 ** min(_LIVE_CAPTURE_FAILURES, 5)))
            if time.monotonic() - _LIVE_CAPTURE_ERROR_AT < wait:
                raise RuntimeError(_LIVE_CAPTURE_ERROR)
            # ventana de backoff vencida: se permite reintentar abajo.

        try:
            import dxcam

            camera = dxcam.create(output_idx=selected_output, output_color="RGB")
            camera.start(target_fps=max(1, int(target_fps)), video_mode=True)
            _LIVE_CAMERA = camera
            _LIVE_CAMERA_OUTPUT_IDX = selected_output
            _LIVE_CAPTURE_ERROR = None
            _LIVE_CAPTURE_FAILURES = 0
            return camera
        except Exception as exc:
            _LIVE_CAPTURE_ERROR = (
                f"No se pudo iniciar captura continua DXGI en output {selected_output}: {exc}"
            )
            _LIVE_CAPTURE_ERROR_AT = time.monotonic()
            _LIVE_CAPTURE_FAILURES += 1
            raise RuntimeError(_LIVE_CAPTURE_ERROR) from exc


def _configured_capture_backend() -> str:
    try:
        from settings_store import get_settings

        return str(get_settings().get("capture_backend") or "dxgi").strip().lower()
    except Exception:
        return "dxgi"


def _configured_obs_camera_index() -> int:
    try:
        from settings_store import get_settings

        return max(0, int(get_settings().get("obs_camera_index", 0)))
    except Exception:
        return 0


def _start_obs_camera(index: int):
    """Abre (o reutiliza) la Cámara Virtual de OBS como fuente de video.

    Tibia bloquea la captura de pantalla convencional (DXGI Desktop Duplication
    y Windows Game Bar dan negro). OBS sí puede verlo via su fuente "Captura de
    juego" con el enganche de compatibilidad anti-cheat activado; su Cámara
    Virtual expone ese mismo contenido como un dispositivo de video estándar
    que cv2.VideoCapture puede leer, igual que una webcam.
    """
    global _OBS_CAMERA, _OBS_CAMERA_INDEX
    with _OBS_CAMERA_LOCK:
        if _OBS_CAMERA is not None and _OBS_CAMERA_INDEX == index:
            return _OBS_CAMERA
        if _OBS_CAMERA is not None:
            try:
                _OBS_CAMERA.release()
            except Exception:
                pass
            _OBS_CAMERA = None
            _OBS_CAMERA_INDEX = None

        import cv2

        camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not camera.isOpened():
            camera.release()
            raise RuntimeError(
                f"No se pudo abrir la Cámara Virtual de OBS en el índice {index}. "
                "Verifica que OBS esté corriendo y que 'Iniciar Cámara Virtual' esté activo."
            )
        # cv2/DirectShow negocia 640x480 por defecto si no se pide otra cosa.
        # Pedimos la resolucion del canvas base de OBS explicitamente para no
        # perder detalle (afecta directamente la precision del matching y OCR).
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        _OBS_CAMERA = camera
        _OBS_CAMERA_INDEX = index
        return camera


def _get_obs_camera_frame(timeout_seconds: float) -> tuple[Image.Image, dict]:
    import cv2

    index = _configured_obs_camera_index()
    camera = _start_obs_camera(index)
    started = time.perf_counter()
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))

    ok, frame = False, None
    while time.monotonic() < deadline:
        ok, frame = camera.read()
        if ok and frame is not None:
            break

    if not ok or frame is None:
        raise TimeoutError(
            f"La Cámara Virtual de OBS (índice {index}) no entregó un frame dentro del tiempo de espera."
        )

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb)
    return image, {
        "source": "obs_camera",
        "obs_camera_index": index,
        "acquire_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "width": image.width,
        "height": image.height,
        "foreground_required": False,
    }


def stop_obs_camera() -> None:
    global _OBS_CAMERA, _OBS_CAMERA_INDEX
    with _OBS_CAMERA_LOCK:
        camera = _OBS_CAMERA
        _OBS_CAMERA = None
        _OBS_CAMERA_INDEX = None
    if camera is not None:
        try:
            camera.release()
        except Exception:
            pass


def get_live_frame(
    tibia_title: str = DEFAULT_TIBIA_TITLE,
    timeout_seconds: float = 2.0,
    target_fps: int = _LIVE_CAPTURE_FPS,
    output_idx: int | None = None,
) -> tuple[Image.Image, dict]:
    """Devuelve el frame RGB más reciente desde el backend de captura configurado.

    settings.capture_backend elige entre:
    - "dxgi" (default): DXGI Desktop Duplication continua. El output se obtiene
      de settings.dxgi_output_idx salvo que se entregue uno explícitamente. Esto
      permite leer una escena OBS proyectada en un monitor específico
      manteniendo todas las regiones en coordenadas locales de ese monitor.
    - "obs_camera": lee la Cámara Virtual de OBS (settings.obs_camera_index) via
      OpenCV. Necesario cuando Tibia bloquea la captura de pantalla convencional
      pero OBS sí puede verlo con su fuente "Captura de juego".
    """
    if _configured_capture_backend() == "obs_camera":
        return _get_obs_camera_frame(timeout_seconds)

    selected_output = _configured_output_idx() if output_idx is None else max(0, int(output_idx))
    camera = _start_live_camera(target_fps=target_fps, output_idx=selected_output)
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    started = time.perf_counter()

    while time.monotonic() < deadline:
        frame = camera.get_latest_frame()
        if frame is not None:
            image = Image.fromarray(frame).convert("RGB")
            return image, {
                "source": "dxgi_live",
                "output_idx": selected_output,
                "target_fps": int(target_fps),
                "acquire_ms": round((time.perf_counter() - started) * 1000.0, 2),
                "width": image.width,
                "height": image.height,
                "foreground_required": False,
            }
        time.sleep(0.01)

    raise TimeoutError("DXGI no entregó un frame dentro del tiempo de espera.")


def stop_live_capture() -> None:
    global _LIVE_CAMERA, _LIVE_CAMERA_OUTPUT_IDX, _LIVE_CAPTURE_ERROR
    global _LIVE_CAPTURE_ERROR_AT, _LIVE_CAPTURE_FAILURES
    with _LIVE_CAPTURE_LOCK:
        camera = _LIVE_CAMERA
        _LIVE_CAMERA = None
        _LIVE_CAMERA_OUTPUT_IDX = None
        _LIVE_CAPTURE_ERROR = None
        _LIVE_CAPTURE_ERROR_AT = 0.0
        _LIVE_CAPTURE_FAILURES = 0
    if camera is not None:
        try:
            camera.stop()
        except Exception:
            pass
    stop_obs_camera()


def request_nvidia_capture(
    tibia_title: str = DEFAULT_TIBIA_TITLE,
    timeout_seconds: float = 10.0,
    poll_seconds: float = 0.10,
) -> Path:
    """Fallback legacy: espera Tibia, envía Alt+F1 y devuelve el PNG nuevo."""
    if sys.platform != "win32":
        raise RuntimeError("La captura NVIDIA Alt+F1 está disponible solo en Windows.")

    started_at = time.monotonic()
    wait_for_tibia_foreground(
        title_text=tibia_title,
        timeout_seconds=timeout_seconds,
        poll_seconds=poll_seconds,
    )

    elapsed = time.monotonic() - started_at
    remaining = max(1.0, float(timeout_seconds) - elapsed)

    before = _fingerprint(get_latest_capture())
    requested_at_ns = time.time_ns()

    pyautogui.hotkey(*NVIDIA_SCREENSHOT_HOTKEY)

    deadline = time.monotonic() + remaining
    while time.monotonic() < deadline:
        latest = get_latest_capture()
        if latest is not None:
            current = _fingerprint(latest)
            try:
                mtime_ns = latest.stat().st_mtime_ns
            except OSError:
                mtime_ns = 0

            if current != before and mtime_ns >= requested_at_ns - 2_000_000_000:
                return _wait_file_stable(latest, poll_seconds=poll_seconds)

        time.sleep(poll_seconds)

    raise TimeoutError(
        f"NVIDIA no generó una captura nueva dentro del timeout. "
        f"Directorio esperado: {NVIDIA_CAPTURE_DIR}"
    )
