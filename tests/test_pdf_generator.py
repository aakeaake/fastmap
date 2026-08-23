import re

import pytest

from fastmap.services import pdf_generator
from fastmap.services.print_layout import Extent
from PIL import Image


def _fake_render(extent, width_px, height_px, layer="maastokartta"):
    return Image.new("RGB", (width_px, height_px), (200, 220, 200))


def test_generate_pdf_a4_exact_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pdf_generator, "render_extent_image", _fake_render
    )
    ext = Extent(428100, 6665230, 431900, 6670770)  # 3800 x 5540 m
    out = tmp_path / "a4.pdf"

    result = pdf_generator.generate_pdf(
        ext,
        paper_size="A4",
        orientation="portrait",
        dpi=300,
        margin_mm=10,
        out_pdf_path=str(out),
    )

    assert result.actual_scale == 20000
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"
    # A4 portrait page in points: 210 x 297 mm
    m = re.search(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", data)
    assert m
    w_pt, h_pt = float(m.group(1)), float(m.group(2))
    assert w_pt == pytest.approx(595.27, abs=0.5)
    assert h_pt == pytest.approx(841.89, abs=0.5)


def test_generate_pdf_landscape_actual_scale(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    from fastmap.services.print_layout import extent_for_center

    ext = extent_for_center(735000, 7560000, 50000, "A3", "landscape", 7)
    out = tmp_path / "a3.pdf"

    result = pdf_generator.generate_pdf(
        ext,
        paper_size="A3",
        orientation="landscape",
        out_pdf_path=str(out),
    )
    assert result.actual_scale == 50000
    assert out.stat().st_size > 1000


@pytest.mark.parametrize("mode", ["off", "vertical", "vertical_coords", "full", "full_coords"])
def test_generate_pdf_grid_modes(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    ext = Extent(428100, 6665230, 431900, 6670770)
    out = tmp_path / f"grid_{mode}.pdf"

    result = pdf_generator.generate_pdf(
        ext,
        paper_size="A4",
        orientation="portrait",
        margin_mm=10,
        grid_mode=mode,
        grid_spacing_m=1000,
        out_pdf_path=str(out),
    )
    assert result.actual_scale == 20000
    assert out.stat().st_size > 1000


def test_generate_pdf_with_title(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    ext = Extent(428100, 6665230, 431900, 6670770)
    out = tmp_path / "titled.pdf"

    result = pdf_generator.generate_pdf(
        ext,
        paper_size="A4",
        orientation="portrait",
        margin_mm=10,
        title="Test Map",
        out_pdf_path=str(out),
    )
    data = out.read_bytes()
    assert b"Test Map" in data


def test_generate_multi_pdf_mixed_sizes(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    ext_a4 = Extent(428100, 6665230, 431900, 6670770)
    ext_a3 = Extent(735000, 7560000, 745000, 7575000)
    out = tmp_path / "multi.pdf"

    items = [
        (ext_a4, {
            "paper_size": "A4", "orientation": "portrait",
            "layer": "maastokartta", "margin_mm": 10,
        }),
        (ext_a3, {
            "paper_size": "A3", "orientation": "landscape",
            "layer": "maastokartta", "margin_mm": 10,
        }),
    ]
    results = pdf_generator.generate_multi_pdf(items, str(out))
    assert len(results) == 2
    assert results[0].actual_scale == 20000
    assert results[1].actual_scale == 25000


def test_generate_pdf_to_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    ext = Extent(428100, 6665230, 431900, 6670770)

    result = pdf_generator.generate_pdf_to_temp(
        ext,
        paper_size="A4",
        orientation="portrait",
        margin_mm=10,
    )
    assert result.path.endswith(".pdf")
    assert result.actual_scale == 20000
    import os
    assert os.path.exists(result.path)
    os.remove(result.path)


def test_generate_pdf_with_gpx_route(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    ext = Extent(428100, 6665230, 431900, 6670770)
    out = tmp_path / "gpx.pdf"

    result = pdf_generator.generate_pdf(
        ext,
        paper_size="A4",
        orientation="portrait",
        margin_mm=10,
        gpx_routes=[[[429000, 6666000], [430000, 6668000], [431000, 6670000]]],
        gpx_color="#ff00ff",
        gpx_width=5,
        gpx_opacity=0.6,
        out_pdf_path=str(out),
    )
    assert result.actual_scale == 20000
    # Render to PNG and check for magenta pixels
    import subprocess
    subprocess.run(["pdftoppm", "-png", "-r", "100", str(out), str(tmp_path / "gpx")], check=True)
    from glob import glob
    from PIL import Image
    imgs = sorted(glob(str(tmp_path / "gpx-*.png")))
    assert len(imgs) == 1
    img = Image.open(imgs[0]).convert("RGB")
    px = img.load()
    w, h = img.size
    magenta = sum(
        1 for x in range(w) for y in range(h)
        if px[x, y][0] > 180 and px[x, y][1] < 100 and px[x, y][2] > 180
    )
    assert magenta > 100  # route should be visible
