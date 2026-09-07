from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def runtime_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_root() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parent


RUNTIME_ROOT = runtime_root()
RESOURCE_ROOT = resource_root()

for folder in (
    "routines",
    "events",
    "checkpoints",
    "battle_targets",
    "battle_targets/images",
    "data",
    "logs",
):
    (RUNTIME_ROOT / folder).mkdir(parents=True, exist_ok=True)
