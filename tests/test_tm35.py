from math import atan, degrees, radians, sin, tan

import pytest

from fastmap.services.tm35 import convergence, to_lat_lon

# Reference values from proj4 2.23.0 (the frontend's projection library),
# EPSG:3067 = +proj=utm +zone=35 +ellps=GRS80, 2026-11-28
REFERENCE = [
    ((385000, 6672000), (60.168666000, 24.927457713)),  # Helsinki
    ((230000, 7000000), (63.028588963, 21.659793706)),  # Vaasa
    ((642000, 6945000), (62.608357041, 29.767037505)),  # Joensuu
    ((500000, 6672000), (60.184869721, 27.0)),  # central meridian
]


@pytest.mark.parametrize(("xy", "latlon"), REFERENCE)
def test_known_points(xy, latlon):
    lat, lon = to_lat_lon(*xy)
    assert lat == pytest.approx(latlon[0], abs=1e-7)
    assert lon == pytest.approx(latlon[1], abs=1e-7)


def test_central_meridian_is_27_with_no_convergence():
    assert to_lat_lon(500000, 6672000)[1] == pytest.approx(27.0, abs=1e-9)
    assert convergence(500000, 6672000) == pytest.approx(0.0, abs=1e-9)


def _spherical(lat, lon):
    return degrees(atan(tan(radians(lon - 27)) * sin(radians(lat))))


def test_convergence_negative_west_positive_east():
    vaasa = convergence(230000, 7000000)
    joensuu = convergence(642000, 6945000)
    assert vaasa == pytest.approx(-4.76, abs=0.02)
    assert joensuu == pytest.approx(2.46, abs=0.02)
    assert vaasa == pytest.approx(_spherical(*to_lat_lon(230000, 7000000)), abs=0.01)
