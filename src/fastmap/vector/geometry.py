"""Merge tile pieces of the same map object and clip to the print extent."""

from __future__ import annotations

import shapely
from shapely.geometry import box
from shapely.ops import linemerge

from fastmap.services.print_layout import Extent

from .model import Feature

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
        if first.geom_type == "Polygon":
            merged = shapely.union_all(geoms)
        else:
            merged = shapely.union_all(geoms)
            if merged.geom_type == "MultiLineString":
                merged = linemerge(merged)
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
