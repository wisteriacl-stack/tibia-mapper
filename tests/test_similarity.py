from PIL import Image

from battle_monitor import _similarity


def _solid(width, height, color):
    return Image.new("RGB", (width, height), color)


def test_identical_images_give_similarity_one():
    img = _solid(20, 20, (100, 120, 140))
    assert _similarity(img, img) == 1.0


def test_black_vs_white_gives_similarity_zero():
    black = _solid(10, 10, (0, 0, 0))
    white = _solid(10, 10, (255, 255, 255))
    assert _similarity(black, white) == 0.0


def test_different_sizes_give_similarity_zero():
    small = _solid(10, 10, (50, 50, 50))
    big = _solid(20, 20, (50, 50, 50))
    assert _similarity(small, big) == 0.0


def test_dark_shades_give_high_similarity_despite_being_different():
    """Caracterizacion de una debilidad conocida de esta metrica (error absoluto
    medio, no correlacion): dos oscuros distintos dan > 0.95. Documenta por que
    los umbrales de battle_similarity_threshold viven cerca de 0.975-0.99, y
    hace fallar este test si alguien cambia _similarity() sin recalibrar."""
    dark_a = _solid(10, 10, (10, 10, 10))
    dark_b = _solid(10, 10, (20, 20, 20))
    assert _similarity(dark_a, dark_b) > 0.95
