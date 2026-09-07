from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def file_lock(path: Path) -> threading.Lock:
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        if key not in _LOCKS:
            _LOCKS[key] = threading.Lock()
        return _LOCKS[key]


def write_json_atomic(path: Path, data: Any, *, indent: int = 2) -> None:
    """Escribe JSON de forma atómica: tmp en el mismo directorio + os.replace.

    os.replace() es atómico dentro del mismo volumen, así que un lector nunca
    ve un archivo a medio escribir. El tmp debe estar en el mismo directorio
    para garantizar que no cruza volúmenes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=indent)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
