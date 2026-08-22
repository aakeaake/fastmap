import io

import pytest
from PIL import Image

from fastmap.services import mml_source
from fastmap.services.mml_source import (
    Extent,
    build_wms_url,
    fetch_wmts_mosaic,
    fetch_wmts_tile,
    pick_wmts_level,
    render_extent_image,
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
    monkeypatch.setattr(mml_source, "MML_WMS_URL", "https://wms.example/")
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


class _FakeResp:
    status_code = 200

    def __init__(self, content: bytes):
        self.content = content


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_fetch_wmts_tile_url_is_z_row_col(monkeypatch):
    """Regression: MML WMTS REST path is {z}/{TileRow}/{TileCol}.png.

    Verified empirically against the live service (2026-08): tile
    12/3348/1810 decodes to Otaniemi only when 3348 is the row.
    """
    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen["url"] = url
        return _FakeResp(_png_bytes(Image.new("RGB", (256, 256))))

    monkeypatch.setattr(mml_source, "MML_API_KEY", "k")
    monkeypatch.setattr(mml_source.requests, "get", fake_get)
    fetch_wmts_tile(x=1243, y=802, level=11, layer="maastokartta")
    assert "maastokartta/default/ETRS-TM35FIN/11/802/1243.png" in seen["url"]


def test_transparent_tiles_composite_to_white(monkeypatch):
    """No-data voids must print white, not black."""
    transparent = Image.new("RGBA", (256, 256), (0, 0, 0, 0))

    def fake_get(url, headers=None, timeout=None):
        return _FakeResp(_png_bytes(transparent))

    monkeypatch.setattr(mml_source, "MML_API_KEY", "k")
    monkeypatch.setattr(mml_source.requests, "get", fake_get)
    img = fetch_wmts_tile(0, 0, 8, "maastokartta")
    assert img.getpixel((128, 128)) == (255, 255, 255)


def test_render_skips_wms_when_unconfigured(monkeypatch):
    """Without MML_WMS_URL there is no WMS attempt at all."""
    monkeypatch.setattr(mml_source, "MML_WMS_URL", "")
    hits = []

    def fake_get(url, **kw):
        hits.append(url)
        raise AssertionError("no HTTP expected")

    monkeypatch.setattr(mml_source.requests, "get", fake_get)
    monkeypatch.setattr(
        mml_source, "fetch_wmts_mosaic", lambda *a, **k: "MOSAIC"
    )
    assert render_extent_image(OTANIEMI, 100, 100) == "MOSAIC"
    assert not hits
