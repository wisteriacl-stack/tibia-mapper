import random

import pytest
from PIL import Image

import battle_monitor as bm


def _noisy(width, height, base=None, seed=0):
    rnd = random.Random(seed)
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            if base:
                r, g, b = base
                px[x, y] = (
                    min(255, max(0, r + rnd.randint(-5, 5))),
                    min(255, max(0, g + rnd.randint(-5, 5))),
                    min(255, max(0, b + rnd.randint(-5, 5))),
                )
            else:
                px[x, y] = (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))
    return img


@pytest.mark.parametrize("backend_name", ["cv2", "bruteforce"])
def test_best_match_finds_known_position(backend_name):
    if backend_name == "cv2" and not bm._CV2_AVAILABLE:
        pytest.skip("cv2 no disponible en este entorno")

    region = _noisy(200, 100, seed=1)
    patch = _noisy(30, 20, base=(180, 120, 60), seed=2)
    region.paste(patch, (50, 40))

    if backend_name == "cv2":
        match = bm._best_match_cv2(region, patch)
    else:
        match = bm._best_match_bruteforce(region, patch, scan_step=1)

    assert match is not None
    assert match["x"] == 50
    assert match["y"] == 40
    assert match["similarity"] > 0.9


def test_best_match_returns_none_when_template_bigger_than_region():
    region = _noisy(50, 50, seed=3)
    template = _noisy(80, 80, seed=4)
    assert bm._best_match_bruteforce(region, template) is None
    if bm._CV2_AVAILABLE:
        assert bm._best_match_cv2(region, template) is None


def test_cv2_and_bruteforce_agree_on_position():
    if not bm._CV2_AVAILABLE:
        pytest.skip("cv2 no disponible en este entorno")
    region = _noisy(200, 100, seed=5)
    patch = _noisy(30, 20, base=(90, 200, 40), seed=6)
    region.paste(patch, (70, 10))

    cv2_match = bm._best_match_cv2(region, patch)
    bruteforce_match = bm._best_match_bruteforce(region, patch, scan_step=1)

    assert cv2_match["x"] == bruteforce_match["x"] == 70
    assert cv2_match["y"] == bruteforce_match["y"] == 10
