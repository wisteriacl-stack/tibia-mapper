from bestiary_reader import _split_merged_current_max


def test_splits_real_current_max_case():
    """Caso real: barra "87/160" donde el OCR pierde el '/' y entrega "87160"."""
    assert _split_merged_current_max("87160", 50000) == 87


def test_returns_none_when_split_is_ambiguous():
    # "12"/"1314" (12) y "121"/"314" (121) son ambas divisiones validas
    # (actual <= maximo, 2+ digitos por lado): resultado ambiguo, se descarta
    # en vez de adivinar cual es la correcta.
    assert _split_merged_current_max("121314", 50000) is None


def test_returns_none_when_right_side_smaller_than_left():
    # "160" seguido de "87" invertiria max < actual: no es un HP valido.
    assert _split_merged_current_max("16087", 50000) is None


def test_returns_none_for_single_digit_sides():
    # Un HP real casi nunca se muestra como un solo digito de un lado.
    assert _split_merged_current_max("99", 50000) is None


def test_rejects_split_exceeding_max_value():
    assert _split_merged_current_max("999999", 100) is None


def test_leading_zero_sides_are_rejected():
    # "100200": los cortes que dejarian un cero a la izquierda de un lado
    # ("10"/"0200", "1002"/"00") se descartan; solo "100"/"200" es valida.
    assert _split_merged_current_max("100200", 50000) == 100
