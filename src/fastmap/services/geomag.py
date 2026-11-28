"""Magnetic declination from the World Magnetic Model 2025 (WMM2025).

``WMM2025.COF`` is NOAA NCEI's coefficient file, unchanged (public domain):
https://www.ncei.noaa.gov/products/world-magnetic-model (WMM2025COF.zip,
fetched 2026-11-28). It is valid from 2025.0 to 2030.0; replace it (and the
test values in tests/test_geomag.py) with the next model when it is out.
"""

from __future__ import annotations

import logging
from functools import cache
from importlib.resources import files
from math import asin, atan2, cos, degrees, radians, sin, sqrt

log = logging.getLogger(__name__)

MODEL_EPOCH = 2025.0
MODEL_VALID_UNTIL = 2030.0
_MAX_DEGREE = 12
_REF_RADIUS_KM = 6371.2
_WGS84_A_KM = 6378.137
_WGS84_F = 1 / 298.257223563


@cache
def _coefficients() -> dict[tuple[int, int], tuple[float, float, float, float]]:
    """(n, m) -> (g, h, g_dot, h_dot) in nT and nT/year."""
    text = (files("fastmap.services") / "WMM2025.COF").read_text()
    coefs = {}
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) != 6:
            break  # the 9999… end lines
        n, m = int(parts[0]), int(parts[1])
        coefs[(n, m)] = tuple(float(p) for p in parts[2:])
    return coefs


@cache
def _warn_outside(year: float) -> None:
    log.warning(
        "Date %.2f is outside WMM2025 (%.1f-%.1f): magnetic north may be off",
        year,
        MODEL_EPOCH,
        MODEL_VALID_UNTIL,
    )


def field(lat: float, lon: float, year: float, height_km: float = 0.0) -> tuple[float, float]:
    """North (X) and east (Y) components of the main field in nT, at a
    geodetic latitude/longitude (degrees) and height above the WGS84 ellipsoid."""
    if not MODEL_EPOCH <= year < MODEL_VALID_UNTIL:
        _warn_outside(round(year, 2))
    phi, lam = radians(lat), radians(lon)
    # geodetic -> geocentric spherical
    e2 = _WGS84_F * (2 - _WGS84_F)
    rc = _WGS84_A_KM / sqrt(1 - e2 * sin(phi) ** 2)
    p = (rc + height_km) * cos(phi)
    z = (rc * (1 - e2) + height_km) * sin(phi)
    r = sqrt(p * p + z * z)
    phi_c = asin(z / r)

    # Schmidt semi-normalised associated Legendre functions of cos(colatitude)
    # and their derivatives with respect to colatitude
    ct, st = sin(phi_c), cos(phi_c)  # cos and sin of the colatitude
    size = _MAX_DEGREE + 1
    pnm = [[0.0] * size for _ in range(size)]
    dpnm = [[0.0] * size for _ in range(size)]
    pnm[0][0] = 1.0
    for n in range(1, size):
        for m in range(n + 1):
            if n == m:
                k = 1.0 if n == 1 else sqrt(1 - 1 / (2 * n))
                pnm[n][n] = k * st * pnm[n - 1][n - 1]
                dpnm[n][n] = k * (st * dpnm[n - 1][n - 1] + ct * pnm[n - 1][n - 1])
            else:
                a = (2 * n - 1) / sqrt(n * n - m * m)
                b = sqrt(((n - 1) ** 2 - m * m) / (n * n - m * m)) if n - 1 > m else 0.0
                p2 = pnm[n - 2][m] if n >= 2 else 0.0
                dp2 = dpnm[n - 2][m] if n >= 2 else 0.0
                pnm[n][m] = a * ct * pnm[n - 1][m] - b * p2
                dpnm[n][m] = a * (ct * dpnm[n - 1][m] - st * pnm[n - 1][m]) - b * dp2

    dt = year - MODEL_EPOCH
    coefs = _coefficients()
    x = y = zc = 0.0
    for n in range(1, size):
        ratio = (_REF_RADIUS_KM / r) ** (n + 2)
        for m in range(n + 1):
            g, h, gd, hd = coefs[(n, m)]
            g += dt * gd
            h += dt * hd
            cm, sm = cos(m * lam), sin(m * lam)
            x += ratio * (g * cm + h * sm) * dpnm[n][m]
            y += ratio * m * (g * sm - h * cm) * pnm[n][m]
            zc -= ratio * (n + 1) * (g * cm + h * sm) * pnm[n][m]
    y /= st
    # rotate from geocentric to geodetic north
    psi = phi_c - phi
    return x * cos(psi) - zc * sin(psi), y


def declination(lat: float, lon: float, year: float, height_km: float = 0.0) -> float:
    """Angle from true north to magnetic north in degrees, positive east."""
    x, y = field(lat, lon, year, height_km)
    return degrees(atan2(y, x))
