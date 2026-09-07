from tibia_map_service import _pathfinding_info


def test_yellow_is_non_walkable():
    info = _pathfinding_info((255, 255, 0))
    assert info["state"] == "non_walkable"
    assert info["walkable"] is False


def test_magenta_is_unexplored():
    info = _pathfinding_info((255, 0, 255))
    assert info["state"] == "unexplored"
    assert info["walkable"] is None


def test_gray_is_walkable_with_friction():
    info = _pathfinding_info((128, 128, 128))
    assert info["state"] == "walkable"
    assert info["walkable"] is True
    assert info["friction"] == 128


def test_none_input_returns_none():
    assert _pathfinding_info(None) is None


def test_non_gray_walkable_has_no_friction():
    info = _pathfinding_info((10, 20, 30))
    assert info["state"] == "walkable"
    assert info["friction"] is None
