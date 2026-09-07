from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from app_paths import RUNTIME_ROOT
from capture_utils import get_live_frame

BASE_DIR = RUNTIME_ROOT
CHECKPOINTS_DIR = BASE_DIR / "checkpoints"
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)


def _routine_dir(routine_id: str) -> Path:
    path = CHECKPOINTS_DIR / routine_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def checkpoint_path(routine_id: str, step_index: int) -> Path:
    return _routine_dir(routine_id) / f"step_{int(step_index) + 1:04d}.png"


def checkpoint_relative_path(routine_id: str, step_index: int) -> str:
    return checkpoint_path(routine_id, step_index).relative_to(BASE_DIR).as_posix()


def crop_region_from_image(image: Image.Image, region: dict[str, Any]) -> Image.Image:
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    image = image.convert("RGB")
    right = x + width
    bottom = y + height
    if x < 0 or y < 0 or right > image.width or bottom > image.height:
        raise ValueError(
            "La región de validación queda fuera de la captura OBS/DXGI. "
            f"Captura={image.width}x{image.height}, región=({x},{y},{width},{height})."
        )
    return image.crop((x, y, right, bottom))


def capture_checkpoint(
    routine_id: str,
    step_index: int,
    region: dict[str, Any],
    tibia_title: str = "Tibia",
    timeout_seconds: float = 10.0,
) -> str:
    image, _meta = get_live_frame(
        tibia_title=tibia_title,
        timeout_seconds=timeout_seconds,
        target_fps=30,
    )
    path = checkpoint_path(routine_id, step_index)
    crop_region_from_image(image, region).save(path, format="PNG")
    return path.relative_to(BASE_DIR).as_posix()


def save_uploaded_checkpoint(routine_id: str, step_index: int, uploaded_file) -> str:
    if not uploaded_file:
        raise ValueError("No se recibió una imagen.")
    path = checkpoint_path(routine_id, step_index)
    Image.open(uploaded_file.stream).convert("RGB").save(path, format="PNG")
    return path.relative_to(BASE_DIR).as_posix()


def get_checkpoint_file(routine_id: str, step_index: int) -> Path | None:
    path = checkpoint_path(routine_id, step_index)
    return path if path.exists() else None


def compare_images(current: Image.Image, reference: Image.Image) -> float:
    reference = reference.convert("RGB")
    current = current.convert("RGB")
    if current.size != reference.size:
        current = current.resize(reference.size)
    diff = ImageChops.difference(current, reference)
    histogram = diff.histogram()
    pixels = reference.size[0] * reference.size[1] * 3
    if pixels <= 0:
        return 0.0
    absolute_error = sum((index % 256) * count for index, count in enumerate(histogram))
    similarity = 1.0 - (absolute_error / (255 * pixels))
    return max(0.0, min(1.0, similarity))


def compare_checkpoint(
    routine_id: str,
    step_index: int,
    region: dict[str, Any],
    threshold: float,
    tibia_title: str = "Tibia",
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    path = get_checkpoint_file(routine_id, step_index)
    if not path:
        return {"ok": False, "match": False, "reason": "checkpoint_missing", "similarity": 0.0}

    image, meta = get_live_frame(
        tibia_title=tibia_title,
        timeout_seconds=timeout_seconds,
        target_fps=30,
    )
    current = crop_region_from_image(image, region)
    reference = Image.open(path)
    similarity = compare_images(current, reference)
    return {
        "ok": True,
        "match": similarity >= float(threshold),
        "similarity": round(similarity, 4),
        "threshold": float(threshold),
        "checkpoint": path.relative_to(BASE_DIR).as_posix(),
        "capture_source": str(meta.get("source") or "dxgi_live"),
        "output_idx": meta.get("output_idx"),
    }
