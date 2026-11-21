from collections import Counter

import pytest
import shapely
from shapely.geometry import LineString, Point, box

from fastmap.services.print_layout import Extent
from fastmap.vector import tiles
from fastmap.vector.geometry import clip_features, merge_by_mtk_id
from fastmap.vector.model import Feature


def _f(layer, gt, geom, **props):
    return Feature(layer, gt, geom, props)


def test_polygon_halves_merge_into_one():
    a = _f("l", "Polygon", box(0, 0, 10, 10), mtk_id=1, n="a")
    b = _f("l", "Polygon", box(10, 0, 20, 10), mtk_id=1, n="b")
    out = merge_by_mtk_id([a, b])
    assert len(out) == 1
    assert out[0].geometry.geom_type == "Polygon"
    assert out[0].geometry.area == 200
    assert out[0].props["n"] == "a"


def test_line_pieces_merge_into_one():
    a = _f("l", "LineString", LineString([(0, 0), (10, 0)]), mtk_id=1)
    b = _f("l", "LineString", LineString([(10, 0), (25, 0)]), mtk_id=1)
    out = merge_by_mtk_id([a, b])
    assert len(out) == 1
    assert out[0].geometry.geom_type == "LineString"
    assert out[0].geometry.length == 25


def test_points_deduplicated_and_layers_separate():
    a = _f("l", "Point", Point(1, 1), mtk_id=1, n="first")
    b = _f("l", "Point", Point(1, 1), mtk_id=1, n="second")
    c = _f("other", "Point", Point(1, 1), mtk_id=1)
    out = merge_by_mtk_id([a, b, c])
    assert len(out) == 2
    assert out[0].props["n"] == "first"


def test_no_mtk_id_passes_through():
    fs = [_f("l", "Polygon", box(0, 0, 1, 1)) for _ in range(3)]
    assert len(merge_by_mtk_id(fs)) == 3


def test_clip_drops_outside_and_shortens_crossing():
    ext = Extent(0, 0, 100, 100)
    inside = _f("l", "LineString", LineString([(10, 10), (20, 10)]))
    outside = _f("l", "LineString", LineString([(500, 500), (600, 500)]))
    crossing = _f("l", "LineString", LineString([(50, 50), (200, 50)]))
    out = clip_features([inside, outside, crossing], ext, buffer_m=10)
    assert len(out) == 2
    assert out[1].geometry.bounds == (50, 50, 110, 50)


def test_clip_keeps_geom_type_consistent():
    ext = Extent(0, 0, 100, 100)
    # polygon touching the buffered box only along an edge -> line leftover, dropped
    p = _f("l", "Polygon", box(110, 0, 200, 100))
    assert clip_features([p], ext, buffer_m=10) == []


def test_real_tiles_merge_preserves_area(offline_tiles):
    cx, cy = offline_tiles
    feats = tiles.load_tiles(Extent(cx - 500, cy - 500, cx + 500, cy + 500), 12)
    merged = merge_by_mtk_id(feats)
    keyed = Counter(
        (f.layer, f.props["mtk_id"]) for f in merged if f.props.get("mtk_id") is not None
    )
    assert keyed and all(n == 1 for n in keyed.values())
    layers = {f.layer for f in feats if f.geom_type == "Polygon"}
    assert layers
    for layer in layers:
        pieces = [
            f.geometry
            for f in feats
            if f.layer == layer and f.geom_type == "Polygon" and "mtk_id" in f.props
        ]
        after = [
            f.geometry
            for f in merged
            if f.layer == layer and f.geom_type == "Polygon" and "mtk_id" in f.props
        ]
        if not pieces:
            continue
        ref = shapely.union_all(pieces).area
        total = sum(g.area for g in after)
        assert abs(total - ref) <= 0.01 * ref


def _fixture_pieces(offline_tiles):
    cx, cy = offline_tiles
    return tiles.load_tiles(Extent(cx - 1500, cy - 1500, cx + 1500, cy + 1500), 12)


def test_real_tiles_contours_merge_to_single_lines(offline_tiles):
    pieces = _fixture_pieces(offline_tiles)
    # outer limit of the fixture tiles: lines may only end there (data ends)
    minx, miny, maxx, maxy = shapely.union_all([f.geometry for f in pieces]).bounds
    tile_m = 256 * 8192 / 2**12
    contours = [
        f for f in merge_by_mtk_id(pieces) if f.layer == "korkeus" and f.geom_type == "LineString"
    ]
    assert contours
    singles = 0
    for f in contours:
        parts = getattr(f.geometry, "geoms", [f.geometry])
        ends = Counter()
        for g in parts:
            for x, y in (g.coords[0], g.coords[-1]):
                ends[(round(x, 1), round(y, 1))] += 1
        for (x, y), n in ends.items():
            if n == 1:  # dangling end: contours may end, but never on an inner tile seam
                on_outer = min(abs(x - minx), abs(x - maxx), abs(y - miny), abs(y - maxy)) < 1.0
                dx = (x - minx) % tile_m
                dy = (y - miny) % tile_m
                on_seam = min(dx, tile_m - dx, dy, tile_m - dy) < 1.0
                assert on_outer or not on_seam, (f.props["mtk_id"], x, y)
        singles += f.geometry.geom_type == "LineString"
    assert singles > len(contours) / 2


def test_real_tiles_line_length_preserved(offline_tiles):
    pieces = _fixture_pieces(offline_tiles)
    summed: dict = {}
    for f in pieces:
        if f.geom_type == "LineString" and f.props.get("mtk_id") is not None:
            k = (f.layer, f.props["mtk_id"])
            summed[k] = summed.get(k, 0.0) + f.geometry.length
    assert summed
    got: dict = {}
    for f in merge_by_mtk_id(pieces):
        if f.geom_type == "LineString" and f.props.get("mtk_id") is not None:
            k = (f.layer, f.props["mtk_id"])
            got[k] = got.get(k, 0.0) + f.geometry.length
    assert got.keys() == summed.keys()
    for k, total in summed.items():
        assert abs(got[k] - total) <= 0.005 * total + 1.0, k


def test_real_tiles_no_duplicate_points(offline_tiles):
    pts = [f for f in _fixture_pieces(offline_tiles) if f.geom_type == "Point"]
    assert pts
    seen = set()
    for f in pts:
        key = (
            f.layer,
            repr(sorted(f.props.items())),
            round(f.geometry.x, 1),
            round(f.geometry.y, 1),
        )
        assert key not in seen
        seen.add(key)


def test_line_pieces_dissolving_into_one_linestring():
    a = _f("l", "LineString", LineString([(0, 0), (10, 0)]), mtk_id=1)
    b = _f("l", "LineString", LineString([(0, 0), (10, 0)]), mtk_id=1)
    out = merge_by_mtk_id([a, b])
    assert len(out) == 1
    assert out[0].geometry.geom_type == "LineString"
    assert out[0].geometry.length == 10


def test_seam_pieces_leave_no_gap_or_sliver():
    # One object clipped into two tile cells, cut vertices a few cm apart.
    from shapely.geometry import Polygon

    x = -548576 + 1800 * 512
    left = Polygon([(x - 150, 100), (x, 100.0), (x, 300.02), (x - 150, 300)])
    right = Polygon([(x, 99.97), (x + 150, 100), (x + 150, 300), (x, 299.99)])
    merged = merge_by_mtk_id([_f("l", "Polygon", g, mtk_id=1) for g in (left, right)])
    assert len(merged) == 1
    g = merged[0].geometry
    assert g.geom_type == "Polygon" and not g.interiors
    assert g.area == pytest.approx(left.area + right.area)
    assert g.contains(box(x - 0.5, 101, x + 0.5, 299))  # nothing open along the seam


def test_outline_leaves_out_cell_edges_and_keeps_the_rest_joined():
    from fastmap.vector.geometry import outline

    x = -548576 + 1800 * 512
    # ring starts mid-way along the real edges; its east side is the cell edge
    ring = shapely.Polygon([(x - 50, 10), (x, 10), (x, 110), (x - 100, 110), (x - 100, 10)])
    lines = outline(ring, 512)
    assert lines.geom_type == "MultiLineString" and len(lines.geoms) == 1
    assert lines.length == pytest.approx(300)  # the 100 m cell-edge side is gone
    assert outline(ring, None).length == pytest.approx(400)
    assert outline(box(x - 100, 10, x - 10, 60), 512).length == pytest.approx(280)
