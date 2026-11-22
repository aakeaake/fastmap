from pathlib import Path

import mapbox_vector_tile
import pytest
from shapely.affinity import affine_transform
from shapely.geometry import shape

from fastmap.vector import mvt

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "vector"


def _reference(data):
    """(layer, props, geometry in tile units, y up) from mapbox_vector_tile."""
    for name, layer in mapbox_vector_tile.decode(data).items():
        for f in layer["features"]:
            try:
                g = shape(f["geometry"])
            except Exception:  # noqa: BLE001 - the reference skips these too
                continue
            yield name, layer["extent"], f["properties"], g


@pytest.mark.parametrize("path", sorted(FIXTURES.rglob("*.pbf")), ids=lambda p: p.stem)
def test_decoder_matches_mapbox_vector_tile(path):
    data = path.read_bytes()
    ours = list(mvt.read_tile(data))
    ref = list(_reference(data))
    assert len(ours) >= len(ref) > 0
    ref_iter = iter(ref)
    checked = 0
    for raw in ours:
        geom = mvt.build_geometry(raw, minx=0.0, miny=0.0, scale=1.0)
        if geom is None:
            continue
        name, extent, props, g = next(ref_iter)
        assert (raw.layer, raw.props) == (name, props)
        # ours: y up in units of the tile extent, like the reference
        assert geom.equals_exact(g, 1e-9), (name, props)
        checked += 1
    assert checked == len(ref)


def test_build_geometry_places_tile_in_metres():
    data = mapbox_vector_tile.encode(
        [{"name": "p", "features": [{"geometry": "POINT (10 4000)", "properties": {"a": 1}}]}]
    )
    raw = next(mvt.read_tile(data))
    pt = mvt.build_geometry(raw, minx=1000.0, miny=2000.0, scale=0.5)
    assert (raw.geom_type, raw.props) == ("Point", {"a": 1})
    assert (pt.x, pt.y) == pytest.approx((1005.0, 4000.0))


def test_affine_reference_is_the_same_transform():
    # build_geometry(minx, miny, scale) == affine of the y-up tile geometry
    data = mapbox_vector_tile.encode(
        [{"name": "l", "features": [{"geometry": "LINESTRING (0 0, 100 50)", "properties": {}}]}]
    )
    raw = next(mvt.read_tile(data))
    a = mvt.build_geometry(raw, minx=0.0, miny=0.0, scale=1.0)
    b = mvt.build_geometry(raw, minx=7.0, miny=9.0, scale=2.0)
    assert b.equals_exact(affine_transform(a, [2, 0, 0, 2, 7, 9]), 1e-9)


def test_read_tile_skips_unlisted_layers():
    data = mapbox_vector_tile.encode(
        [
            {"name": "a", "features": [{"geometry": "POINT (1 1)", "properties": {"k": 1}}]},
            {"name": "b", "features": [{"geometry": "POINT (2 2)", "properties": {"k": 2}}]},
        ]
    )
    assert [f.layer for f in mvt.read_tile(data)] == ["a", "b"]
    assert [f.layer for f in mvt.read_tile(data, layers={"b"})] == ["b"]


def test_features_with_equal_tags_share_one_props_dict():
    same = {"geometry": "POINT (1 1)", "properties": {"k": 1}}
    other = {"geometry": "POINT (2 2)", "properties": {"k": 2}}
    data = mapbox_vector_tile.encode([{"name": "a", "features": [same, dict(same), other]}])
    a, b, c = mvt.read_tile(data)
    assert a.props is b.props and a.props == {"k": 1}
    assert c.props == {"k": 2}
