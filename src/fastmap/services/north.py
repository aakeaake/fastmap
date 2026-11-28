"""Total correction ("kokonaiskorjaus", "kok."): the angle from the map's grid
north (TM35FIN) to magnetic north, for compass use and magnetic north lines.

total = declination (true -> magnetic north, WMM2025) - grid convergence
(true -> grid north), in degrees, positive east (clockwise).
"""

from __future__ import annotations

from datetime import date
from math import floor

from fastmap.services.geomag import declination
from fastmap.services.tm35 import convergence, to_lat_lon


def decimal_year(d: date) -> float:
    """``date`` as a decimal year: 1 January is ``year.0``."""
    start = date(d.year, 1, 1)
    days = (date(d.year + 1, 1, 1) - start).days
    return d.year + (d - start).days / days


def total_correction(x: float, y: float, when: date) -> float:
    """Grid north -> magnetic north at EPSG:3067 (x, y) on ``when``, degrees, east positive."""
    lat, lon = to_lat_lon(x, y)
    return declination(lat, lon, decimal_year(when)) - convergence(x, y)


def format_correction(deg: float) -> str:
    """'kok. +12°': whole degrees, half away from zero, sign unless zero."""
    whole = int(floor(abs(deg) + 0.5))
    if whole == 0:
        return "kok. 0°"
    return f"kok. {'+' if deg > 0 else '−'}{whole}°"
