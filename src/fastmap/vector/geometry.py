"""Merge tile pieces of the same map object and clip to the print extent."""

from __future__ import annotations

import shapely
from shapely.geometry import LineString, box
from shapely.ops import linemerge

from fastmap.services.print_layout import Extent

from .model import Feature

SNAP_TOLERANCE_M = 1.0

_FAMILY = {
    "Point": ("Point", "MultiPoint"),
    "LineString": ("LineString", "MultiLineString"),
    "Polygon": ("Polygon", "MultiPolygon"),
}


def _only_type(geom, geom_type: str):
    """Keep only the parts of ``geom`` matching ``geom_type``; None if nothing is left."""
    if geom is None or geom.is_empty:
        return None
    names = _FAMILY[geom_type]
    if geom.geom_type in names:
        return geom
    if geom.geom_type == "GeometryCollection":
        parts = [p for p in geom.geoms if p.geom_type in names and not p.is_empty]
        if not parts:
            return None
        return shapely.union_all(parts)
    return None


def _join_lines(geoms):
    """Merge line pieces, bridging gaps up to SNAP_TOLERANCE_M between their ends.

    Tile-edge clipping leaves pieces whose ends differ by a few cm; end points
    that lie within the tolerance of each other are moved to a shared
    coordinate so ``linemerge`` can join them. Branch points stay branches.
    """
    parts = []
    for g in geoms:
        parts.extend(g.geoms if hasattr(g, "geoms") else [g])
    coords = [list(p.coords) for p in parts]
    anchors: list[tuple[float, float]] = []  # one shared coordinate per end cluster
    tol2 = SNAP_TOLERANCE_M**2

    def anchor(pt):
        for a in anchors:
            if (a[0] - pt[0]) ** 2 + (a[1] - pt[1]) ** 2 <= tol2:
                return a
        anchors.append((pt[0], pt[1]))
        return anchors[-1]

    for c in coords:
        for i in (0, -1):
            c[i] = anchor(c[i][:2])
    lines = [LineString(c) for c in coords if len(c) > 1 and c[0] != c[-1] or len(c) > 2]
    if not lines:
        return None
    merged = shapely.union_all(lines)
    if merged.geom_type == "MultiLineString":
        return linemerge(merged)
    return merged  # LineString, or a collection that _only_type filters later


def merge_by_mtk_id(features: list[Feature]) -> list[Feature]:
    """Join pieces of one object (same layer and ``mtk_id``) split by tile edges."""
    out: list[Feature] = []
    groups: dict[tuple, list[Feature]] = {}
    slots: dict[tuple, int] = {}
    for f in features:
        mtk_id = f.props.get("mtk_id")
        if mtk_id is None:
            out.append(f)
            continue
        key = (f.layer, f.geom_type, mtk_id)
        if key not in groups:
            groups[key] = []
            slots[key] = len(out)
            out.append(f)  # placeholder keeps first-seen order
        groups[key].append(f)
    for key, pieces in groups.items():
        first = pieces[0]
        if len(pieces) == 1 or first.geom_type == "Point":
            continue
        geoms = [p.geometry for p in pieces]
        if first.geom_type == "LineString":
            merged = _join_lines(geoms)
        else:
            merged = shapely.union_all(geoms)
        merged = _only_type(merged, first.geom_type)
        if merged is None:
            continue
        out[slots[key]] = Feature(first.layer, first.geom_type, merged, first.props)
    return out


def clip_features(features: list[Feature], extent: Extent, buffer_m: float) -> list[Feature]:
    """Intersect features with the extent grown by ``buffer_m``; drop empties."""
    clip = box(
        extent.minx - buffer_m,
        extent.miny - buffer_m,
        extent.maxx + buffer_m,
        extent.maxy + buffer_m,
    )
    out: list[Feature] = []
    for f in features:
        g = _only_type(f.geometry.intersection(clip), f.geom_type)
        if g is not None:
            out.append(Feature(f.layer, f.geom_type, g, f.props))
    return out
