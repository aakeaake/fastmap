from unittest.mock import MagicMock

import pytest

from fastmap.services import mml_source
from fastmap.services.mml_source import MMLError
from fastmap.services.print_layout import Extent
from fastmap.vector import tiles


def _resp(status):
    r = MagicMock()
    r.status_code = status
    r.content = b""
    return r


def test_tile_range_matches_raster_grid():
    ext = Extent(371000, 6687000, 372000, 6688000)
    c0, r0, c1, r1 = mml_source.tile_range(ext, 12)
    assert tiles.tile_range(ext, 12, pad=2) == (c0 - 2, r0 - 2, c1 + 2, r1 + 2)
    assert tiles.tile_range(ext, 12) == (c0 - 1, r0 - 1, c1 + 1, r1 + 1)


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
    buf = 0.1 * tile_m
    for f in feats:
        assert f.geom_type in ("Point", "LineString", "Polygon")
        x0, y0, x1, y1 = f.geometry.bounds
        assert x0 >= minx - buf and x1 <= minx + tile_m + buf
        assert y0 >= miny - buf and y1 <= miny + tile_m + buf
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
        tiles.fetch_tile(12, 3291, 1803)
    assert "test-key" not in str(err.value)
    assert "12/" in str(err.value)


def test_too_many_tiles():
    with pytest.raises(MMLError):
        tiles.load_tiles(Extent(360000, 6680000, 390000, 6710000), 12)
