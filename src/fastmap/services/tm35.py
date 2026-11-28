"""ETRS-TM35FIN (EPSG:3067) to latitude/longitude, and grid convergence.

Inverse Transverse Mercator by the Krüger series (as in the JHS 154
recommendation), on the GRS80 ellipsoid: far more accurate than the
magnetic north calculation needs.
"""

from math import asinh, atan, atanh, cos, cosh, degrees, radians, sin, sinh, sqrt, tan, tanh

_A = 6378137.0
_F = 1 / 298.257222101
_K0 = 0.9996
_LON0 = 27.0
_FALSE_EASTING = 500000.0

_N = _F / (2 - _F)
_E = sqrt(_F * (2 - _F))
_A1 = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)
_BETA = (
    _N / 2 - 2 * _N**2 / 3 + 37 * _N**3 / 96 - _N**4 / 360,
    _N**2 / 48 + _N**3 / 15 - 437 * _N**4 / 1440,
    17 * _N**3 / 480 - 37 * _N**4 / 840,
    4397 * _N**4 / 161280,
)


def to_lat_lon(x: float, y: float) -> tuple[float, float]:
    """EPSG:3067 metres -> (latitude, longitude) in degrees."""
    xi1 = y / (_K0 * _A1)
    eta1 = (x - _FALSE_EASTING) / (_K0 * _A1)
    xi, eta = xi1, eta1
    for j, b in enumerate(_BETA, start=1):
        xi -= b * sin(2 * j * xi1) * cosh(2 * j * eta1)
        eta -= b * cos(2 * j * xi1) * sinh(2 * j * eta1)
    beta = atan(sin(xi) / sqrt(sinh(eta) ** 2 + cos(xi) ** 2))  # conformal latitude
    lon = _LON0 + degrees(atan(sinh(eta) / cos(xi)))
    q1 = asinh(tan(beta))
    q = q1
    for _ in range(10):  # isometric -> geodetic latitude, converges in a few steps
        q = q1 + _E * atanh(_E * tanh(q))
    return degrees(atan(sinh(q))), lon


def convergence(x: float, y: float) -> float:
    """Grid convergence in degrees: the angle from true north to grid north,
    positive when grid north lies east of true north (east of 27°E)."""
    lat, lon = to_lat_lon(x, y)
    return degrees(atan(tan(radians(lon - _LON0)) * sin(radians(lat))))
