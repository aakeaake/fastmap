"""Merge tile pieces of the same map object and clip to the print extent."""

from __future__ import annotations

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import linemerge

from fastmap.services.mml_source import WMTS_ORIGIN
from fastmap.services.print_layout import Extent

from .model import Feature

SNAP_TOLERANCE_M = 1.0
CUT_TOLERANCE_M = 0.01  # cut vertices sit exactly on the cell edge
MIN_CUT_EDGE_M = 0.5  # shorter stretches on a cell edge are jogs between merged pieces

_FAMILY = {
    "Point": ("Point", "MultiPoint"),
    "LineString": ("LineString", "MultiLineString"),
    "Polygon": ("Polygon", "MultiPolygon"),
}


def parts(geom) -> list:
    """The parts of a multi-geometry, or the geometry itself as the only part."""
    return getattr(geom, "geoms", [geom])


def only_type(geom, geom_type: str):
    """Keep only the parts of ``geom`` matching ``geom_type``; None if nothing is left."""
    if geom is None or geom.is_empty:
        return None
    names = _FAMILY[geom_type]
    if geom.geom_type in names:
        return geom
    if geom.geom_type == "GeometryCollection":
        kept = [p for p in geom.geoms if p.geom_type in names and not p.is_empty]
        if not kept:
            return None
        return shapely.union_all(kept)
    return None


def _join_lines(geoms):
    """Merge line pieces, bridging gaps up to SNAP_TOLERANCE_M between their ends.

    Tile-edge clipping leaves pieces whose ends differ by a few cm; end points
    that lie within the tolerance of each other are moved to a shared
    coordinate so ``linemerge`` can join them. Branch points stay branches.
    """
    coords = [list(p.coords) for g in geoms for p in parts(g)]
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
    return merged  # LineString, or a collection that only_type filters later


# Area layers whose polygons are merged by class, not by object: a protected area
# stored as several adjacent polygons must print as one area, with no border
# drawn along the shared edges.
DISSOLVE_BY_CLASS = frozenset({"alueraja"})


def merge_by_mtk_id(features: list[Feature]) -> list[Feature]:
    """Join pieces of one object (same layer and ``mtk_id``) split by tile edges.

    Polygons of the ``DISSOLVE_BY_CLASS`` layers are joined by ``kohdeluokka``.
    """
    out: list[Feature] = []
    groups: dict[tuple, list[Feature]] = {}
    slots: dict[tuple, int] = {}
    for f in features:
        if f.layer in DISSOLVE_BY_CLASS and f.geom_type == "Polygon":
            key = (f.layer, f.geom_type, "class", f.props.get("kohdeluokka"))
        elif f.props.get("mtk_id") is None:
            out.append(f)
            continue
        else:
            key = (f.layer, f.geom_type, f.props["mtk_id"])
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
        merged = only_type(merged, first.geom_type)
        if merged is None:
            continue
        out[slots[key]] = Feature(first.layer, first.geom_type, merged, first.props)
    return out


def clip_features(features: list[Feature], extent: Extent, buffer_m: float) -> list[Feature]:
    """Intersect features with the extent grown by ``buffer_m``; drop empties."""
    clip = box(*extent.buffered(buffer_m).as_tuple())
    out: list[Feature] = []
    for f in features:
        g = only_type(f.geometry.intersection(clip), f.geom_type)
        if g is not None:
            out.append(Feature(f.layer, f.geom_type, g, f.props))
    return out


def _cut_segments(coords: np.ndarray, tile_m: float) -> np.ndarray:
    """Per segment: True when it runs along a tile-cell edge for at least MIN_CUT_EDGE_M."""
    cut = np.zeros(len(coords) - 1, dtype=bool)
    for axis, origin in enumerate(WMTS_ORIGIN):
        f = (coords[:, axis] - origin) / tile_m
        k = np.round(f)
        on = np.abs(f - k) * tile_m <= CUT_TOLERANCE_M
        cut |= on[:-1] & on[1:] & (k[:-1] == k[1:])
    lengths = np.hypot(*np.diff(coords, axis=0).T)
    return cut & (lengths >= MIN_CUT_EDGE_M)


def outline(geom, tile_m: float | None):
    """A polygon's boundary as lines, minus the stretches along tile-cell edges.

    Tiles are clipped to their cells, so a boundary runs along a cell edge
    where the object goes on in the next tile. Those stretches are clipping
    artefacts, not edges of the object, and are left out. The few-cm jogs left
    where merged pieces' cut vertices differ are kept, so an outline crossing a
    seam stays one line (dashes and offsets do not restart there). ``tile_m``
    None keeps everything.
    """
    boundary = geom.boundary
    if tile_m is None:
        return boundary
    out: list[LineString] = []
    for line in parts(boundary):
        a = np.asarray(line.coords)[:, :2]
        if len(a) < 2:
            continue
        cut = _cut_segments(a, tile_m)
        if not cut.any():
            out.append(line)
            continue
        if line.is_closed and not cut.all():
            # start the ring just after a cut so no kept run wraps around
            r = int(np.argmax(cut)) + 1
            a = np.roll(a[:-1], -r, axis=0)
            a = np.vstack([a, a[:1]])
            cut = np.roll(cut, -r)
        start = None
        for i, is_cut in enumerate([*cut, True]):
            if not is_cut and start is None:
                start = i
            elif is_cut and start is not None:
                out.append(LineString(a[start : i + 1]))
                start = None
    return shapely.line_merge(MultiLineString(out))


def simplify_features(features: list[Feature], tolerance_m: float, geom_type: str) -> list[Feature]:
    """Drop vertices of ``geom_type`` shapes that move them less than ``tolerance_m``.

    Tile geometry is stored far finer than print can show; fewer vertices make the
    later stages and the drawing faster and the PDF smaller. Polygons keep their
    topology (they stay valid); lines use the faster plain Douglas-Peucker, which
    keeps their endpoints, so pieces still join at tile edges. Other features pass
    through; shapes that simplify away are dropped.
    """
    selected = [f for f in features if f.geom_type == geom_type]
    simplified = iter(
        shapely.simplify(
            np.array([f.geometry for f in selected], dtype=object),
            tolerance_m,
            preserve_topology=geom_type == "Polygon",
        )
    )
    out: list[Feature] = []
    for f in features:
        if f.geom_type != geom_type:
            out.append(f)
            continue
        g = next(simplified)
        if not g.is_empty:
            out.append(Feature(f.layer, f.geom_type, g, f.props))
    return out
