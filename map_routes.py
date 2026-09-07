from __future__ import annotations

from flask import jsonify, request

from tibia_map_service import get_position_info, map_data_status


def register_map_routes(app) -> None:
    @app.get("/api/map/status")
    def map_status():
        return jsonify({"ok": True, "map": map_data_status()})

    @app.get("/api/map/position")
    def map_position():
        try:
            x = int(request.args.get("x"))
            y = int(request.args.get("y"))
            z = int(request.args.get("z"))
            radius = float(request.args.get("marker_radius", 30.0))
            info = get_position_info(x, y, z, marker_radius=max(0.0, min(500.0, radius)))
        except (TypeError, ValueError, FileNotFoundError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc), "map": map_data_status()}), 400
        return jsonify({"ok": True, "map": info})
