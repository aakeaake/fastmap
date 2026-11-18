import io
import re
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fastmap.main import app

client = TestClient(app)


def _fake_render(extent, width_px, height_px, layer="maastokartta"):
    return Image.new("RGB", (width_px, height_px), (255, 0, 0))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Patch the raster source; everything downstream runs for real."""
    monkeypatch.setattr("fastmap.services.pdf_generator.render_extent_image", _fake_render)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200


def test_generate_map_bbox_ok():
    payload = {
        "bbox": {"minx": 428100, "miny": 6665230, "maxx": 431900, "maxy": 6670770},
        "scale": 20000,
        "paper_size": "A4",
        "orientation": "portrait",
    }
    resp = client.post("/generate-map", json=payload)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "fastmap_A4portrait_20000" in resp.headers["content-disposition"]
    assert resp.content[:5] == b"%PDF-"


def test_generate_map_center_scale_ok():
    payload = {
        "center_x": 430000,
        "center_y": 6668000,
        "scale": 25000,
        "paper_size": "A4",
        "orientation": "landscape",
    }
    resp = client.post("/generate-map", json=payload)
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"
    assert "25000" in resp.headers["content-disposition"]


def test_missing_location_is_422():
    resp = client.post("/generate-map", json={"scale": 20000})
    assert resp.status_code == 422


def test_bad_paper_size_is_422():
    resp = client.post(
        "/generate-map",
        json={
            "center_x": 430000,
            "center_y": 6668000,
            "scale": 20000,
            "paper_size": "Letter",
        },
    )
    assert resp.status_code == 422


def test_negative_bbox_is_422():
    resp = client.post(
        "/generate-map",
        json={
            "bbox": {"minx": 500000, "miny": 6000000, "maxx": 400000, "maxy": 6100000},
            "scale": 20000,
        },
    )
    assert resp.status_code == 422


def test_tile_proxy_validates_layer(monkeypatch):
    # no network needed: invalid layer must be rejected before fetching
    resp = client.get("/api/nls-tiles/8/119/210.png", params={"layer": "nope"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------


def _batch_map(i: int) -> dict:
    return {
        "bbox": {
            "minx": 428100 + i * 20000,
            "miny": 6665230,
            "maxx": 431900 + i * 20000,
            "maxy": 6670770,
        },
        "scale": 20000,
        "paper_size": "A4" if i % 2 == 0 else "A3",
        "orientation": "portrait" if i % 2 == 0 else "landscape",
        "title": f"Koe {i + 1}",
    }


def test_generate_batch_pdf_mixed_pages():
    resp = client.post(
        "/generate-maps-batch", json={"output": "pdf", "maps": [_batch_map(0), _batch_map(1)]}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert re.fullmatch(
        r'attachment; filename="fastmap_2pages_\d{12}\.pdf"',
        resp.headers["content-disposition"],
    )
    assert resp.content[:5] == b"%PDF-"
    pages = re.findall(rb"/Type\s*/Page(?![A-Za-z])", resp.content)
    assert len(pages) == 2


def test_generate_batch_zip_members_are_pdfs():
    resp = client.post(
        "/generate-maps-batch", json={"output": "zip", "maps": [_batch_map(0), _batch_map(1)]}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert re.fullmatch(
        r'attachment; filename="fastmap_2maps_\d{12}\.zip"',
        resp.headers["content-disposition"],
    )

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert len(names) == 2
    for name in names:
        assert zf.read(name)[:5] == b"%PDF-"


def test_batch_empty_map_list_is_422():
    resp = client.post("/generate-maps-batch", json={"maps": []})
    assert resp.status_code == 422


def test_batch_over_limit_is_422():
    resp = client.post("/generate-maps-batch", json={"maps": [_batch_map(0)] * 26})
    assert resp.status_code == 422


def test_slug_normalises_filenames():
    from fastmap.api.routes import _slug

    assert _slug("Koli itä") == "Koli_it"
    assert _slug("  My Map!  ") == "My_Map"
    assert _slug("") == "kartta"
    assert _slug("a" * 100) == "a" * 40


# ---------------------------------------------------------------------------
# Async generation
# ---------------------------------------------------------------------------


def _poll_until(job_id: str, max_polls: int = 50, delay: float = 0.1) -> dict:
    """Poll /map-status until done or error. Returns the final status dict."""
    for _ in range(max_polls):
        resp = client.get(f"/map-status/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(delay)
    raise AssertionError(f"Job {job_id} did not finish in {max_polls * delay:.1f}s")


def _single_payload(**overrides) -> dict:
    base = {
        "bbox": {"minx": 428100, "miny": 6665230, "maxx": 431900, "maxy": 6670770},
        "paper_size": "A4",
        "orientation": "portrait",
    }
    base.update(overrides)
    return base


def test_async_single_returns_job_id():
    resp = client.post("/generate-map-async", json=_single_payload())
    assert resp.status_code == 200
    assert "job_id" in resp.json()


def test_async_single_poll_and_download():
    resp = client.post("/generate-map-async", json=_single_payload())
    job_id = resp.json()["job_id"]

    result = _poll_until(job_id)
    assert result["status"] == "done"
    assert "download_url" in result
    assert "filename" in result

    dr = client.get(result["download_url"])
    assert dr.status_code == 200
    assert dr.content[:5] == b"%PDF-"
    assert result["filename"].endswith(".pdf")


def test_async_single_422_bad_input():
    resp = client.post("/generate-map-async", json={"scale": 20000})
    assert resp.status_code == 422


def test_async_single_status_404_unknown_job():
    resp = client.get("/map-status/nonexistent123")
    assert resp.status_code == 404


def test_async_single_download_404_unknown_job():
    resp = client.get("/map-download/nonexistent123")
    assert resp.status_code == 404


def test_async_batch_returns_job_id():
    resp = client.post(
        "/generate-maps-batch-async",
        json={"output": "zip", "maps": [_single_payload(), _single_payload()]},
    )
    assert resp.status_code == 200
    assert "job_id" in resp.json()


def test_async_batch_zip_poll_and_download():
    resp = client.post(
        "/generate-maps-batch-async",
        json={"output": "zip", "maps": [_batch_map(0), _batch_map(1)]},
    )
    job_id = resp.json()["job_id"]
    result = _poll_until(job_id)
    assert result["status"] == "done"

    dr = client.get(result["download_url"])
    assert dr.status_code == 200
    assert result["filename"].endswith(".zip")

    zf = zipfile.ZipFile(io.BytesIO(dr.content))
    names = zf.namelist()
    assert len(names) == 2
    for name in names:
        assert zf.read(name)[:5] == b"%PDF-"


def test_async_batch_pdf_poll_and_download():
    resp = client.post(
        "/generate-maps-batch-async",
        json={"output": "pdf", "maps": [_batch_map(0), _batch_map(1)]},
    )
    job_id = resp.json()["job_id"]
    result = _poll_until(job_id)
    assert result["status"] == "done"

    dr = client.get(result["download_url"])
    assert dr.status_code == 200
    assert dr.content[:5] == b"%PDF-"
    pages = re.findall(rb"/Type\s*/Page(?![A-Za-z])", dr.content)
    assert len(pages) == 2


def test_async_batch_empty_maps_422():
    resp = client.post("/generate-maps-batch-async", json={"maps": []})
    assert resp.status_code == 422


def test_app_version_matches_package():
    from importlib.metadata import version

    assert app.version == version("fastmap")


def test_version_fallback_when_not_installed(monkeypatch):
    import importlib
    import importlib.metadata as md

    import fastmap

    def boom(name):
        raise md.PackageNotFoundError(name)

    monkeypatch.setattr(md, "version", boom)
    importlib.reload(fastmap)
    assert fastmap.__version__ == "0.0.0+unknown"
    monkeypatch.undo()
    importlib.reload(fastmap)


def test_tile_proxy_network_error_is_502_without_key(monkeypatch):
    import requests

    from fastmap.api import routes

    def boom(url, **kw):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}?api-key=test-key")

    monkeypatch.setattr(routes.requests, "get", boom)
    resp = client.get("/api/nls-tiles/8/119/210.png", params={"layer": "maastokartta"})
    assert resp.status_code == 502
    assert "test-key" not in resp.text


def test_async_job_error_does_not_leak_key(monkeypatch):
    import requests

    from fastmap.services import mml_source

    def boom(url, **kw):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    # Undo the autouse raster fake so the real tile fetcher runs
    monkeypatch.setattr(
        "fastmap.services.pdf_generator.render_extent_image", mml_source.render_extent_image
    )
    monkeypatch.setattr(mml_source, "MML_API_KEY", "test-key")
    monkeypatch.setattr(mml_source._session, "get", boom)
    job = client.post(
        "/generate-map-async",
        json={"center_x": 385000, "center_y": 6672000, "scale": 50000},
    ).json()
    status = _poll_until(job["job_id"])
    assert status["status"] == "error"
    assert "test-key" not in status["error"]


def test_gpx_points_with_elevation_are_accepted():
    """GPS tracks carry [x, y, elevation(, time)]; only x and y are used."""
    from fastmap.schemas.map_request import MapRequest

    req = MapRequest(
        center_x=385000,
        center_y=6672000,
        scale=50000,
        gpx_routes=[[[385000, 6672000, 12.5], [386000, 6673000, 13.0, 1700000000]]],
    )
    assert req.gpx_routes == [[[385000, 6672000], [386000, 6673000]]]


def test_gpx_point_needs_two_coordinates():
    from pydantic import ValidationError

    from fastmap.schemas.map_request import MapRequest

    with pytest.raises(ValidationError):
        MapRequest(center_x=385000, center_y=6672000, scale=50000, gpx_routes=[[[385000]]])


def test_generate_map_with_elevation_gpx_ok():
    resp = client.post(
        "/generate-map",
        json={
            "center_x": 385000,
            "center_y": 6672000,
            "scale": 50000,
            "gpx_routes": [[[384000, 6671000, 10], [386000, 6673000, 11]]],
        },
    )
    assert resp.status_code == 200
    assert resp.content[:5] == b"%PDF-"


@pytest.mark.parametrize("color", ["red", "#fff", "#12345g", "ff00ff", "#ff00ff00"])
def test_bad_gpx_color_is_422(color):
    resp = client.post(
        "/generate-map",
        json={"center_x": 385000, "center_y": 6672000, "scale": 50000, "gpx_color": color},
    )
    assert resp.status_code == 422


def test_gpx_color_accepts_any_case_hex():
    resp = client.post(
        "/generate-map",
        json={
            "center_x": 385000,
            "center_y": 6672000,
            "scale": 50000,
            "gpx_color": "#A1b2C3",
            "gpx_routes": [[[384000, 6671000], [386000, 6673000]]],
        },
    )
    assert resp.status_code == 200


def test_attribution_endpoint_matches_pdf_text():
    from fastmap.services.pdf_generator import attribution

    resp = client.get("/api/attribution")
    assert resp.status_code == 200
    assert resp.json() == {"text": attribution()}


@pytest.fixture
def full_queue(monkeypatch):
    """A job store with no free slots, as when the server is saturated."""
    from fastmap.api import routes
    from fastmap.services.jobs import JobStore

    monkeypatch.setattr(routes, "jobs", JobStore(workers=1, max_pending=0, ttl_s=60))


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/generate-map", _single_payload()),
        ("/generate-map-async", _single_payload()),
        ("/generate-maps-batch", {"maps": [_single_payload()]}),
        ("/generate-maps-batch-async", {"maps": [_single_payload()]}),
    ],
)
def test_busy_server_answers_503_with_retry_after(full_queue, path, body):
    resp = client.post(path, json=body)
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "30"
    assert "uudelleen" in resp.json()["detail"]


def test_second_download_of_a_job_is_404():
    job_id = client.post("/generate-map-async", json=_single_payload()).json()["job_id"]
    url = _poll_until(job_id)["download_url"]
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 404


def test_download_while_pending_is_409_and_keeps_the_job(monkeypatch):
    import threading

    gate = threading.Event()

    def slow_render(extent, width_px, height_px, layer="maastokartta"):
        gate.wait(5)
        return Image.new("RGB", (width_px, height_px), (255, 0, 0))

    monkeypatch.setattr("fastmap.services.pdf_generator.render_extent_image", slow_render)
    job_id = client.post("/generate-map-async", json=_single_payload()).json()["job_id"]
    assert client.get(f"/map-download/{job_id}").status_code == 409
    gate.set()
    assert _poll_until(job_id)["status"] == "done"  # still there after the 409
    assert client.get(f"/map-download/{job_id}").status_code == 200


def test_failed_zip_write_leaves_no_temp_files(tmp_path, monkeypatch):
    import tempfile

    from fastmap.api import routes

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    class BrokenZip(zipfile.ZipFile):
        def write(self, *a, **kw):
            raise OSError("disk full")

    monkeypatch.setattr(routes.zipfile, "ZipFile", BrokenZip)
    body = {"output": "zip", "maps": [_single_payload(), _single_payload()]}
    with pytest.raises(OSError, match="disk full"):
        client.post("/generate-maps-batch", json=body)
    assert list(tmp_path.iterdir()) == []


def test_app_shutdown_stops_the_job_store(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from fastmap.api import routes
    from fastmap.services import mml_source
    from fastmap.services.jobs import JobStore

    store = JobStore(workers=1, max_pending=5, ttl_s=60)
    tiles = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(routes, "jobs", store)
    monkeypatch.setattr(mml_source, "_tile_pool", tiles)
    with TestClient(app):
        pass  # startup + shutdown
    with pytest.raises(RuntimeError):
        store.submit(lambda: {"path": None, "filename": "x"})
    with pytest.raises(RuntimeError):  # queued tile downloads don't delay exit either
        tiles.submit(lambda: None)
