from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any

from PIL import Image, ImageEnhance, ImageFilter

from app_paths import RUNTIME_ROOT

_ENGINE = None
_ENGINE_ERROR: str | None = None
SNAPSHOT_LOG = RUNTIME_ROOT / "data" / "bestiary_snapshots.jsonl"

# En la escena OBS el tracker está ampliado. No tiene sentido agrandarlo 3x/4x
# antes de RapidOCR: eso multiplicaba brutalmente los píxeles procesados y llevaba
# cada lectura a varios segundos. El OCR completo solo necesita la parte superior
# donde aparecen las filas del tracker; una vez localizada la fila objetivo, el
# monitor usa únicamente la mini-región del contador.
BESTIARY_FAST_MAX_HEIGHT = 300


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-zA-Z0-9 ]+", " ", value).lower()
    return re.sub(r"\s+", " ", value).strip()


def _get_engine():
    global _ENGINE, _ENGINE_ERROR
    if _ENGINE is not None:
        return _ENGINE
    if _ENGINE_ERROR:
        raise RuntimeError(_ENGINE_ERROR)
    try:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
        return _ENGINE
    except Exception as exc:
        _ENGINE_ERROR = f"No se pudo iniciar RapidOCR: {exc}"
        raise RuntimeError(_ENGINE_ERROR) from exc


def _prepare(image: Image.Image, scale: int = 1) -> Image.Image:
    rgb = image.convert("RGB")
    scale = max(1, int(scale))
    if scale > 1:
        rgb = rgb.resize((rgb.width * scale, rgb.height * scale), Image.Resampling.LANCZOS)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.35)
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.45)
    return rgb.filter(ImageFilter.SHARPEN)


def _box_bounds(box: Any, scale: int) -> dict[str, float]:
    points = list(box or [])
    xs = [float(p[0]) / scale for p in points if len(p) >= 2]
    ys = [float(p[1]) / scale for p in points if len(p) >= 2]
    if not xs or not ys:
        return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0, "center_x": 0.0, "center_y": 0.0}
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    return {
        "x": round(x1, 2),
        "y": round(y1, 2),
        "width": round(x2 - x1, 2),
        "height": round(y2 - y1, 2),
        "center_x": round((x1 + x2) / 2, 2),
        "center_y": round((y1 + y2) / 2, 2),
    }


def _parse_entries(tokens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = []
    numbers = []
    for token in tokens:
        text = str(token.get("text") or "").strip()
        normalized = _normalize_text(text)
        if not normalized:
            continue
        if re.fullmatch(r"\d+", normalized):
            numbers.append(token)
            continue
        if any(ch.isalpha() for ch in normalized) and "bestiary" not in normalized and "tracker" not in normalized:
            names.append(token)

    entries: list[dict[str, Any]] = []
    used_numbers: set[int] = set()
    for name in names:
        ny = float(name.get("box", {}).get("center_y", 0.0))
        nx = float(name.get("box", {}).get("center_x", 0.0))
        candidates = []
        for idx, number in enumerate(numbers):
            if idx in used_numbers:
                continue
            by = float(number.get("box", {}).get("center_y", 0.0))
            bx = float(number.get("box", {}).get("center_x", 0.0))
            vertical = by - ny
            if -8 <= vertical <= 60:
                candidates.append((abs(vertical) + abs(bx - nx) * 0.10, idx, number))
        if not candidates:
            continue
        _, idx, number = min(candidates, key=lambda item: item[0])
        used_numbers.add(idx)
        value_text = re.sub(r"\D", "", str(number.get("text") or ""))
        if not value_text:
            continue
        entries.append({
            "name": str(name.get("text") or "").strip(),
            "normalized_name": _normalize_text(name.get("text") or ""),
            "value": int(value_text),
            "name_score": float(name.get("score") or 0.0),
            "value_score": float(number.get("score") or 0.0),
            "name_box": dict(name.get("box") or {}),
            "value_box": dict(number.get("box") or {}),
        })
    return entries


def read_bestiary(image: Image.Image, region: dict[str, Any]) -> dict[str, Any]:
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))

    ocr_height = min(height, BESTIARY_FAST_MAX_HEIGHT)
    crop = image.crop((x, y, x + width, y + ocr_height))
    scale = 1 if width >= 250 else 2

    try:
        import numpy as np

        engine = _get_engine()
        result, _ = engine(np.asarray(_prepare(crop, scale=scale)))
    except Exception as exc:
        return {
            "ok": False,
            "region": {"x": x, "y": y, "width": width, "height": ocr_height},
            "tokens": [],
            "entries": [],
            "error": str(exc),
        }

    tokens: list[dict[str, Any]] = []
    for item in result or []:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], str(item[1] or "").strip(), float(item[2] or 0.0)
        if not text:
            continue
        tokens.append({
            "text": text,
            "score": round(score, 4),
            "box": _box_bounds(box, scale),
        })

    return {
        "ok": True,
        "region": {"x": x, "y": y, "width": width, "height": ocr_height},
        "source_region_height": height,
        "ocr_scale": scale,
        "tokens": tokens,
        "values": [token["text"] for token in tokens],
        "entries": _parse_entries(tokens),
    }


def find_target_entry(snapshot: dict[str, Any] | None, target_name: str | None) -> dict[str, Any] | None:
    if not snapshot or not snapshot.get("ok"):
        return None
    wanted = _normalize_text(target_name or "")
    if not wanted:
        return None
    entries = list(snapshot.get("entries") or [])
    exact = next((e for e in entries if e.get("normalized_name") == wanted), None)
    if exact:
        return exact
    return next(
        (
            e
            for e in entries
            if wanted in str(e.get("normalized_name") or "")
            or str(e.get("normalized_name") or "") in wanted
        ),
        None,
    )


def find_target_value(snapshot: dict[str, Any] | None, target_name: str | None) -> int | None:
    entry = find_target_entry(snapshot, target_name)
    return int(entry.get("value")) if entry and entry.get("value") is not None else None


def target_value_region(
    snapshot: dict[str, Any] | None,
    target_name: str | None,
    *,
    pad_x: int = 6,
    pad_y: int = 4,
) -> dict[str, int] | None:
    entry = find_target_entry(snapshot, target_name)
    if not entry:
        return None
    box = dict(entry.get("value_box") or {})
    source_region = dict((snapshot or {}).get("region") or {})
    if not box or not source_region:
        return None
    x = int(round(float(source_region.get("x", 0)) + float(box.get("x", 0)))) - pad_x
    y = int(round(float(source_region.get("y", 0)) + float(box.get("y", 0)))) - pad_y
    width = int(round(float(box.get("width", 0)))) + pad_x * 2
    height = int(round(float(box.get("height", 0)))) + pad_y * 2
    if width < 1 or height < 1:
        return None
    return {"x": max(0, x), "y": max(0, y), "width": width, "height": height}


def read_bestiary_number(
    image: Image.Image,
    region: dict[str, Any],
    *,
    scale_override: int | None = None,
) -> dict[str, Any]:
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    crop = image.crop((x, y, x + width, y + height))

    scale = max(1, int(scale_override)) if scale_override is not None else (2 if width < 120 else 1)
    try:
        import numpy as np

        result, _ = _get_engine()(np.asarray(_prepare(crop, scale=scale)))
    except Exception as exc:
        return {
            "ok": False,
            "value": None,
            "region": {"x": x, "y": y, "width": width, "height": height},
            "ocr_scale": scale,
            "error": str(exc),
        }

    candidates: list[tuple[float, int, str]] = []
    raw_tokens: list[str] = []
    for item in result or []:
        if not item or len(item) < 3:
            continue
        text = str(item[1] or "").strip()
        if text:
            raw_tokens.append(text)
        digits = re.sub(r"\D", "", text)
        if not digits:
            continue
        candidates.append((float(item[2] or 0.0), int(digits), text))
    if not candidates:
        return {
            "ok": False,
            "value": None,
            "region": {"x": x, "y": y, "width": width, "height": height},
            "ocr_scale": scale,
            "raw_tokens": raw_tokens,
            "error": "OCR no encontró un número",
        }
    score, value, raw = max(candidates, key=lambda item: item[0])
    return {
        "ok": True,
        "value": value,
        "raw": raw,
        "score": round(score, 4),
        "ocr_scale": scale,
        "raw_tokens": raw_tokens,
        "region": {"x": x, "y": y, "width": width, "height": height},
    }


def read_health_number(
    image: Image.Image,
    region: dict[str, Any],
    *,
    scale_override: int | None = 2,
    max_value: int = 50000,
) -> dict[str, Any]:
    """Lee HP con reglas estrictas para no concatenar números ajenos al valor."""
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    crop = image.crop((x, y, x + width, y + height))
    scale = max(1, int(scale_override)) if scale_override is not None else (2 if width < 120 else 1)
    max_value = max(1, int(max_value))

    try:
        import numpy as np

        result, _ = _get_engine()(np.asarray(_prepare(crop, scale=scale)))
    except Exception as exc:
        return {
            "ok": False,
            "value": None,
            "region": {"x": x, "y": y, "width": width, "height": height},
            "ocr_scale": scale,
            "raw_tokens": [],
            "rejected_tokens": [],
            "error": str(exc),
        }

    candidates: list[tuple[float, int, str]] = []
    raw_tokens: list[str] = []
    rejected_tokens: list[dict[str, Any]] = []

    for item in result or []:
        if not item or len(item) < 3:
            continue
        text = str(item[1] or "").strip()
        score = float(item[2] or 0.0)
        if not text:
            continue
        raw_tokens.append(text)

        # HP debe venir como un único token numérico. No concatenamos grupos
        # separados porque "920 261 108" terminaría convertido en 920261108.
        if not re.fullmatch(r"\d{1,6}", text):
            rejected_tokens.append({"text": text, "score": round(score, 4), "reason": "not_single_integer"})
            continue

        value = int(text)
        if value > max_value:
            rejected_tokens.append({"text": text, "score": round(score, 4), "reason": "above_max_value"})
            continue

        candidates.append((score, value, text))

    if not candidates:
        return {
            "ok": False,
            "value": None,
            "region": {"x": x, "y": y, "width": width, "height": height},
            "ocr_scale": scale,
            "raw_tokens": raw_tokens,
            "rejected_tokens": rejected_tokens,
            "max_value": max_value,
            "error": "OCR no encontró un HP válido",
        }

    score, value, raw = max(candidates, key=lambda item: item[0])
    return {
        "ok": True,
        "value": value,
        "raw": raw,
        "score": round(score, 4),
        "ocr_scale": scale,
        "raw_tokens": raw_tokens,
        "rejected_tokens": rejected_tokens,
        "max_value": max_value,
        "region": {"x": x, "y": y, "width": width, "height": height},
    }


def persist_snapshot(snapshot: dict[str, Any], *, target_id: str | None, phase: str) -> None:
    payload = {
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "target_id": target_id,
        "phase": phase,
        "snapshot": snapshot,
    }
    SNAPSHOT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
