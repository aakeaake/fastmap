import pytest

from fastmap.vector.colors import parse_color


def _approx(value, expected):
    assert value == pytest.approx(expected, abs=0.01)


def test_hsla():
    _approx(parse_color("hsla(200, 80%, 90%, 0.7)"), (0.82, 0.93, 0.98, 0.7))


def test_hex6():
    _approx(parse_color("#c8c4c5"), (200 / 255, 196 / 255, 197 / 255, 1.0))


def test_hex3():
    _approx(parse_color("#fff"), (1.0, 1.0, 1.0, 1.0))


def test_rgba():
    _approx(parse_color("rgba(252, 179, 110, 1)"), (252 / 255, 179 / 255, 110 / 255, 1.0))


def test_rgb_and_hsl():
    _approx(parse_color("rgb(255, 255, 255)"), (1.0, 1.0, 1.0, 1.0))
    _approx(parse_color("hsl(0, 0%, 25%)"), (0.25, 0.25, 0.25, 1.0))


def test_names():
    _approx(parse_color("white"), (1.0, 1.0, 1.0, 1.0))
    _approx(parse_color("black"), (0.0, 0.0, 0.0, 1.0))
    _approx(parse_color("Red"), (1.0, 0.0, 0.0, 1.0))


def test_invalid():
    with pytest.raises(ValueError):
        parse_color("not-a-colour")
