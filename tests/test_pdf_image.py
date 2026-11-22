import shutil
import subprocess

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from fastmap.services.pdf_image import draw_palette_image


def _palette_image():
    rgb = Image.new("RGB", (40, 30), (255, 255, 255))
    for x in range(40):
        for y in range(30):
            rgb.putpixel(
                (x, y), [(255, 255, 255), (200, 120, 20), (30, 90, 200)][(x // 5 + y // 7) % 3]
            )
    return rgb, rgb.convert("P", palette=Image.ADAPTIVE, colors=3)


def test_palette_image_is_embedded_indexed(tmp_path):
    _, img = _palette_image()
    path = tmp_path / "p.pdf"
    c = canvas.Canvas(str(path), pagesize=(40, 30))
    draw_palette_image(c, img, 0, 0, 40, 30)
    c.showPage()
    c.save()
    data = path.read_bytes()
    assert b"/Indexed /DeviceRGB 2 (" in data
    assert data.count(b"/Subtype /Image") == 1


def test_same_image_twice_is_stored_once(tmp_path):
    _, img = _palette_image()
    path = tmp_path / "p.pdf"
    c = canvas.Canvas(str(path), pagesize=(80, 30))
    draw_palette_image(c, img, 0, 0, 40, 30)
    draw_palette_image(c, img, 40, 0, 40, 30)
    c.save()
    assert path.read_bytes().count(b"/Subtype /Image") == 1


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="needs pdftoppm")
def test_indexed_image_renders_the_exact_pixels(tmp_path):
    _, img = _palette_image()
    rgb = img.convert("RGB")  # the palette image's own colours
    path = tmp_path / "p.pdf"
    c = canvas.Canvas(str(path), pagesize=(40, 30))
    draw_palette_image(c, img, 0, 0, 40, 30)
    c.save()
    # 72 dpi: one PDF point per image pixel
    subprocess.run(
        ["pdftoppm", "-r", "72", "-png", "-singlefile", str(path), str(tmp_path / "r")], check=True
    )
    out = Image.open(tmp_path / "r.png").convert("RGB")
    assert out.size == rgb.size
    # block centres (edges may be resampled by the renderer)
    centres = [(x, y) for x in range(2, 40, 5) for y in range(3, 30, 7)]
    assert [out.getpixel(p) for p in centres] == [rgb.getpixel(p) for p in centres]


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="needs pdftoppm")
def test_colour_table_survives_every_byte_value(tmp_path):
    # 256 colours whose table holds every byte, "(", ")" and "\\" included
    img = Image.new("P", (16, 16))
    img.putpalette([v for i in range(256) for v in (i, 255 - i, (i * 7) % 256)])
    img.putdata(range(256))
    rgb = img.convert("RGB")
    path = tmp_path / "p.pdf"
    c = canvas.Canvas(str(path), pagesize=(160, 160))
    draw_palette_image(c, img, 0, 0, 160, 160)
    c.save()
    subprocess.run(
        ["pdftoppm", "-r", "72", "-png", "-singlefile", str(path), str(tmp_path / "r")], check=True
    )
    out = Image.open(tmp_path / "r.png").convert("RGB")
    centres = [(x, y) for x in range(16) for y in range(16)]
    assert [out.getpixel((10 * x + 5, 10 * y + 5)) for x, y in centres] == [
        rgb.getpixel(p) for p in centres
    ]
