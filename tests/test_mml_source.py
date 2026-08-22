import pytest

from fastmap.services import mml_source
from fastmap.services.mml_source import (
    Extent,
    build_wms_url,
    fetch_wmts_mosaic,
    pick_wmts_level,
    tile_range,
    wmts_resolution,
)

OTANIEMI = Extent(428100, 6665230, 431900, 6670770)


def test_wmts_resolution_halves_per_level():
    assert wmts_resolution(0) == pytest.approx(8192.0)
    assert wmts_resolution(1) == pytest.approx(4096.0)
    assert wmts_resolution(14) == pytest.approx(0.5)


def test_pick_level_closest():
    # 32 m/px is exactly level 8
    assert pick_wmts_level(32.0) == 8
    # between levels 11 (4.0) and 12 (2.0): 3.0 equidistant -> finer wins
    assert pick_wmts_level(3.0) == 12
    assert pick_wmts_level(100.0) in (5, 6)


def test_tile_range_known_values():
    # level 12: res = 2 m/px, tiles are 512 m wide
    cols = tile_range(OTANIEMI, 12)
    col_min, row_min, col_max, row_max = cols
    assert col_max >= col_min and row_max >= row_min
    # sanity against grid geometry
    res = wmts_resolution(12)
    ts = 256 * res
    ox, oy = mml_source.WMTS_ORIGIN
    assert OTANIEMI.minx >= ox + col_min * ts
    assert OTANIEMI.maxx <= ox + (col_max + 1) * ts
    assert OTANIEMI.maxy <= oy - row_min * ts
    assert OTANIEMI.miny >= oy - (row_max + 1) * ts


def test_build_wms_url_contains_params(monkeypatch):
    monkeypatch.setattr(mml_source, "MML_API_KEY", "secret")
    url = build_wms_url(OTANIEMI, 2244, 3272, "maastokartta")
    for expected in (
        "service=WMS",
        "version=1.1.1",
        "request=GetMap",
        "layers=maastokartta",
        "srs=EPSG:3067",
        "bbox=428100,6665230",
        "width=2244",
        "height=3272",
        "api-key=secret",
    ):
        assert expected in url


def test_fetch_wmts_mosaic_offline(monkeypatch):
    """Stitching math with a fake tile source - no network."""
    calls = []

    def fake_tile(x, y, level, layer):
        calls.append((x, y, level))
        from PIL import Image

        img = Image.new("RGB", (256, 256), (x, y, level))
        return img

    monkeypatch.setattr(mml_source, "fetch_wmts_tile", fake_tile)
    img = fetch_wmts_mosaic(OTANIEMI, 950, 1385)
    assert img.size == (950, 1385)
    assert len(calls) > 0
