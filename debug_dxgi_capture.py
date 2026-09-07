from __future__ import annotations

from datetime import datetime

from app_paths import RUNTIME_ROOT
from capture_utils import get_live_frame, wait_for_tibia_f10
from settings_store import get_settings


def _crop(image, region: dict):
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    return image.crop((x, y, x + width, y + height))


def main() -> None:
    settings = get_settings()
    tibia_title = str(settings.get("tibia_window_title") or "Tibia")
    battle_region = dict(settings.get("battle_event_region") or {})

    print("DXGI DEBUG")
    print("1) Cambia a Tibia")
    print("2) Presiona F10")
    print(f"Region Battle: {battle_region}")

    wait_for_tibia_f10(tibia_title, timeout_seconds=30.0)
    image, meta = get_live_frame(
        tibia_title=tibia_title,
        timeout_seconds=2.0,
        target_fps=30,
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    debug_dir = RUNTIME_ROOT / "logs" / "dxgi_debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    full_path = debug_dir / f"dxgi_full_{stamp}.png"
    battle_path = debug_dir / f"dxgi_battle_{stamp}.png"

    image.save(full_path)
    battle_crop = _crop(image, battle_region)
    battle_crop.save(battle_path)

    print()
    print("Captura guardada.")
    print(f"Fuente       : {meta.get('source')}")
    print(f"Frame        : {image.width}x{image.height}")
    print(f"Acquire ms   : {meta.get('acquire_ms')}")
    print(f"Full         : {full_path}")
    print(f"Battle crop  : {battle_path}")
    print(f"Crop size    : {battle_crop.width}x{battle_crop.height}")
    print()
    print("Abre ambas imagenes y confirma si Tibia se ve normalmente o negro/desplazado.")


if __name__ == "__main__":
    main()
