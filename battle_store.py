from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image
from app_paths import RUNTIME_ROOT

BASE_DIR = RUNTIME_ROOT
BATTLE_DIR = BASE_DIR / "battle_targets"
IMAGES_DIR = BATTLE_DIR / "images"
INDEX_PATH = BATTLE_DIR / "targets.json"
BATTLE_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value or "target"


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item or {})
    result["enabled"] = bool(result.get("enabled", True))
    result["loot_enabled"] = bool(result.get("loot_enabled", False))
    result["battle_action"] = dict(result.get("battle_action") or {"type": "single"})
    return result


def _load_index() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    try:
        return [_normalize_item(item) for item in list(json.loads(INDEX_PATH.read_text(encoding="utf-8")) or [])]
    except Exception:
        return []


def _save_index(items: list[dict[str, Any]]) -> None:
    INDEX_PATH.write_text(
        json.dumps([_normalize_item(item) for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def list_battle_targets() -> list[dict[str, Any]]:
    items = _load_index()
    items.sort(key=lambda item: (int(item.get("priority", 100)), str(item.get("name") or "").casefold()))
    return items


def get_battle_target(target_id: str) -> dict[str, Any] | None:
    target_id = _slug(target_id)
    for item in _load_index():
        if item.get("id") == target_id:
            return item
    return None


def _crop_image(image: Image.Image, region: dict[str, Any], label: str = "región") -> tuple[Image.Image, dict[str, int]]:
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = int(region.get("width", 0))
    height = int(region.get("height", 0))
    if width < 1 or height < 1:
        raise ValueError(f"La {label} debe tener ancho y alto mayores a cero.")
    if x < 0 or y < 0 or x + width > image.width or y + height > image.height:
        raise ValueError(
            f"La {label} queda fuera de la imagen. "
            f"Imagen={image.width}x{image.height}, región=({x},{y},{width},{height})."
        )
    return image.crop((x, y, x + width, y + height)), {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
    }


def _capture_dxgi_battle_reference() -> tuple[Image.Image, dict[str, int], dict[str, Any]]:
    """Captura una sola fila del Battle desde la escena OBS PanelDatos.

    battle_event_region es el área grande donde el detector busca objetivos.
    battle_reference_region es únicamente la primera fila visible y se usa para
    crear una plantilla pequeña que luego puede encontrarse en cualquier fila.
    """
    from capture_utils import get_live_frame
    from settings_store import get_settings

    settings = get_settings()
    region = dict(settings.get("battle_reference_region") or settings.get("battle_event_region") or {})
    image, meta = get_live_frame(
        tibia_title=str(settings.get("tibia_window_title") or "Tibia"),
        timeout_seconds=2.0,
        target_fps=30,
    )
    cropped, applied = _crop_image(image, region, "Región de referencia Battle DXGI")
    return cropped, applied, dict(meta or {})


def save_battle_target_image(
    name: str,
    priority: int,
    uploaded_file=None,
    crop_region: dict[str, Any] | None = None,
    action_uploaded_file=None,
    action_crop_region: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Guarda una referencia visual de Battle.

    Flujo preferido: si no se sube archivo, captura directamente una sola fila
    desde battle_reference_region. El detector busca esa plantilla dentro de la
    región grande battle_event_region.
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("El nombre es obligatorio.")

    target_id = _slug(clean_name)
    items = _load_index()
    if any(item.get("id") == target_id for item in items):
        raise ValueError("Ya existe una referencia con ese nombre.")

    capture_meta: dict[str, Any] | None = None
    if uploaded_file:
        image = Image.open(uploaded_file.stream).convert("RGB")
        applied_crop = None
        if crop_region is not None:
            image, applied_crop = _crop_image(image, crop_region, "Región de eventos battle")
        reference_source = "upload"
    else:
        image, applied_crop, capture_meta = _capture_dxgi_battle_reference()
        image = image.convert("RGB")
        reference_source = "dxgi_live"

    path = IMAGES_DIR / f"{target_id}.png"
    image.save(path, format="PNG")

    item: dict[str, Any] = {
        "id": target_id,
        "name": clean_name,
        "priority": max(1, int(priority)),
        "image": path.relative_to(BASE_DIR).as_posix(),
        "image_width": image.width,
        "image_height": image.height,
        "enabled": True,
        "loot_enabled": False,
        "battle_action": {"type": "single"},
        "reference_source": reference_source,
        "created_at": _now(),
        "updated_at": _now(),
    }
    if applied_crop is not None:
        item["crop"] = applied_crop
        item["auto_cropped_from_battle_region"] = True
    if capture_meta:
        item["capture_source"] = str(capture_meta.get("source") or "dxgi_live")
        item["capture_width"] = int(capture_meta.get("width") or 0)
        item["capture_height"] = int(capture_meta.get("height") or 0)

    # Compatibilidad con referencias antiguas de doble imagen.
    if action_uploaded_file:
        action_image = Image.open(action_uploaded_file.stream).convert("RGB")
        action_applied_crop = None
        if action_crop_region is not None:
            action_image, action_applied_crop = _crop_image(
                action_image,
                action_crop_region,
                "Región de acción Battle en ejecución",
            )
        action_path = IMAGES_DIR / f"{target_id}--action-running.png"
        action_image.save(action_path, format="PNG")
        item["action_image"] = action_path.relative_to(BASE_DIR).as_posix()
        item["action_image_width"] = action_image.width
        item["action_image_height"] = action_image.height
        if action_applied_crop is not None:
            item["action_crop"] = action_applied_crop
            item["auto_cropped_from_action_region"] = True

    items.append(item)
    _save_index(items)
    return _normalize_item(item)


def crop_battle_target_image(target_id: str, x: int, y: int, width: int, height: int) -> dict[str, Any]:
    target_id = _slug(target_id)
    items = _load_index()
    target = next((item for item in items if item.get("id") == target_id), None)
    if not target:
        raise ValueError("Referencia battle no encontrada.")

    path = BASE_DIR / str(target.get("image") or "")
    if not path.exists():
        raise ValueError("Imagen battle no encontrada.")

    image = Image.open(path).convert("RGB")
    cropped, crop = _crop_image(
        image,
        {"x": x, "y": y, "width": width, "height": height},
        "recorte",
    )
    cropped.save(path, format="PNG")

    target["updated_at"] = _now()
    target["crop"] = crop
    target["image_width"] = cropped.width
    target["image_height"] = cropped.height
    _save_index(items)
    return _normalize_item(target)


def update_battle_target(target_id: str, data: dict[str, Any]) -> dict[str, Any]:
    target_id = _slug(target_id)
    items = _load_index()
    for item in items:
        if item.get("id") != target_id:
            continue
        if "name" in data:
            item["name"] = str(data.get("name") or item.get("name") or target_id).strip()
        if "priority" in data:
            item["priority"] = max(1, int(data.get("priority", item.get("priority", 100))))
        if "enabled" in data:
            item["enabled"] = bool(data.get("enabled"))
        if "loot_enabled" in data:
            item["loot_enabled"] = bool(data.get("loot_enabled"))
        item["battle_action"] = {"type": "single"}
        item["updated_at"] = _now()
        _save_index(items)
        return _normalize_item(item)
    raise ValueError("Referencia battle no encontrada.")


def delete_battle_target(target_id: str) -> bool:
    target_id = _slug(target_id)
    items = _load_index()
    keep, removed = [], None
    for item in items:
        if item.get("id") == target_id:
            removed = item
        else:
            keep.append(item)
    if not removed:
        return False
    _save_index(keep)
    for key in ("image", "action_image"):
        image_path = BASE_DIR / str(removed.get(key) or "")
        try:
            if image_path.exists():
                image_path.unlink()
        except OSError:
            pass
    return True


def battle_target_image_path(target_id: str) -> Path | None:
    target = get_battle_target(target_id)
    if not target:
        return None
    path = BASE_DIR / str(target.get("image") or "")
    return path if path.exists() else None


def battle_target_action_image_path(target_id: str) -> Path | None:
    target = get_battle_target(target_id)
    if not target:
        return None
    path = BASE_DIR / str(target.get("action_image") or "")
    return path if path.exists() else None
