from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image

from app_paths import RUNTIME_ROOT

MAP_REPO_ROOT = RUNTIME_ROOT / "data" / "tibia-map-data"
MAP_DATA_ROOT = MAP_REPO_ROOT / "data"
BOUNDS_PATH = MAP_DATA_ROOT / "bounds.json"
MARKERS_PATH = MAP_DATA_ROOT / "markers.json"


def _floor_id(z: int) -> str:
    return f"{int(z):02d}"


def _floor_map_path(z: int) -> Path:
    return MAP_DATA_ROOT / f"floor-{_floor_id(z)}-map.png"


def _floor_pathfinding_path(z: int) -> Path:
    return MAP_DATA_ROOT / f"floor-{_floor_id(z)}-pathfinding.png"


def map_data_status() -> dict[str, Any]:
    installed = BOUNDS_PATH.exists() and MARKERS_PATH.exists()
    return {
        "installed": installed,
        "repo_root": str(MAP_REPO_ROOT),
        "data_root": str(MAP_DATA_ROOT),
        "bounds_present": BOUNDS_PATH.exists(),
        "markers_present": MARKERS_PATH.exists(),
        "update_command": r".\scripts\update_tibiamaps.ps1",
        "source_repo": "https://github.com/tibiamaps/tibia-map-data.git",
    }


def _load_bounds() -> dict[str, Any]:
    if not BOUNDS_PATH.exists():
        raise FileNotFoundError(
            f"No existe {BOUNDS_PATH}. Ejecuta .\\scripts\\update_tibiamaps.ps1 para descargar TibiaMaps."
        )
    return json.loads(BOUNDS_PATH.read_text(encoding="utf-8"))


def _load_markers() -> list[dict[str, Any]]:
    if not MARKERS_PATH.exists():
        return []
    value = json.loads(MARKERS_PATH.read_text(encoding="utf-8"))
    return value if isinstance(value, list) else []


def _pixel_for_position(x: int, y: int, bounds: dict[str, Any]) -> tuple[int, int]:
    x_min = int(bounds["xMin"])
    y_min = int(bounds["yMin"])
    width = int(bounds["width"])
    height = int(bounds["height"])
    px = int(x) - x_min
    py = int(y) - y_min
    if px < 0 or py < 0 or px >= width or py >= height:
        raise ValueError(
            f"Posición fuera de los límites locales: x={x}, y={y}; "
            f"rango x={x_min}..{x_min + width - 1}, y={y_min}..{y_min + height - 1}."
        )
    return px, py


def _rgb_at(path: Path, px: int, py: int) -> tuple[int, int, int] | None:
    if not path.exists():
        return None
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        if px < 0 or py < 0 or px >= rgb.width or py >= rgb.height:
            return None
        value = rgb.getpixel((px, py))
    return int(value[0]), int(value[1]), int(value[2])


def _pathfinding_info(rgb: tuple[int, int, int] | None) -> dict[str, Any] | None:
    if rgb is None:
        return None
    if rgb == (255, 255, 0):
        return {
            "rgb": list(rgb),
            "hex": "#FFFF00",
            "state": "non_walkable",
            "walkable": False,
            "friction": None,
        }
    if rgb == (255, 0, 255):
        return {
            "rgb": list(rgb),
            "hex": "#FF00FF",
            "state": "unexplored",
            "walkable": None,
            "friction": None,
        }
    friction = rgb[0] if rgb[0] == rgb[1] == rgb[2] else None
    return {
        "rgb": list(rgb),
        "hex": f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}",
        "state": "walkable",
        "walkable": True,
        "friction": friction,
    }


def nearby_markers(x: int, y: int, z: int, radius: float = 30.0, limit: int = 20) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for marker in _load_markers():
        try:
            if int(marker.get("z")) != int(z):
                continue
            mx = int(marker.get("x"))
            my = int(marker.get("y"))
        except (TypeError, ValueError):
            continue
        distance = math.hypot(mx - int(x), my - int(y))
        if distance > float(radius):
            continue
        candidates.append({
            "x": mx,
            "y": my,
            "z": int(z),
            "icon": str(marker.get("icon") or ""),
            "description": str(marker.get("description") or ""),
            "distance_tiles": round(distance, 2),
        })
    candidates.sort(key=lambda item: item["distance_tiles"])
    return candidates[: max(1, int(limit))]


def get_position_info(x: int, y: int, z: int, *, marker_radius: float = 30.0) -> dict[str, Any]:
    bounds = _load_bounds()
    z = int(z)
    z_min = int(bounds.get("zMin", 0))
    z_max = int(bounds.get("zMax", 15))
    if z < z_min or z > z_max:
        raise ValueError(f"Piso fuera de límites: z={z}; rango={z_min}..{z_max}.")

    px, py = _pixel_for_position(int(x), int(y), bounds)
    map_path = _floor_map_path(z)
    pathfinding_path = _floor_pathfinding_path(z)
    map_rgb = _rgb_at(map_path, px, py)
    pathfinding_rgb = _rgb_at(pathfinding_path, px, py)

    return {
        "source": "local-tibiamaps-cache",
        "position": {"x": int(x), "y": int(y), "z": z},
        "floor_id": _floor_id(z),
        "pixel": {"x": px, "y": py},
        "bounds": {
            "x_min": int(bounds["xMin"]),
            "y_min": int(bounds["yMin"]),
            "width": int(bounds["width"]),
            "height": int(bounds["height"]),
            "z_min": z_min,
            "z_max": z_max,
        },
        "map_pixel": {
            "rgb": list(map_rgb) if map_rgb is not None else None,
            "hex": f"#{map_rgb[0]:02X}{map_rgb[1]:02X}{map_rgb[2]:02X}" if map_rgb is not None else None,
            "file": str(map_path),
        },
        "pathfinding": _pathfinding_info(pathfinding_rgb),
        "pathfinding_file": str(pathfinding_path),
        "nearby_markers": nearby_markers(int(x), int(y), z, radius=marker_radius),
        "viewer_url": f"https://tibiamaps.io/map#{int(x)},{int(y)},{z}:2",
    }
