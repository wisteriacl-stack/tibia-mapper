from __future__ import annotations

import os
import time
from pathlib import Path

DEFAULT_MAX_SESSION_AGE_DAYS = 14
DEFAULT_MAX_JSONL_BYTES = 10 * 1024 * 1024


def purge_old_sessions(log_dir: Path, *, pattern: str = "session_*.log", max_age_days: float = DEFAULT_MAX_SESSION_AGE_DAYS) -> int:
    """Borra archivos de sesion mas antiguos que max_age_days. Devuelve cuantos borro."""
    log_dir = Path(log_dir)
    if not log_dir.exists():
        return 0
    cutoff = time.time() - max(0.0, float(max_age_days)) * 86400.0
    removed = 0
    for path in log_dir.glob(pattern):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def rotate_if_large(path: Path, *, max_bytes: int = DEFAULT_MAX_JSONL_BYTES, keep: int = 2) -> None:
    """Rota path -> path.1 -> path.2 ... cuando supera max_bytes.

    Se llama antes de cada escritura para que el append que sigue nunca
    empuje el archivo mucho mas alla del limite.
    """
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
    except OSError:
        return

    for index in range(keep, 0, -1):
        src = path.with_name(f"{path.name}.{index}")
        if not src.exists():
            continue
        if index == keep:
            try:
                src.unlink()
            except OSError:
                pass
            continue
        dst = path.with_name(f"{path.name}.{index + 1}")
        try:
            os.replace(src, dst)
        except OSError:
            pass

    try:
        os.replace(path, path.with_name(f"{path.name}.1"))
    except OSError:
        pass
