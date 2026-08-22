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
    monkeypatch.setattr(
        "fastmap.services.pdf_generator.render_extent_image", _fake_render
    )


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
    assert "fastmap_A4_portrait_1-20000" in resp.headers["content-disposition"]
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
    assert "1-25000" in resp.headers["content-disposition"]


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
