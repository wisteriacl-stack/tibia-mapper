from ai_advisor import analyze_routine_path


def test_none_routine_returns_zeros_without_raising():
    result = analyze_routine_path(None)
    assert result["coordinate_count"] == 0
    assert result["total_distance_px"] == 0.0
    assert result["near_duplicate_pairs"] == 0
    assert result["large_jumps"] == 0
    assert result["segments"] == []


def test_empty_routine_returns_zeros():
    result = analyze_routine_path({"steps": []})
    assert result["coordinate_count"] == 0


def test_near_duplicate_points_counted_at_threshold():
    routine = {
        "steps": [
            {"type": "coordinate", "x": 100, "y": 100},
            {"type": "coordinate", "x": 103, "y": 104},  # distancia 5 <= 8
        ]
    }
    result = analyze_routine_path(routine)
    assert result["near_duplicate_pairs"] == 1
    assert result["large_jumps"] == 0


def test_large_jump_counted_at_threshold():
    routine = {
        "steps": [
            {"type": "coordinate", "x": 0, "y": 0},
            {"type": "coordinate", "x": 300, "y": 0},  # distancia 300 >= 250
        ]
    }
    result = analyze_routine_path(routine)
    assert result["large_jumps"] == 1
    assert result["near_duplicate_pairs"] == 0


def test_segments_split_quiet_and_move():
    routine = {
        "steps": [
            {"type": "coordinate", "x": 0, "y": 0},
            {"type": "coordinate", "x": 5, "y": 0},      # distancia 5 -> quiet
            {"type": "coordinate", "x": 200, "y": 0},    # distancia 195 -> move
        ]
    }
    result = analyze_routine_path(routine)
    kinds = [segment["kind"] for segment in result["segments"]]
    assert "quiet" in kinds
    assert "move" in kinds


def test_action_steps_are_ignored():
    routine = {
        "steps": [
            {"type": "coordinate", "x": 0, "y": 0},
            {"type": "action", "action": {"type": "write", "text": "hola"}},
            {"type": "coordinate", "x": 10, "y": 0},
        ]
    }
    result = analyze_routine_path(routine)
    assert result["coordinate_count"] == 2
