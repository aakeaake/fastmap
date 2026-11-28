from datetime import date
from math import isfinite

import pytest

from fastmap.services.geomag import declination
from fastmap.services.north import decimal_year, format_correction, total_correction
from fastmap.services.print_layout import TM35FIN_BOUNDS
from fastmap.services.tm35 import convergence, to_lat_lon

DAY = date(2026, 11, 28)


def test_decimal_year():
    assert decimal_year(date(2026, 1, 1)) == 2026.0
    assert decimal_year(date(2026, 7, 2)) == pytest.approx(2026.5, abs=0.003)


def test_total_is_declination_minus_convergence_at_vaasa():
    x, y = 230000, 7000000
    lat, lon = to_lat_lon(x, y)
    d = declination(lat, lon, decimal_year(DAY))
    total = total_correction(x, y, DAY)
    assert total == pytest.approx(d - convergence(x, y), abs=1e-9)
    assert total - d == pytest.approx(4.76, abs=0.02)  # the grid offset is added in the west


def test_helsinki_sanity():
    assert 10.5 < total_correction(385000, 6672000, DAY) < 13


def test_corners_are_finite():
    minx, miny, maxx, maxy = TM35FIN_BOUNDS
    for x in (minx, maxx):
        for y in (miny, maxy):
            assert isfinite(total_correction(x, y, DAY))


@pytest.mark.parametrize(
    ("deg", "text"),
    [
        (11.5, "kok. +12°"),
        (-11.5, "kok. −12°"),
        (11.49, "kok. +11°"),
        (3.2, "kok. +3°"),
        (0.4, "kok. 0°"),
        (-0.4, "kok. 0°"),
    ],
)
def test_format(deg, text):
    assert format_correction(deg) == text
