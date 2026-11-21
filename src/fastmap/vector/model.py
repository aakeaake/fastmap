"""Decoded vector-tile features in EPSG:3067 metres."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry.base import BaseGeometry


@dataclass
class Feature:
    layer: str
    geom_type: str  # Point | LineString | Polygon (multi-geometries use the single type)
    geometry: BaseGeometry
    props: dict[str, Any]
