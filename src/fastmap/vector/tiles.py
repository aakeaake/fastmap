"""Fetch and decode MML vector tiles (Mapbox Vector Tile, EPSG:3067)."""

from __future__ import annotations

from concurrent.futures import as_completed

import mapbox_vector_tile
import requests
from shapely.affinity import affine_transform
from shapely.geometry import MultiPolygon, box, shape
from shapely.validation import make_valid

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
from fastmap.vector.geometry import _only_type
from fastmap.vector.model import Feature

MAX_VECTOR_TILES = 400

_SINGLE_TYPE = {
    "Point": "Point",
    "MultiPoint": "Point",
    "LineString": "LineString",
    "MultiLineString": "LineString",
    "Polygon": "Polygon",
    "MultiPolygon": "Polygon",
}


def tile_range(extent: Extent, level: int, pad: int = 1) -> tuple[int, int, int, int]:
    """Tile range (col_min, row_min, col_max, row_max), widened by ``pad``."""
    col_min, row_min, col_max, row_max = mml_source.tile_range(extent, level)
    return col_min - pad, row_min - pad, col_max + pad, row_max + pad


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


def decode_tile(data: bytes, level: int, row: int, col: int) -> list[Feature]:
    """Decode a tile into features with geometry in EPSG:3067 metres."""
    tile_m = WMTS_TILE_SIZE * 8192.0 / 2**level
    ox, oy = WMTS_ORIGIN
    minx = ox + col * tile_m
    miny = oy - (row + 1) * tile_m
    cell = box(minx, miny, minx + tile_m, miny + tile_m)

    try:
        decoded = mapbox_vector_tile.decode(data)
    except Exception:  # noqa: BLE001 - any parser failure means a bad tile
        raise MMLError(f"Vector tile decode failed for {level}/{row}/{col}") from None

    out: list[Feature] = []
    for layer_name, layer in decoded.items():
        scale = tile_m / (layer.get("extent") or 4096)
        for feat in layer.get("features", []):
            geom = feat.get("geometry") or {}
            gtype = _SINGLE_TYPE.get(geom.get("type", ""))
            if gtype is None:
                continue
            try:
                g = shape(geom)
            except Exception:  # noqa: BLE001 - skip malformed geometry
                continue
            if g.is_empty:
                continue
            g = _to_metres(g, minx, miny, scale)
            if gtype == "Polygon" and not g.is_valid:
                g = make_valid(g)
                if g.geom_type not in ("Polygon", "MultiPolygon"):
                    # make_valid may yield a collection; keep only the areal parts
                    parts = [p for p in getattr(g, "geoms", []) if p.geom_type == "Polygon"]
                    if not parts:
                        continue
                    g = MultiPolygon(parts)
            g = _only_type(g.intersection(cell), gtype)
            if g is None:
                continue
            out.append(Feature(layer_name, gtype, g, dict(feat.get("properties") or {})))
    return out


def _to_metres(g, minx: float, miny: float, scale: float):
    return affine_transform(g, [scale, 0, 0, scale, minx, miny])


def load_tiles(extent: Extent, level: int) -> list[Feature]:
    """Fetch and decode every tile covering ``extent`` (plus a 1-tile pad)."""
    col_min, row_min, col_max, row_max = tile_range(extent, level)
    n = (col_max - col_min + 1) * (row_max - row_min + 1)
    if n > MAX_VECTOR_TILES:
        raise MMLError("Requested area needs too many vector tiles")

    def work(row: int, col: int) -> list[Feature]:
        data = fetch_tile(level, row, col)
        return decode_tile(data, level, row, col) if data else []

    futures = [
        _tile_pool.submit(work, r, c)
        for r in range(row_min, row_max + 1)
        for c in range(col_min, col_max + 1)
    ]
    features: list[Feature] = []
    try:
        for future in as_completed(futures):
            features.extend(future.result())
    except BaseException:
        for future in futures:
            future.cancel()
        raise
    return features
