from unittest.mock import MagicMock

import mapbox_vector_tile
import pytest
from shapely.geometry import Point

from fastmap.services import mml_source
from fastmap.services.mml_source import MMLError
from fastmap.services.print_layout import Extent
from fastmap.vector import tiles


def _resp(status):
    r = MagicMock()
    r.status_code = status
    r.content = b""
    return r


def test_load_fetches_exactly_the_tiles_covering_the_extent(monkeypatch):
    ext = Extent(371000, 6687000, 372000, 6688000)
    c0, r0, c1, r1 = mml_source.tile_range(ext, 12)
    fetched = []
    monkeypatch.setattr(tiles, "fetch_tile", lambda level, r, c: fetched.append((r, c)))
    tiles.load_tiles(ext, 12)
    want = {(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)}
    assert sorted(fetched) == sorted(want)


def test_tiles_are_decoded_on_the_calling_thread(offline_tiles, monkeypatch):
    import threading

    threads = set()
    real = tiles.decode_tile

    def spy(*args, **kwargs):
        threads.add(threading.get_ident())
        return real(*args, **kwargs)

    monkeypatch.setattr(tiles, "decode_tile", spy)
    e, n = offline_tiles
    assert tiles.load_tiles(Extent(e - 600, n - 600, e + 600, n + 600), 12)
    assert threads == {threading.get_ident()}


def test_decode_places_feature_in_metres(offline_tiles):
    cx, cy = offline_tiles
    col, row, _, _ = mml_source.tile_range(Extent(cx, cy, cx, cy), 12)
    data = tiles.fetch_tile(12, row, col)
    assert data
    feats = tiles.decode_tile(data, 12, row, col)
    assert feats
    tile_m = 256 * 8192 / 2**12
    minx = -548576 + col * tile_m
    miny = 8388608 - (row + 1) * tile_m
    eps = 1e-6
    for f in feats:
        assert f.geom_type in ("Point", "LineString", "Polygon")
        x0, y0, x1, y1 = f.geometry.bounds
        assert x0 >= minx - eps and x1 <= minx + tile_m + eps
        assert y0 >= miny - eps and y1 <= miny + tile_m + eps
    layers = {f.layer for f in feats}
    assert {"korkeus", "liikenne", "nimisto"} <= layers


def test_fetch_404_is_empty(monkeypatch):
    monkeypatch.setattr(tiles._session, "get", lambda *a, **k: _resp(404))
    assert tiles.fetch_tile(12, 1, 1) is None
    monkeypatch.setattr(tiles, "fetch_tile", lambda *a: None)
    assert tiles.load_tiles(Extent(371000, 6687000, 372000, 6688000), 12) == []


def test_fetch_error_hides_key(monkeypatch):
    monkeypatch.setattr(tiles._session, "get", lambda *a, **k: _resp(503))
    with pytest.raises(MMLError) as err:
        tiles.fetch_tile(12, 3322, 1797)
    assert "test-key" not in str(err.value)
    assert "12/" in str(err.value)


def test_too_many_tiles():
    with pytest.raises(MMLError):
        tiles.load_tiles(Extent(360000, 6680000, 390000, 6710000), 12)


def test_decode_orientation_y_up():
    # pixel (10, 10) is near the tile's bottom-left, (10, 4000) near its top-left
    data = mapbox_vector_tile.encode(
        [
            {
                "name": "t",
                "features": [
                    {"geometry": "POINT(10 10)", "properties": {"k": "low"}},
                    {"geometry": "POINT(10 4000)", "properties": {"k": "high"}},
                ],
            }
        ],
        default_options={"extents": 4096},
    )
    level, row, col = 12, 3322, 1797
    tile_m = 256 * 8192 / 2**level
    minx = -548576 + col * tile_m
    miny = 8388608 - (row + 1) * tile_m
    pts = {f.props["k"]: f.geometry for f in tiles.decode_tile(data, level, row, col)}
    k = tile_m / 4096
    assert pts["low"].x == pytest.approx(minx + 10 * k)
    assert pts["low"].y == pytest.approx(miny + 10 * k)
    assert pts["high"].y == pytest.approx(miny + 4000 * k)
    assert pts["high"].y > pts["low"].y


def test_decode_garbage_is_mml_error():
    with pytest.raises(MMLError) as err:
        tiles.decode_tile(b"\xff\xfe not a tile", 12, 3322, 1797)
    assert "12/3322/1797" in str(err.value)


def _decode_one(wkt, level=12, row=3322, col=1797):
    """Encode one polygon (tile units, y up) and decode it; also return a tile->metres map."""
    data = mapbox_vector_tile.encode(
        [{"name": "a", "features": [{"geometry": wkt, "properties": {"mtk_id": 1}}]}],
        default_options={"extents": 4096},
    )
    tile_m = 256 * 8192 / 2**level
    minx = -548576 + col * tile_m
    miny = 8388608 - (row + 1) * tile_m
    k = tile_m / 4096

    def at(x, y):
        return Point(minx + x * k, miny + y * k)

    return tiles.decode_tile(data, level, row, col), at


def test_decode_keeps_lobes_joined_along_the_buffer():
    # Real MML pattern: a lake reaching into this tile in two lobes, written as
    # one ring that runs back over itself along the bottom buffer line (y=-16).
    # make_valid turns it into MultiPolygon + LineString; dropping that left
    # straight, outlined lake edges at the tile seam.
    ring = "POLYGON((-16 300, 600 -16, 2300 -16, 2300 300, 3990 300, 3990 -16, -16 -16, -16 300))"
    feats, at = _decode_one(ring)
    assert len(feats) == 1
    g = feats[0].geometry
    assert g.contains(at(100, 100))  # left lobe
    assert g.contains(at(3000, 150))  # right lobe
    assert not g.contains(at(1500, 100))  # land between the lobes


def test_decode_keeps_hole_touching_the_buffer():
    # A hole sharing a stretch of the exterior's buffer edge is invalid; the
    # repair must keep it a hole (linework repair filled it in).
    poly = (
        "POLYGON((-16 -16, 2000 -16, 2000 2000, -16 2000, -16 -16),"
        " (500 -16, 500 1000, 1500 1000, 1500 -16, 500 -16))"
    )
    feats, at = _decode_one(poly)
    assert len(feats) == 1
    g = feats[0].geometry
    assert g.contains(at(200, 500))
    assert not g.contains(at(1000, 500))


def test_keep_drops_features_before_they_are_built(offline_tiles):
    from fastmap.vector.style import StyleLayer

    e, n = offline_tiles
    ext = Extent(e - 300, n - 300, e + 300, n + 300)
    every = tiles.load_tiles(ext, 12)
    seen = []

    class Recording(tiles.FeatureFilter):
        def __call__(self, layer, props, geom_type):
            seen.append((layer, geom_type))
            return super().__call__(layer, props, geom_type)

    korkeus = StyleLayer("k", "line", "korkeus", 0, 24, None)
    only = tiles.load_tiles(ext, 12, keep=Recording({"korkeus": [korkeus]}, 13.5))
    assert only and all(f.layer == "korkeus" for f in only)
    assert len(only) == sum(1 for f in every if f.layer == "korkeus")
    # other tile layers are skipped whole, before their features are read
    assert seen and {layer for layer, _ in seen} == {"korkeus"}
    assert {gt for _, gt in seen} <= {"Point", "LineString", "Polygon"}


def test_feature_order_does_not_depend_on_download_order(offline_tiles, monkeypatch):
    import random
    import time

    e, n = offline_tiles
    ext = Extent(e - 600, n - 600, e + 600, n + 600)
    first = [(f.layer, f.props.get("mtk_id")) for f in tiles.load_tiles(ext, 12)]
    real = tiles.fetch_tile

    def slow_random(level, row, col):
        time.sleep(random.random() * 0.02)  # tiles finish in a shuffled order
        return real(level, row, col)

    monkeypatch.setattr(tiles, "fetch_tile", slow_random)
    again = [(f.layer, f.props.get("mtk_id")) for f in tiles.load_tiles(ext, 12)]
    assert again == first
