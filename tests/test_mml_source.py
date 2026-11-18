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
    assert img.mode == "P"
    assert abs(img.size[0] - 950) <= 1
    assert abs(img.size[1] - 1385) <= 1
    assert len(calls) > 0


class _FakeResp:
    status_code = 200

    def __init__(self, content: bytes):
        self.content = content

    def close(self):
        pass


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
    monkeypatch.setattr(mml_source._session, "get", fake_get)
    fetch_wmts_tile(x=1243, y=802, level=11, layer="maastokartta")
    assert "maastokartta/default/ETRS-TM35FIN/11/802/1243.png" in seen["url"]


def test_transparent_tiles_composite_to_white(monkeypatch):
    """No-data voids must print white, not black."""
    transparent = Image.new("RGBA", (256, 256), (0, 0, 0, 0))

    def fake_get(url, headers=None, timeout=None):
        return _FakeResp(_png_bytes(transparent))

    monkeypatch.setattr(mml_source, "MML_API_KEY", "k")
    monkeypatch.setattr(mml_source._session, "get", fake_get)
    img = fetch_wmts_tile(0, 0, 8, "maastokartta")
    assert img.getpixel((128, 128)) == (255, 255, 255)


def test_render_skips_wms_when_unconfigured(monkeypatch):
    """Without MML_WMS_URL there is no WMS attempt at all."""
    monkeypatch.setattr(mml_source, "MML_WMS_URL", "")
    hits = []

    def fake_get(url, **kw):
        hits.append(url)
        raise AssertionError("no HTTP expected")

    monkeypatch.setattr(mml_source._session, "get", fake_get)
    monkeypatch.setattr(mml_source, "fetch_wmts_mosaic", lambda *a, **k: "MOSAIC")
    assert render_extent_image(OTANIEMI, 100, 100) == "MOSAIC"
    assert not hits


SECRET = "s3cr3t-api-key"


def test_tile_http_error_does_not_leak_api_key(monkeypatch):
    resp = _FakeResp(b"")
    resp.status_code = 500

    monkeypatch.setattr(mml_source, "MML_API_KEY", SECRET)
    monkeypatch.setattr(mml_source._session, "get", lambda url, **kw: resp)
    with pytest.raises(mml_source.MMLError) as info:
        fetch_wmts_tile(x=1243, y=802, level=11, layer="maastokartta")
    assert SECRET not in str(info.value)
    assert "500" in str(info.value)


def test_tile_network_error_does_not_leak_api_key(monkeypatch):
    import requests

    def boom(url, **kw):
        # requests puts the full URL, query string included, in its messages
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    monkeypatch.setattr(mml_source, "MML_API_KEY", SECRET)
    monkeypatch.setattr(mml_source._session, "get", boom)
    with pytest.raises(mml_source.MMLError) as info:
        fetch_wmts_tile(x=1243, y=802, level=11, layer="maastokartta")
    assert SECRET not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_wms_network_error_does_not_leak_api_key(monkeypatch):
    import requests

    def boom(url, **kw):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    monkeypatch.setattr(mml_source, "MML_API_KEY", SECRET)
    monkeypatch.setattr(mml_source, "MML_WMS_URL", "https://wms.example/")
    monkeypatch.setattr(mml_source._session, "get", boom)
    with pytest.raises(mml_source.MMLError) as info:
        mml_source.fetch_wms_image(OTANIEMI, 100, 100)
    assert SECRET not in str(info.value)


# --- Retries, tested through urllib3 against a real local HTTP server ------


class _ScriptedServer:
    """Local HTTP server answering each request from a script of
    ``(status, headers, delay_s)``; the last entry repeats."""

    def __init__(self, script):
        import http.server
        import threading

        self.script = list(script)
        self.hits = 0
        outer = self
        body = _png_bytes(Image.new("RGB", (256, 256)))

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits += 1
                status, headers, delay = outer.script[min(outer.hits, len(outer.script)) - 1]
                threading.Event().wait(delay)  # not time.sleep: tests patch it
                payload = body if status == 200 else b"error"
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except OSError:
                    pass  # client gave up (timeout tests)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True  # don't join a handler still "hanging"
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def mml_server(monkeypatch):
    """Point the WMTS/WMS URLs at a scripted server; record backoff sleeps."""
    import urllib3.util.retry

    servers = []
    sleeps = []
    monkeypatch.setattr(mml_source, "MML_API_KEY", SECRET)
    monkeypatch.setattr(urllib3.util.retry.time, "sleep", sleeps.append)

    def start(*script):
        server = _ScriptedServer(script)
        servers.append(server)
        monkeypatch.setattr(mml_source, "MML_WMTS_URL", server.url + "/{layer}/{z}/{y}/{x}.png")
        monkeypatch.setattr(mml_source, "MML_WMS_URL", server.url + "/wms")
        server.sleeps = sleeps
        return server

    yield start
    for server in servers:
        server.close()


def _ok():
    return (200, {"Content-Type": "image/png"}, 0)


def _err(code, **headers):
    return (code, headers, 0)


def _tile():
    return fetch_wmts_tile(x=1, y=2, level=11, layer="maastokartta")


def test_tile_retries_server_errors_then_succeeds(mml_server):
    server = mml_server(_err(503), _err(500), _ok())
    assert _tile().size == (256, 256)
    assert server.hits == 3
    assert server.sleeps == [1.0]  # urllib3: no wait before the 1st retry, 1 s before the 2nd


def test_tile_gives_up_after_three_attempts_naming_the_status(mml_server):
    server = mml_server(_err(502))
    with pytest.raises(mml_source.MMLError, match="502") as info:
        _tile()
    assert server.hits == 3
    assert "maastokartta 11/2/1" in str(info.value)
    assert SECRET not in str(info.value)


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_tile_client_errors_are_not_retried(mml_server, code):
    server = mml_server(_err(code))
    with pytest.raises(mml_source.MMLError, match=str(code)):
        _tile()
    assert server.hits == 1


def test_rate_limit_honours_retry_after(mml_server):
    server = mml_server(_err(429, **{"Retry-After": "3"}), _ok())
    _tile()
    assert server.hits == 2
    assert server.sleeps == [3.0]


def test_rate_limit_retry_after_is_capped(mml_server):
    """A huge Retry-After must not park a render worker for minutes."""
    server = mml_server(_err(429, **{"Retry-After": "3600"}), _ok())
    _tile()
    assert server.sleeps == [mml_source.MAX_RETRY_AFTER_S]


def test_wms_is_retried_too(mml_server):
    server = mml_server(_err(503), _ok())
    img = mml_source.fetch_wms_image(OTANIEMI, 256, 256)
    assert img.size == (256, 256)
    assert server.hits == 2


def test_read_timeout_is_not_retried(mml_server, monkeypatch):
    """When MML stops answering, fail after one read timeout, not three."""
    monkeypatch.setattr(mml_source, "TILE_TIMEOUT", (2, 0.2))
    server = mml_server((200, {}, 1.0))
    with pytest.raises(mml_source.MMLError) as info:
        _tile()
    assert server.hits == 1
    assert SECRET not in str(info.value)


def test_session_uses_a_short_connect_timeout():
    connect, read = mml_source.TILE_TIMEOUT
    assert connect <= 5 < read
