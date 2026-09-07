from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageChops

from battle_store import battle_target_image_path, list_battle_targets
from capture_utils import get_live_frame
from event_audit_log import log_action_event
from session_log import log_event

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except Exception:  # pragma: no cover
    _CV2_AVAILABLE = False


@dataclass
class BattleRuntimeState:
    current_target_id: str | None = None
    current_match: dict[str, Any] | None = None
    action_locked: bool = False
    queue: list[dict[str, Any]] = field(default_factory=list)
    trigger_serial: int = 0
    action_started_at: float | None = None
    action_target_name: str | None = None
    action_loot_enabled: bool = False
    loot_reference: Image.Image | None = None
    loot_similarity: float | None = None
    loot_change_streak: int = 0
    loot_completion_detected: bool = False
    last_release_reason: str | None = None
    last_timeout_forced: bool = False
    last_loot_enabled: bool = False


_runtime = BattleRuntimeState()
_scan_serial = 0
_update_lock = threading.Lock()


def _similarity(a: Image.Image, b: Image.Image) -> float:
    a = a.convert("RGB")
    b = b.convert("RGB")
    if a.size != b.size:
        return 0.0
    diff = ImageChops.difference(a, b)
    histogram = diff.histogram()
    pixels = a.size[0] * a.size[1] * 3
    if pixels <= 0:
        return 0.0
    error = sum((index % 256) * count for index, count in enumerate(histogram))
    return max(0.0, min(1.0, 1.0 - (error / (255 * pixels))))


def _best_match_bruteforce(region_image: Image.Image, template: Image.Image, scan_step: int = 2) -> dict[str, Any] | None:
    region = region_image.convert("RGB")
    target = template.convert("RGB")
    tw, th = target.size
    rw, rh = region.size
    if tw > rw or th > rh:
        return None

    best = None
    best_score = -1.0
    for y in range(0, rh - th + 1, max(1, int(scan_step))):
        for x in range(0, rw - tw + 1, max(1, int(scan_step))):
            crop = region.crop((x, y, x + tw, y + th))
            score = _similarity(crop, target)
            if score > best_score:
                best_score = score
                best = {
                    "x": x,
                    "y": y,
                    "width": tw,
                    "height": th,
                    "similarity": round(score, 4),
                }
    return best


def _best_match_cv2(region_image: Image.Image, template: Image.Image) -> dict[str, Any] | None:
    """Localiza la plantilla con correlación cruzada normalizada.

    TM_CCOEFF_NORMED resta la media de cada ventana antes de correlacionar, así
    que el score no se desplaza cuando cambia el brillo global de la escena.
    Devuelve la misma forma que _best_match_bruteforce() para no tocar a los llamadores.
    """
    region = np.asarray(region_image.convert("RGB"))
    target = np.asarray(template.convert("RGB"))
    th, tw = target.shape[:2]
    rh, rw = region.shape[:2]
    if tw > rw or th > rh:
        return None

    result = cv2.matchTemplate(region, target, cv2.TM_CCOEFF_NORMED)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    return {
        "x": int(max_loc[0]),
        "y": int(max_loc[1]),
        "width": int(tw),
        "height": int(th),
        "similarity": round(float(max_val), 4),
    }


def _best_match(region_image: Image.Image, template: Image.Image, scan_step: int = 2) -> dict[str, Any] | None:
    if _CV2_AVAILABLE:
        return _best_match_cv2(region_image, template)
    return _best_match_bruteforce(region_image, template, scan_step=scan_step)


def _crop_absolute(image: Image.Image, region: dict[str, Any]) -> Image.Image:
    x = int(region.get("x", 0))
    y = int(region.get("y", 0))
    width = max(1, int(region.get("width", 1)))
    height = max(1, int(region.get("height", 1)))
    return image.crop((x, y, x + width, y + height))


def _capture(settings: dict[str, Any]) -> tuple[str, Image.Image, float]:
    started = time.perf_counter()
    image, meta = get_live_frame(
        tibia_title=str(settings.get("tibia_window_title") or "Tibia"),
        timeout_seconds=2.0,
        target_fps=30,
    )
    return str(meta.get("source") or "dxgi_live"), image, (time.perf_counter() - started) * 1000.0


def _disabled_scan(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "screenshot": None,
        "capture_source": "disabled",
        "region": dict(settings.get("battle_event_region") or {}),
        "loot_region": dict(settings.get("loot_tracker_region") or {}),
        "threshold": float(settings.get("battle_similarity_threshold", 0.90)),
        "matches": [],
        "match_debug": [],
        "timing": None,
        "scan_mode": "disabled",
        "detection_enabled": False,
    }


def _timing_log(scan_id: int, mode: str, timing: dict[str, Any]) -> None:
    log_event(
        "BATTLE PERF | "
        f"scan={scan_id} | mode={mode} | source={timing.get('capture_source')} | "
        f"capture_ms={timing.get('capture_ms')} | ocr_ms=0.0 | "
        f"battle_match_ms={timing.get('battle_match_ms')} | "
        f"visual_compare_ms={timing.get('visual_compare_ms')} | "
        f"total_ms={timing.get('total_scan_ms')} | targets={timing.get('targets_checked')} | "
        f"matches={timing.get('matches_found')}"
    )


def _scan_idle(settings: dict[str, Any], scan_id: int, total_started: float) -> dict[str, Any]:
    battle_region = dict(settings.get("battle_event_region") or {})
    loot_region = dict(settings.get("loot_tracker_region") or {})
    threshold = float(settings.get("battle_similarity_threshold", 0.90))
    scan_step = int(settings.get("battle_scan_step", 2))

    capture_source, image, capture_ms = _capture(settings)
    battle_crop = _crop_absolute(image, battle_region)
    loot_reference = _crop_absolute(image, loot_region).copy()

    bx = int(battle_region.get("x", 0))
    by = int(battle_region.get("y", 0))
    matches: list[dict[str, Any]] = []
    match_debug: list[dict[str, Any]] = []
    targets_checked = 0

    match_started = time.perf_counter()
    for target in list_battle_targets():
        if not target.get("enabled", True):
            continue
        target_id = str(target.get("id") or "")
        path = battle_target_image_path(target_id)
        if not path:
            continue

        targets_checked += 1
        template = Image.open(path).convert("RGB")
        match = _best_match(battle_crop, template, scan_step=scan_step)
        similarity = float(match.get("similarity", 0.0)) if match else None
        accepted = bool(match and similarity is not None and similarity >= threshold)

        debug_item = {
            "target_id": target_id,
            "name": target.get("name"),
            "template_width": template.width,
            "template_height": template.height,
            "region_width": battle_crop.width,
            "region_height": battle_crop.height,
            "best_similarity": similarity,
            "threshold": threshold,
            "accepted": accepted,
            "x": match.get("x") if match else None,
            "y": match.get("y") if match else None,
        }
        match_debug.append(debug_item)
        log_event(
            "BATTLE MATCH DEBUG | "
            f"target={target_id} | template={template.width}x{template.height} | "
            f"region={battle_crop.width}x{battle_crop.height} | "
            f"backend={'cv2' if _CV2_AVAILABLE else 'bruteforce'} | "
            f"best_similarity={similarity if similarity is not None else 'None'} | "
            f"threshold={threshold:.4f} | accepted={accepted} | "
            f"x={debug_item['x']} | y={debug_item['y']}"
        )

        if not accepted:
            continue

        match.update({
            "target_id": target.get("id"),
            "name": target.get("name"),
            "priority": int(target.get("priority", 100)),
            "loot_enabled": bool(target.get("loot_enabled", False)),
            "screen_x": bx + int(match["x"]),
            "screen_y": by + int(match["y"]),
        })
        matches.append(match)

    matches.sort(key=lambda item: (int(item.get("priority", 100)), int(item.get("y", 0)), int(item.get("x", 0))))
    battle_match_ms = (time.perf_counter() - match_started) * 1000.0

    timing = {
        "scan_id": scan_id,
        "capture_source": capture_source,
        "capture_ms": round(capture_ms, 2),
        "ocr_ms": 0.0,
        "battle_match_ms": round(battle_match_ms, 2),
        "visual_compare_ms": 0.0,
        "total_scan_ms": round((time.perf_counter() - total_started) * 1000.0, 2),
        "targets_checked": targets_checked,
        "matches_found": len(matches),
    }
    _timing_log(scan_id, "idle", timing)

    return {
        "screenshot": None,
        "capture_source": capture_source,
        "region": battle_region,
        "loot_region": loot_region,
        "threshold": threshold,
        "matches": matches,
        "match_debug": match_debug,
        "timing": timing,
        "scan_mode": "idle",
        "detection_enabled": True,
        "_loot_reference": loot_reference,
    }


def _scan_tracking(settings: dict[str, Any], scan_id: int, total_started: float) -> dict[str, Any]:
    loot_region = dict(settings.get("loot_tracker_region") or {})
    threshold = float(settings.get("loot_similarity_threshold", 0.975))

    capture_source, image, capture_ms = _capture(settings)
    compare_started = time.perf_counter()
    current_loot = _crop_absolute(image, loot_region)
    similarity = None
    if _runtime.loot_reference is not None:
        similarity = _similarity(current_loot, _runtime.loot_reference)
    visual_compare_ms = (time.perf_counter() - compare_started) * 1000.0

    changed_candidate = similarity is not None and similarity < threshold

    timing = {
        "scan_id": scan_id,
        "capture_source": capture_source,
        "capture_ms": round(capture_ms, 2),
        "ocr_ms": 0.0,
        "battle_match_ms": 0.0,
        "visual_compare_ms": round(visual_compare_ms, 2),
        "total_scan_ms": round((time.perf_counter() - total_started) * 1000.0, 2),
        "targets_checked": 0,
        "matches_found": 0,
    }
    _timing_log(scan_id, "tracking_loot", timing)

    return {
        "screenshot": None,
        "capture_source": capture_source,
        "region": dict(settings.get("battle_event_region") or {}),
        "loot_region": loot_region,
        "matches": [],
        "match_debug": [],
        "loot_similarity": round(similarity, 4) if similarity is not None else None,
        "loot_similarity_threshold": threshold,
        "loot_changed_candidate": bool(changed_candidate),
        "timing": timing,
        "scan_mode": "tracking_loot",
        "detection_enabled": True,
    }


def detect_battle_targets(settings: dict[str, Any]) -> dict[str, Any]:
    global _scan_serial
    if not bool(settings.get("battle_detection_enabled", False)):
        return _disabled_scan(settings)

    _scan_serial += 1
    scan_id = _scan_serial
    total_started = time.perf_counter()
    if _runtime.action_locked and _runtime.current_target_id:
        return _scan_tracking(settings, scan_id, total_started)
    return _scan_idle(settings, scan_id, total_started)


def _release_current(
    scan: dict[str, Any],
    *,
    reason: str,
    timed_out: bool,
    auto_action_enabled: bool = False,
) -> dict[str, Any]:
    old_target = _runtime.current_target_id
    old_name = _runtime.action_target_name
    loot_enabled = bool(_runtime.action_loot_enabled)
    duration = max(0.0, time.monotonic() - _runtime.action_started_at) if _runtime.action_started_at is not None else None
    loot_similarity = _runtime.loot_similarity

    _runtime.last_release_reason = reason
    _runtime.last_timeout_forced = timed_out
    _runtime.last_loot_enabled = loot_enabled

    log_action_event(
        event_type="battle",
        phase="timeout" if timed_out else "completed",
        event_id=f"battle-{_runtime.trigger_serial}",
        target_id=old_target,
        target_name=old_name,
        duration_seconds=duration,
        action={
            "type": "battle_observation",
            "loot_enabled": loot_enabled,
            "input_executed": bool(auto_action_enabled),
        },
        details={
            "release_reason": reason,
            "timeout": timed_out,
            "trigger_serial": _runtime.trigger_serial,
            "loot_similarity": loot_similarity,
            "scan_timing": dict(scan.get("timing") or {}),
        },
    )

    _runtime.action_locked = False
    _runtime.current_target_id = None
    _runtime.current_match = None
    _runtime.queue = []
    _runtime.action_started_at = None
    _runtime.action_target_name = None
    _runtime.action_loot_enabled = False
    _runtime.loot_reference = None
    _runtime.loot_similarity = None
    _runtime.loot_change_streak = 0
    _runtime.loot_completion_detected = False

    log_event(
        "BATTLE TRANSITION | waiting_loot_change -> idle | "
        f"id={old_target} | reason={reason} | duration={round(duration, 3) if duration is not None else None}s | "
        f"loot_similarity={loot_similarity}"
    )
    return battle_runtime_status(
        scan,
        action_triggered=False,
        released=True,
        timeout_forced=timed_out,
        release_reason=reason,
        loot_requested=loot_enabled,
    )


def _clean_scan_for_response(scan: dict[str, Any]) -> dict[str, Any]:
    scan.pop("_loot_reference", None)
    return scan


def _update_battle_runtime(settings: dict[str, Any]) -> dict[str, Any]:
    global _runtime

    if not bool(settings.get("battle_detection_enabled", False)):
        if _runtime.current_target_id is not None or _runtime.action_locked or _runtime.queue:
            _runtime = BattleRuntimeState()
            log_event("BATTLE detenido | runtime limpiado")
        return battle_runtime_status(_disabled_scan(settings), action_triggered=False, released=False)

    scan = detect_battle_targets(settings)
    matches = list(scan.get("matches") or [])
    action_triggered = False
    auto_action_enabled = bool(settings.get("battle_auto_action_enabled", False))

    if _runtime.action_locked and _runtime.current_target_id:
        similarity = scan.get("loot_similarity")
        _runtime.loot_similarity = float(similarity) if similarity is not None else None

        if scan.get("loot_changed_candidate"):
            _runtime.loot_change_streak += 1
        else:
            _runtime.loot_change_streak = 0

        confirmations = max(1, int(settings.get("loot_change_confirmations", 2)))
        if _runtime.loot_change_streak >= confirmations:
            _runtime.loot_completion_detected = True
            log_event(
                "BATTLE LOOT CHANGE | "
                f"id={_runtime.current_target_id} | target={_runtime.action_target_name} | "
                f"similarity={_runtime.loot_similarity} | streak={_runtime.loot_change_streak}/{confirmations} | "
                "completion_detected=True | liberando inmediatamente"
            )
            return _release_current(
                _clean_scan_for_response(scan),
                reason="loot_changed",
                timed_out=False,
                auto_action_enabled=auto_action_enabled,
            )

        elapsed = max(0.0, time.monotonic() - _runtime.action_started_at) if _runtime.action_started_at is not None else None
        timeout_seconds = float(settings.get("battle_action_timeout_seconds", 20.0))

        log_event(
            "BATTLE STATE | "
            f"locked=True | current={_runtime.current_target_id} | mode={scan.get('scan_mode')} | "
            f"loot_similarity={_runtime.loot_similarity} | streak={_runtime.loot_change_streak}/{confirmations} | "
            f"elapsed={round(elapsed, 2) if elapsed is not None else None}"
        )

        if elapsed is not None and elapsed >= timeout_seconds:
            return _release_current(
                _clean_scan_for_response(scan),
                reason="timeout",
                timed_out=True,
                auto_action_enabled=auto_action_enabled,
            )

        return battle_runtime_status(_clean_scan_for_response(scan), action_triggered=False, released=False)

    if matches:
        first = matches[0]
        _runtime.current_target_id = str(first.get("target_id") or "")
        _runtime.current_match = first
        _runtime.action_locked = True
        _runtime.queue = matches[1:]
        _runtime.trigger_serial += 1
        _runtime.action_started_at = time.monotonic()
        _runtime.action_target_name = str(first.get("name") or first.get("target_id") or "")
        _runtime.action_loot_enabled = bool(first.get("loot_enabled", False))
        _runtime.loot_reference = scan.get("_loot_reference")
        _runtime.loot_similarity = 1.0 if _runtime.loot_reference is not None else None
        _runtime.loot_change_streak = 0
        _runtime.loot_completion_detected = False
        _runtime.last_release_reason = None
        _runtime.last_timeout_forced = False
        _runtime.last_loot_enabled = False
        action_triggered = True

        log_action_event(
            event_type="battle",
            phase="triggered",
            event_id=f"battle-{_runtime.trigger_serial}",
            target_id=_runtime.current_target_id,
            target_name=_runtime.action_target_name,
            action={
                "type": "battle_observation",
                "loot_enabled": _runtime.action_loot_enabled,
                "input_executed": False,
            },
            details={
                "trigger_serial": _runtime.trigger_serial,
                "similarity": first.get("similarity"),
                "priority": first.get("priority"),
                "screen_x": first.get("screen_x"),
                "screen_y": first.get("screen_y"),
                "capture_source": scan.get("capture_source"),
                "loot_region": scan.get("loot_region"),
                "scan_timing": dict(scan.get("timing") or {}),
            },
        )

        log_event(
            "BATTLE TRANSITION | idle -> waiting_loot_change | "
            f"id={_runtime.current_target_id} | target={_runtime.action_target_name} | "
            f"start_similarity={first.get('similarity')} | serial={_runtime.trigger_serial} | "
            f"loot_region={scan.get('loot_region')}"
        )
    else:
        _runtime.queue = []
        log_event("BATTLE IDLE | sin referencias detectadas")

    return battle_runtime_status(_clean_scan_for_response(scan), action_triggered=action_triggered, released=False)


def update_battle_runtime(settings: dict[str, Any]) -> dict[str, Any]:
    if not _update_lock.acquire(blocking=False):
        state = battle_runtime_status()
        state["busy"] = True
        log_event("BATTLE SCAN SKIP | ya existe un análisis en curso")
        return state
    try:
        return _update_battle_runtime(settings)
    finally:
        _update_lock.release()


def battle_runtime_status(
    scan: dict[str, Any] | None = None,
    action_triggered: bool = False,
    released: bool = False,
    timeout_forced: bool = False,
    release_reason: str | None = None,
    loot_requested: bool = False,
) -> dict[str, Any]:
    phase = "waiting_loot_change" if _runtime.action_locked else "idle"

    elapsed = None
    if _runtime.action_started_at is not None:
        elapsed = round(max(0.0, time.monotonic() - _runtime.action_started_at), 2)

    return {
        "current_target_id": _runtime.current_target_id,
        "current_match": _runtime.current_match,
        "action_locked": _runtime.action_locked,
        "phase": phase,
        "queue": list(_runtime.queue),
        "scan": scan,
        "pending_target": _runtime.current_match,
        "action_triggered": bool(action_triggered),
        "released": bool(released),
        "trigger_serial": _runtime.trigger_serial,
        "action_elapsed_seconds": elapsed,
        "loot_similarity": _runtime.loot_similarity,
        "loot_change_streak": _runtime.loot_change_streak,
        "loot_completion_detected": bool(_runtime.loot_completion_detected),
        "release_reason": release_reason or _runtime.last_release_reason,
        "timeout_forced": bool(timeout_forced or _runtime.last_timeout_forced),
        "manual_escape_required": False,
        "loot_enabled": bool(_runtime.action_loot_enabled),
        "loot_requested": bool(loot_requested),
        "last_loot_enabled": bool(_runtime.last_loot_enabled),
        "busy": False,
    }


def reset_battle_runtime() -> dict[str, Any]:
    global _runtime
    _runtime = BattleRuntimeState()
    log_event("BATTLE STATE RESET")
    return battle_runtime_status()