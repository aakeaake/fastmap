import pytest

from fastmap.services.geomag import MODEL_EPOCH, MODEL_VALID_UNTIL, declination, field

# NOAA's official WMM2025 test values (WMM2025_TEST_VALUES.txt, NCEI, 2025-02):
# date, height km, lat, lon -> X, Y (nT), declination (deg)
OFFICIAL = [
    (2025.0, 0.0, 80.0, 0.0, 6521.6, 145.9, 1.28),
    (2025.0, 0.0, 0.0, 120.0, 39677.8, -109.6, -0.16),
    (2025.0, 0.0, -80.0, 240.0, 6117.5, 15751.9, 68.78),
    (2025.0, 100.0, 80.0, 0.0, 6216.0, 92.4, 0.85),
    (2025.0, 100.0, 0.0, 120.0, 37688.6, -96.2, -0.15),
    (2025.0, 100.0, -80.0, 240.0, 5907.6, 14780.3, 68.21),
    (2027.5, 0.0, 80.0, 0.0, 6500.8, 294.5, 2.59),
    (2027.5, 0.0, 0.0, 120.0, 39701.6, -167.4, -0.24),
    (2027.5, 0.0, -80.0, 240.0, 6200.7, 15730.3, 68.49),
    (2027.5, 100.0, 80.0, 0.0, 6196.7, 233.8, 2.16),
    (2027.5, 100.0, 0.0, 120.0, 37711.5, -148.7, -0.23),
    (2027.5, 100.0, -80.0, 240.0, 5984.0, 14760.1, 67.93),
]


@pytest.mark.parametrize("row", OFFICIAL)
def test_official_values(row):
    year, h, lat, lon, x, y, d = row
    fx, fy = field(lat, lon, year, height_km=h)
    assert fx == pytest.approx(x, abs=0.1)
    assert fy == pytest.approx(y, abs=0.1)
    assert declination(lat, lon, year, height_km=h) == pytest.approx(d, abs=0.006)


def test_model_validity():
    assert (MODEL_EPOCH, MODEL_VALID_UNTIL) == (2025.0, 2030.0)


def test_helsinki_2026_sanity():
    assert 9 < declination(60.17, 24.94, 2026.9) < 12
