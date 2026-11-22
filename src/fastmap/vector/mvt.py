"""Minimal Mapbox Vector Tile reader: properties first, geometry only on demand.

mapbox_vector_tile.decode builds every feature's geometry in pure Python (and as
GeoJSON dicts). Most features of a tile are not drawn at a given scale, so this
reader yields each feature's properties first, and ``build_geometry`` decodes the
geometry of the kept ones with numpy, straight into map metres. It uses the same
protobuf classes, and groups polygon rings exactly like mapbox_vector_tile.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
import shapely
from mapbox_vector_tile.decoder import TileData
from mapbox_vector_tile.Mapbox import vector_tile_pb2
from shapely.geometry.base import BaseGeometry

GeomType = Literal["Point", "LineString", "Polygon"]

_TYPES: dict[int, GeomType] = {1: "Point", 2: "LineString", 3: "Polygon"}
_MOVE_TO, _LINE_TO, _CLOSE_PATH = 1, 2, 7


@dataclass(frozen=True)
class RawFeature:
    layer: str
    tile_extent: int  # tile units across the tile
    geom_type: GeomType
    props: dict  # shared by the layer's features with the same tags: do not mutate
    commands: Sequence[int]  # MVT geometry command stream (tile units, y down)


def _value(v: vector_tile_pb2.tile.value) -> bool | int | float | str | None:
    """A layer value as mapbox_vector_tile reads it; None for one with no known field."""
    try:
        return TileData.parse_value(v)
    except ValueError:
        return None


def read_tile(data: bytes, layers: Collection[str] | None = None) -> Iterator[RawFeature]:
    """Every feature of a tile with known geometry type, geometry still encoded.

    ``layers`` limits the reading to those tile layers (the others are skipped
    before their values are decoded).
    """
    tile = vector_tile_pb2.tile()
    tile.ParseFromString(data)
    for layer in tile.layers:
        if layers is not None and layer.name not in layers:
            continue
        keys = list(layer.keys)
        values = [_value(v) for v in layer.values]
        extent = layer.extent or 4096
        by_tags: dict[tuple[int, ...], dict] = {}  # features with equal tags share props
        for f in layer.features:
            geom_type = _TYPES.get(f.type)
            if geom_type is None:
                continue
            tags = tuple(f.tags)
            props = by_tags.get(tags)
            if props is None:
                pairs = range(0, len(tags) - 1, 2)
                props = by_tags[tags] = {keys[tags[i]]: values[tags[i + 1]] for i in pairs}
            yield RawFeature(layer.name, extent, geom_type, props, f.geometry)


def _decode_runs(commands: Sequence[int], close: bool) -> list[np.ndarray]:
    """Decode the command stream into point runs (one per MoveTo / ring).

    The cursor carries across commands, so all parameters are zigzag-decoded and
    summed in one go; only the command headers are walked in Python.
    """
    cmds = list(commands)
    n = len(cmds)
    keep = np.zeros(n, dtype=bool)  # which ints are coordinate parameters
    ranges: list[list[int]] = []  # [first point, end point] of each run
    npts, i = 0, 0
    while i < n:
        header = cmds[i]
        cmd, count = header & 7, header >> 3
        i += 1
        if cmd == _CLOSE_PATH:
            continue
        if cmd not in (_MOVE_TO, _LINE_TO):
            break  # unknown command: the rest of the stream can't be followed
        end = min(i + 2 * count, n)
        keep[i:end] = True
        count = (end - i) // 2
        if cmd == _MOVE_TO or not ranges:
            ranges.append([npts, npts])
        npts += count
        ranges[-1][1] = npts
        i = end
    if npts == 0:
        return []
    raw = np.asarray(cmds, dtype=np.int64)[keep][: 2 * npts]
    pts = np.cumsum(((raw >> 1) ^ -(raw & 1)).reshape(-1, 2), axis=0)  # zigzag, deltas
    runs = [pts[a:b] for a, b in ranges if b > a]
    if close:
        runs = [r if (r[0] == r[-1]).all() else np.vstack([r, r[:1]]) for r in runs]
    return runs


def _area_sign(ring: np.ndarray) -> int:
    x, y = ring[:, 0], ring[:, 1]
    a = float(np.sum(x[:-1] * y[1:] - x[1:] * y[:-1]))
    return -1 if a < 0 else 1 if a > 0 else 0


def _to_map(run: np.ndarray, origin: np.ndarray, flip: np.ndarray) -> np.ndarray:
    """Tile units (y down) to map units: ``run · flip + origin``."""
    return run * flip + origin


def _points(runs: list[np.ndarray], origin: np.ndarray, flip: np.ndarray) -> BaseGeometry:
    pts = _to_map(np.vstack(runs), origin, flip)
    return shapely.points(pts[0]) if len(pts) == 1 else shapely.multipoints(pts)


def _lines(runs: list[np.ndarray], origin: np.ndarray, flip: np.ndarray) -> BaseGeometry | None:
    lines = [_to_map(r, origin, flip) for r in runs if len(r) >= 2]
    if not lines:
        return None
    if len(lines) == 1:
        return shapely.linestrings(lines[0])
    return shapely.multilinestrings([shapely.linestrings(p) for p in lines])


def _polygons(runs: list[np.ndarray], origin: np.ndarray, flip: np.ndarray) -> BaseGeometry | None:
    # Rings wound like the first one start a polygon, the others are its holes
    # (mapbox_vector_tile's rule); zero-area rings are dropped. Windings are
    # taken in exact tile units, before the transform.
    polygons: list[list[np.ndarray]] = []
    winding = 0
    for ring in runs:
        sign = _area_sign(ring)
        if sign == 0:
            continue
        winding = winding or sign
        if sign == winding:
            polygons.append([ring])
        elif polygons:
            polygons[-1].append(ring)
    if not polygons:
        return None
    shapes = [
        shapely.polygons(
            _to_map(rings[0], origin, flip),
            holes=[shapely.linearrings(_to_map(h, origin, flip)) for h in rings[1:]] or None,
        )
        for rings in polygons
    ]
    return shapes[0] if len(shapes) == 1 else shapely.multipolygons(shapes)


_BUILDERS = {"Point": _points, "LineString": _lines, "Polygon": _polygons}


def build_geometry(f: RawFeature, minx: float, miny: float, scale: float) -> BaseGeometry | None:
    """The feature's shape in map units: x = minx + tx·scale, y = miny + (extent − ty)·scale.

    None when the geometry is degenerate (no points, a one-point line).
    """
    runs = _decode_runs(f.commands, close=f.geom_type == "Polygon")
    if not runs:
        return None
    origin = np.array([minx, miny + f.tile_extent * scale])
    flip = np.array([scale, -scale])
    return _BUILDERS[f.geom_type](runs, origin, flip)
