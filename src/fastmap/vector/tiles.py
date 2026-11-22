"""Fetch and decode MML vector tiles (Mapbox Vector Tile, EPSG:3067)."""

from __future__ import annotations

from concurrent.futures import as_completed

import requests
import shapely
from shapely.geometry import box

from fastmap.core.config import MML_VECTOR_URL
from fastmap.services import mml_source
from fastmap.services.mml_source import (
    TILE_TIMEOUT,
    WMTS_ORIGIN,
    WMTS_TILE_SIZE,
    MMLError,
    _require_api_key,
    _session,
    _tile_pool,
)
from fastmap.services.print_layout import Extent
from fastmap.vector.expressions import EvalContext
from fastmap.vector.geometry import only_type
from fastmap.vector.model import Feature
from fastmap.vector.mvt import build_geometry, read_tile
from fastmap.vector.style import StyleLayer

MAX_VECTOR_TILES = 400


def tile_size_m(level: int) -> float:
    """Ground size of one tile cell at ``level`` in metres."""
    return WMTS_TILE_SIZE * 8192.0 / 2**level


def fetch_tile(level: int, row: int, col: int) -> bytes | None:
    """Fetch one vector tile; ``None`` when MML has no data there (404)."""
    key = _require_api_key()
    url = MML_VECTOR_URL.format(z=level, y=row, x=col) + f"?api-key={key}"
    # Name the tile, never the URL (it carries the API key).
    tile = f"{level}/{row}/{col}"
    try:
        resp = _session.get(url, timeout=TILE_TIMEOUT)
    except requests.RequestException as exc:
        raise MMLError(f"Vector tile fetch failed ({type(exc).__name__}) for {tile}") from None
    try:
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise MMLError(f"Vector tile fetch failed ({resp.status_code}) for {tile}")
        return resp.content
    finally:
        resp.close()


class FeatureFilter:
    """Which tile features a map draws, decided from their properties alone.

    ``by_source`` holds, per tile layer, the style layers (visible at ``zoom``)
    that read it; a feature is kept when any of them would draw it.
    """

    def __init__(self, by_source: dict[str, list[StyleLayer]], zoom: float) -> None:
        self.by_source = by_source
        self.zoom = zoom
        self.layers: frozenset[str] = frozenset(by_source)  # tile layers worth reading

    def __call__(self, layer: str, props: dict, geom_type: str) -> bool:
        ctx = EvalContext(props, self.zoom, geom_type)
        return any(sl.matches(ctx) for sl in self.by_source.get(layer, ()))


def decode_tile(
    data: bytes, level: int, row: int, col: int, keep: FeatureFilter | None = None
) -> list[Feature]:
    """Decode a tile into features with geometry in EPSG:3067 metres.

    ``keep`` filters features before any geometry is built (the costly part).
    """
    tile_m = tile_size_m(level)
    ox, oy = WMTS_ORIGIN
    minx = ox + col * tile_m
    miny = oy - (row + 1) * tile_m
    maxx = minx + tile_m
    maxy = miny + tile_m
    cell = box(minx, miny, maxx, maxy)

    try:
        raw_features = list(read_tile(data, None if keep is None else keep.layers))
    except Exception:  # noqa: BLE001 - any parser failure means a bad tile
        raise MMLError(f"Vector tile decode failed for {level}/{row}/{col}") from None

    out: list[Feature] = []
    for raw in raw_features:
        geom_type = raw.geom_type
        if keep is not None and not keep(raw.layer, raw.props, geom_type):
            continue
        try:
            g = build_geometry(raw, minx, miny, tile_m / raw.tile_extent)
        except Exception:  # noqa: BLE001 - skip malformed geometry
            continue
        if g is None or g.is_empty:
            continue
        if geom_type == "Polygon" and not g.is_valid:
            # Tiles hold rings that run back over themselves along the buffer
            # line, and holes touching the exterior there. The 'structure'
            # repair keeps exteriors as area and holes as holes (linework fills
            # such holes); its areal parts may come as a MultiPolygon inside a
            # collection.
            g = only_type(shapely.make_valid(g, method="structure"), geom_type)
            if g is None:
                continue
        x0, y0, x1, y1 = g.bounds
        if not (minx <= x0 and miny <= y0 and x1 <= maxx and y1 <= maxy):
            g = only_type(g.intersection(cell), geom_type)  # crosses into the tile buffer
            if g is None:
                continue
        out.append(Feature(raw.layer, geom_type, g, raw.props))
    return out


def load_tiles(extent: Extent, level: int, keep: FeatureFilter | None = None) -> list[Feature]:
    """Fetch and decode every tile covering ``extent``.

    Downloads run on the shared tile pool; decoding is CPU-bound, so it runs here
    on the calling thread as tiles arrive (threads would only contend for the GIL).
    """
    col_min, row_min, col_max, row_max = mml_source.tile_range(extent, level)
    n = (col_max - col_min + 1) * (row_max - row_min + 1)
    if n > MAX_VECTOR_TILES:
        raise MMLError("Requested area needs too many vector tiles")

    def fetch(row: int, col: int) -> tuple[int, int, bytes | None]:
        return row, col, fetch_tile(level, row, col)

    futures = [
        _tile_pool.submit(fetch, r, c)
        for r in range(row_min, row_max + 1)
        for c in range(col_min, col_max + 1)
    ]
    by_tile: dict[tuple[int, int], list[Feature]] = {}
    try:
        for future in as_completed(futures):
            row, col, data = future.result()
            if data:
                by_tile[(row, col)] = decode_tile(data, level, row, col, keep)
    except BaseException:
        for future in futures:
            future.cancel()
        raise
    # grid order, not arrival order: feature order decides how pieces join and
    # where labels go, so the same request always gives the same map
    return [f for tile in sorted(by_tile) for f in by_tile[tile]]
