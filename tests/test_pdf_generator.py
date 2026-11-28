import math
import re

import pytest
from PIL import Image

from fastmap.services import pdf_generator
from fastmap.services.print_layout import Extent


def _fake_render(extent, width_px, height_px, layer="maastokartta"):
    return Image.new("RGB", (width_px, height_px), (200, 220, 200))


def test_generate_pdf_a4_exact_geometry(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    ext = Extent(428100, 6665230, 431900, 6670770)  # 3800 x 5540 m
    out = tmp_path / "a4.pdf"

    result = pdf_generator.generate_pdf(
        ext,
        paper_size="A4",
        orientation="portrait",
        zoom_level=12,
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

    pdf_generator.generate_pdf(
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
        (
            ext_a4,
            {
                "paper_size": "A4",
                "orientation": "portrait",
                "layer": "maastokartta",
                "margin_mm": 10,
            },
        ),
        (
            ext_a3,
            {
                "paper_size": "A3",
                "orientation": "landscape",
                "layer": "maastokartta",
                "margin_mm": 10,
            },
        ),
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
        1
        for x in range(w)
        for y in range(h)
        if px[x, y][0] > 180 and px[x, y][1] < 100 and px[x, y][2] > 180
    )
    assert magenta > 100  # route should be visible


_STREAM = re.compile(rb"<<((?:[^<>]|<<[^<>]*>>)*)>>\s*stream\r?\n")
_LENGTH = re.compile(rb"/Length (\d+)(?!\d| \d+ R)")


def _page_content(data: bytes) -> bytes:
    """Decode the PDF's non-image streams so drawn text can be searched.

    Reads exactly ``/Length`` bytes and applies the declared filters; a stream
    that fails to decode raises instead of being skipped.
    """
    import base64
    import zlib

    decoders = {
        b"ASCII85Decode": lambda raw: base64.a85decode(raw.strip().removesuffix(b"~>")),
        b"FlateDecode": zlib.decompress,
    }
    out = []
    for m in _STREAM.finditer(data):
        head = m.group(1)
        if b"/Subtype /Image" in head:
            continue
        length = _LENGTH.search(head)
        assert length, f"stream without a direct /Length: {head!r}"
        raw = data[m.end() : m.end() + int(length.group(1))]
        for name in re.findall(rb"/(\w+Decode)", head):
            raw = decoders[name](raw)
        out.append(raw)
    return b"\n".join(out)


def _grid_pdf(tmp_path, monkeypatch, spacing, margin=10):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / f"grid_{spacing}.pdf"
    pdf_generator.generate_pdf(
        Extent(428100, 6665230, 431900, 6670770),
        paper_size="A4",
        orientation="portrait",
        margin_mm=margin,
        grid_mode="full_coords",
        grid_spacing_m=spacing,
        out_pdf_path=str(out),
    )
    return _page_content(out.read_bytes())


@pytest.mark.parametrize(
    ("value", "label"), [(385500, "3855"), (6672500, "66725"), (429000, "4290")]
)
def test_grid_label_is_coordinate_over_100(value, label):
    assert pdf_generator._grid_label(value) == label


def test_grid_labels_distinct_at_500m(tmp_path, monkeypatch):
    """Half-km lines must differ from whole-km ones, without decimals."""
    data = _grid_pdf(tmp_path, monkeypatch, 500)
    assert b"(4285)" in data and b"(4290)" in data
    assert b"." not in b"".join(re.findall(rb"\((\d[\d.]*)\) Tj", data))


def test_attribution_uses_render_date(tmp_path, monkeypatch):
    """The month must be the PDF's, not the server start's."""
    from datetime import datetime as real_datetime

    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2031, 3, 15)

    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    monkeypatch.setattr(pdf_generator, "datetime", FakeDatetime)
    out = tmp_path / "attr.pdf"
    pdf_generator.generate_pdf(
        Extent(428100, 6665230, 431900, 6670770),
        paper_size="A4",
        orientation="portrait",
        out_pdf_path=str(out),
    )
    assert b"03/2031" in _page_content(out.read_bytes())


def test_attribution_is_finnish_time(monkeypatch):
    """23:30 UTC on 30 Nov is already December in Helsinki."""
    from datetime import datetime as real_datetime
    from datetime import timezone

    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(pdf_generator, "datetime", FakeDatetime)
    assert pdf_generator.attribution().endswith("12/2026")


def test_multi_page_pdf_has_one_attribution_date(tmp_path, monkeypatch):
    """Pages must not disagree on the month when rendering crosses midnight."""
    from datetime import datetime as real_datetime

    months = iter(range(1, 13))

    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2031, next(months), 1)

    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    monkeypatch.setattr(pdf_generator, "datetime", FakeDatetime)
    page = {"paper_size": "A4", "orientation": "portrait"}
    ext = Extent(428100, 6665230, 431900, 6670770)
    out = tmp_path / "multi.pdf"
    pdf_generator.generate_multi_pdf([(ext, page), (ext, page)], str(out))
    data = _page_content(out.read_bytes())
    assert data.count(b"01/2031") == 2
    assert b"02/2031" not in data


@pytest.mark.parametrize("color", ["#fff", "red", "#12345g", "#ff00ff00", ""])
def test_generate_pdf_rejects_bad_color(tmp_path, monkeypatch, color):
    def no_render(*args, **kwargs):
        raise AssertionError("tiles fetched before the colour was checked")

    monkeypatch.setattr(pdf_generator, "render_extent_image", no_render)
    with pytest.raises(ValueError, match="colour"):
        pdf_generator.generate_pdf(
            Extent(428100, 6665230, 431900, 6670770),
            paper_size="A4",
            orientation="portrait",
            gpx_color=color,
            out_pdf_path=str(tmp_path / "x.pdf"),
        )


def test_parse_hex_color():
    assert pdf_generator._parse_hex_color("#FF0080") == (1.0, 0.0, 128 / 255)


@pytest.mark.parametrize(
    ("step_pt", "needed_pt", "expected"),
    [(20, 10, 1), (10, 10, 1), (6, 10, 2), (3, 10, 5), (1.5, 10, 10), (0.4, 10, 50)],
)
def test_label_every(step_pt, needed_pt, expected):
    assert pdf_generator._label_every(step_pt, needed_pt) == expected


def test_dense_half_km_grid_labels_only_whole_km(tmp_path, monkeypatch):
    """At 1:200 000, 500 m lines are 2.5 mm apart: label every km, not every line."""
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    from fastmap.services.print_layout import extent_for_center

    out = tmp_path / "dense.pdf"
    pdf_generator.generate_pdf(
        extent_for_center(430000, 6668000, 200000, "A4", "portrait", 10),
        paper_size="A4",
        orientation="portrait",
        margin_mm=10,
        zoom_level=8,
        grid_mode="full_coords",
        grid_spacing_m=500,
        out_pdf_path=str(out),
    )
    data = _page_content(out.read_bytes())
    assert b"(4300)" in data
    assert b"(4305)" not in data


def test_stream_length_regex_is_direct_only():
    """An indirect '/Length 12 0 R' must not be read as a length of 1."""
    assert _LENGTH.search(b"/Length 594 /Filter").group(1) == b"594"
    assert _LENGTH.search(b"/Length 12 0 R") is None


def test_multi_pdf_checks_every_page_before_fetching_tiles(tmp_path, monkeypatch):
    def no_render(*args, **kwargs):
        raise AssertionError("tiles fetched before all pages were checked")

    monkeypatch.setattr(pdf_generator, "render_extent_image", no_render)
    ext = Extent(428100, 6665230, 431900, 6670770)
    good = {"paper_size": "A4", "orientation": "portrait"}
    with pytest.raises(ValueError, match="colour"):
        pdf_generator.generate_multi_pdf(
            [(ext, good), (ext, {**good, "gpx_color": "red"})], str(tmp_path / "m.pdf")
        )
    with pytest.raises(ValueError, match="layer"):
        pdf_generator.generate_multi_pdf(
            [(ext, good), (ext, {**good, "layer": "nope"})], str(tmp_path / "m.pdf")
        )


def test_pdf_streams_skip_ascii85(tmp_path, monkeypatch):
    """ReportLab's ASCII85 runs in pure Python without its optional C
    extension and adds ~25 % to the file; binary Flate streams are standard."""
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / "plain.pdf"
    pdf_generator.generate_pdf(
        Extent(428100, 6665230, 431900, 6670770),
        paper_size="A4",
        orientation="portrait",
        title="Binary streams",
        out_pdf_path=str(out),
    )
    data = out.read_bytes()
    assert b"ASCII85Decode" not in data
    assert b"FlateDecode" in data
    assert b"Binary streams" in _page_content(data)  # still decodable text


def test_reportlab_uses_its_c_extension():
    """rl_accel roughly halves PDF build time; it's optional in ReportLab, so
    check it is installed rather than silently falling back to pure Python."""
    from reportlab.lib import rl_accel

    assert rl_accel.fp_str.__module__ == "_rl_accel"


# --- Footer line under the map ----------------------------------------------

from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase.pdfmetrics import stringWidth  # noqa: E402

from fastmap.services.print_layout import FOOTER_MM, format_scale_label  # noqa: E402

_TEXT_OP = re.compile(
    rb"(?:([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) cm\s+)?"
    rb"BT 1 0 0 1 ([-\d.]+) ([-\d.]+) Tm \(((?:\\.|[^\\)])*)\) Tj"
)


def _pdf_string(raw: bytes) -> str:
    """Decode a PDF literal string (octal and backslash escapes, cp1252)."""
    out = re.sub(
        rb"\\([0-7]{3}|.)",
        lambda m: bytes([int(m.group(1), 8)]) if len(m.group(1)) == 3 else m.group(1),
        raw,
    )
    return out.decode("cp1252")


def _text_ops(content: bytes) -> list[tuple[float, float, str, bool]]:
    """(x, y, text, rotated) for each drawn string, in page coordinates."""
    ops = []
    for m in _TEXT_OP.finditer(content):
        tx, ty = float(m.group(7)), float(m.group(8))
        text = _pdf_string(m.group(9))
        if m.group(1) is not None:  # inside a translate+rotate 'cm'
            a, b, c, d, e, f = (float(m.group(i)) for i in range(1, 7))
            ops.append((a * tx + c * ty + e, b * tx + d * ty + f, text, (a, b) == (0.0, 1.0)))
        else:
            ops.append((tx, ty, text, False))
    return ops


def _image_box(content: bytes) -> tuple[float, float, float, float]:
    m = re.search(rb"([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm\s+/FormXob", content)
    w, h, x, y = (float(v) for v in m.groups())
    return x, y, w, h


def _footer_pdf(tmp_path, monkeypatch, *, title="Test Map", margin=10.0, **kw):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / "footer.pdf"
    result = pdf_generator.generate_pdf(
        Extent(428100, 6665230, 431900, 6670770),
        paper_size="A4",
        orientation="portrait",
        margin_mm=margin,
        title=title,
        out_pdf_path=str(out),
        **kw,
    )
    return result, _page_content(out.read_bytes())


def test_attribution_text_is_short():
    assert re.fullmatch(r"© Maanmittauslaitos, CC BY 4\.0, \d\d/\d{4}", pdf_generator.attribution())


def test_map_sits_footer_height_above_the_margin(tmp_path, monkeypatch):
    _, content = _footer_pdf(tmp_path, monkeypatch)
    x, y, w, h = _image_box(content)
    assert (x, y) == pytest.approx((10 * mm, (10 + FOOTER_MM) * mm), abs=0.01)
    assert (w, h) == pytest.approx((190 * mm, (277 - FOOTER_MM) * mm), abs=0.01)


def test_footer_line_is_below_the_map_and_has_no_box(tmp_path, monkeypatch):
    result, content = _footer_pdf(tmp_path, monkeypatch)
    mx, my, mw, _ = _image_box(content)
    texts = {t: (x, y) for x, y, t, _ in _text_ops(content)}
    left = next(t for t in texts if t.startswith("Test Map · "))
    assert re.fullmatch(
        rf"Test Map · {format_scale_label(result.actual_scale)} · kok\. [+−]?\d+°", left
    )
    right = pdf_generator.attribution()
    assert right in texts
    for _x, y in (texts[left], texts[right]):
        assert 10 * mm <= y < my  # between the margin line and the map
    assert texts[left][0] == pytest.approx(mx, abs=0.01)
    assert texts[right][0] + stringWidth(right, "Courier", 7) == pytest.approx(mx + mw, abs=0.01)
    assert b" re f" not in content  # the white boxes behind on-map text are gone


def test_footer_without_title_shows_scale_and_correction(tmp_path, monkeypatch):
    result, content = _footer_pdf(tmp_path, monkeypatch, title=None)
    texts = [t for _, _, t, _ in _text_ops(content)]
    scale = re.escape(format_scale_label(result.actual_scale))
    assert any(re.fullmatch(rf"{scale} · kok\. [+−]?\d+°", t) for t in texts)


def test_long_title_is_shortened_not_overlapping(tmp_path, monkeypatch):
    _, content = _footer_pdf(tmp_path, monkeypatch, title="Pitkä otsikko " * 8)
    ops = {t: x for x, _, t, _ in _text_ops(content)}
    left = next(t for t in ops if t.startswith("Pitkä"))
    right = pdf_generator.attribution()
    # only the title is shortened; the scale is never cut
    assert re.fullmatch(r"Pitkä otsikko.*… · 1 : \d+ \d{3} · kok\. [+−]?\d+°", left)
    assert ops[left] + stringWidth(left, "Courier", 7) + 2 * mm <= ops[right] + 0.01


def test_every_batch_page_has_a_footer(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / "multi.pdf"
    page = {"paper_size": "A4", "orientation": "portrait"}
    a3 = {"paper_size": "A3", "orientation": "landscape"}
    ext = Extent(428100, 6665230, 431900, 6670770)
    pdf_generator.generate_multi_pdf([(ext, page), (ext, a3)], str(out))
    content = _page_content(out.read_bytes())
    assert content.count(b"Maanmittauslaitos") == 2


# --- Grid labels outside the map ----------------------------------------------


def _label_ops(content: bytes):
    """Grid label ops: (x, y, text, rotated) for all-digit strings."""
    return [op for op in _text_ops(content) if op[2].isdigit()]


def test_grid_labels_outside_the_map(tmp_path, monkeypatch):
    content = _grid_pdf(tmp_path, monkeypatch, 500)
    mx, my, mw, mh = _image_box(content)
    ops = _label_ops(content)
    east = [op for op in ops if not op[3]]
    north = [op for op in ops if op[3]]
    assert east and north
    for _x, y, text, _ in east:
        assert y > my + mh, text  # above the map's top edge
    for x, _y, text, _ in north:
        # rotated 90° anticlockwise, in the left margin: the baseline is left
        # of the map edge and the glyphs (5.5 pt tall) still end on the page
        assert 0 <= x - 5.5 and x < mx, text
    assert {t for *_, t, _ in north} >= {"66655", "66660"}


def test_grid_labels_fall_back_inside_with_small_margin(tmp_path, monkeypatch):
    content = _grid_pdf(tmp_path, monkeypatch, 500, margin=2)
    mx, my, mw, mh = _image_box(content)
    ops = _label_ops(content)
    assert ops and not any(rotated for *_, rotated in ops)
    for x, y, text, _ in ops:
        assert mx <= x <= mx + mw and my <= y <= my + mh, text


def test_grid_labels_skip_corners(tmp_path, monkeypatch):
    content = _grid_pdf(tmp_path, monkeypatch, 500)
    mx, my, mw, mh = _image_box(content)
    for x, y, text, rotated in _label_ops(content):
        width = stringWidth(text, "Courier", 5.5)
        if rotated:  # x, y is the label's start; it runs upward along the edge
            assert my <= y and y + width <= my + mh + 0.01, text
        else:
            assert mx <= x and x + width <= mx + mw + 0.01, text


def test_footer_text_sits_1mm_below_the_map(tmp_path, monkeypatch):
    """Little wasted space: ~1 mm between the map edge and the footer text."""
    from reportlab.pdfbase.pdfmetrics import getAscent

    _, content = _footer_pdf(tmp_path, monkeypatch)
    _, map_bottom, _, _ = _image_box(content)
    right = pdf_generator.attribution()
    baseline = next(y for _, y, t, _ in _text_ops(content) if t == right)
    text_top = baseline + getAscent("Courier", 7)
    assert map_bottom - text_top == pytest.approx(1 * mm, abs=0.25 * mm)


# ---------------------------------------------------------------------------
# Vector layer
# ---------------------------------------------------------------------------


def _vector_extent(centre, scale, paper="A4", orientation="portrait", margin=7.0):
    from fastmap.services.print_layout import extent_for_center

    return extent_for_center(centre[0], centre[1], scale, paper, orientation, margin)


def test_vector_layer_page_geometry(tmp_path, offline_tiles):
    extent = _vector_extent(offline_tiles, 25000)
    out = tmp_path / "v.pdf"
    result = pdf_generator.generate_pdf(
        extent, paper_size="A4", orientation="portrait", layer="maastokartta_vektori",
        title="Vektori", out_pdf_path=str(out),
    )  # fmt: skip
    data = out.read_bytes()
    assert b"/Subtype /Image" not in data
    assert result.actual_scale == 25000
    assert (result.width_px, result.height_px) == (0, 0)
    assert re.search(rb"/MediaBox \[ 0 0 595\.27\d* 841\.88\d* \]", data)
    texts = [t for _, _, t, _ in _text_ops(_page_content(data))]
    assert any("Vektori" in t and format_scale_label(25000) in t for t in texts)


def test_vector_with_grid_and_gpx(tmp_path, offline_tiles):
    cx, cy = offline_tiles
    extent = _vector_extent(offline_tiles, 25000)
    out = tmp_path / "v.pdf"
    pdf_generator.generate_pdf(
        extent, paper_size="A4", orientation="portrait", layer="maastokartta_vektori",
        grid_mode="full_coords", grid_spacing_m=1000,
        gpx_routes=[[[cx - 500, cy - 500], [cx + 500, cy + 500]]],
        gpx_color="#12ab34", out_pdf_path=str(out),
    )  # fmt: skip
    content = _page_content(out.read_bytes()).decode("latin-1")
    clip = re.search(r" re W\*? n", content).start()  # the map's clip block
    after = content[clip:]
    assert ".070588 .670588 .203922 RG" in after  # GPX stroke colour
    assert ".070588 .670588 .203922 RG" not in content[:clip]
    labels = [t for _, _, t, _ in _text_ops(content.encode("latin-1"))]
    assert "3730" in labels  # an east grid label
    assert after.index("(3730) Tj") > 0  # drawn after the map clip block


def test_vector_clip_rect_equals_raster_image_rect(tmp_path, monkeypatch, offline_tiles):
    extent = _vector_extent(offline_tiles, 25000)
    kw = dict(paper_size="A4", orientation="portrait", margin_mm=7.0)
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    r = tmp_path / "r.pdf"
    pdf_generator.generate_pdf(extent, out_pdf_path=str(r), **kw)
    v = tmp_path / "v.pdf"
    pdf_generator.generate_pdf(extent, layer="maastokartta_vektori", out_pdf_path=str(v), **kw)
    x, y, w, h = _image_box(_page_content(r.read_bytes()))
    content = _page_content(v.read_bytes()).decode("latin-1")
    rects = [
        tuple(float(g) for g in m.groups())
        for m in re.finditer(r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re\s+W", content)
    ]
    assert any(
        all(abs(a - b) < 0.01 for a, b in zip(rect, (x, y, w, h), strict=True)) for rect in rects
    ), (rects, (x, y, w, h))


def test_vector_rejects_unsupported_scale(tmp_path, offline_tiles):
    extent = _vector_extent(offline_tiles, 20000)
    with pytest.raises(ValueError, match="1:25 000 and 1:50 000"):
        pdf_generator.generate_pdf(
            extent, paper_size="A4", orientation="portrait",
            layer="maastokartta_vektori", out_pdf_path=str(tmp_path / "x.pdf"),
        )  # fmt: skip


def test_multi_pdf_mixed_raster_vector(tmp_path, monkeypatch, offline_tiles):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / "m.pdf"
    results = pdf_generator.generate_multi_pdf(
        [
            (
                _vector_extent(offline_tiles, 20000, "A3", "landscape"),
                {"paper_size": "A3", "orientation": "landscape"},
            ),
            (
                _vector_extent(offline_tiles, 50000),
                {"paper_size": "A4", "orientation": "portrait", "layer": "maastokartta_vektori"},
            ),
        ],
        str(out),
    )
    data = out.read_bytes()
    assert [r.actual_scale for r in results] == [20000, 50000]
    assert [r.width_px == 0 for r in results] == [False, True]
    assert len(re.findall(rb"/Subtype /Image", data)) == 1
    boxes = re.findall(rb"/MediaBox \[ 0 0 ([\d.]+) ([\d.]+) \]", data)
    sizes = [(round(float(w) / mm), round(float(h) / mm)) for w, h in boxes]
    assert sizes == [(420, 297), (210, 297)]


# --- Course look and waypoints -----------------------------------------------

_COURSE_EXT = Extent(428100, 6665230, 431900, 6670770)
_COURSE_PTS = [[429000, 6666000], [430000, 6667000], [431000, 6668000], [430000, 6670000]]


def _pdf_text(path):
    import subprocess

    out = subprocess.run(["pdftotext", str(path), "-"], check=True, capture_output=True)
    return out.stdout.decode()


def _magenta_pixels(path, tmp_path):
    import subprocess
    from glob import glob

    subprocess.run(["pdftoppm", "-png", "-r", "100", str(path), str(tmp_path / "pg")], check=True)
    img = Image.open(sorted(glob(str(tmp_path / "pg-*.png")))[0]).convert("RGB")
    px = img.load()
    w, h = img.size
    return sum(
        1
        for x in range(w)
        for y in range(h)
        if px[x, y][0] > 180 and px[x, y][1] < 100 and px[x, y][2] > 180
    )


def test_generate_pdf_course_look(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    texts = []
    orig = pdf_generator.canvas.Canvas.drawCentredString

    def spy(self, x, y, text, *a, **k):
        texts.append(text)
        return orig(self, x, y, text, *a, **k)

    monkeypatch.setattr(pdf_generator.canvas.Canvas, "drawCentredString", spy)
    out = tmp_path / "course.pdf"
    pdf_generator.generate_pdf(
        _COURSE_EXT,
        paper_size="A4",
        orientation="portrait",
        gpx_routes=[_COURSE_PTS],
        gpx_look="course",
        gpx_color="#ff00ff",
        gpx_width=1,
        gpx_opacity=1,
        out_pdf_path=str(out),
    )
    assert "1" in texts and "2" in texts  # the two controls
    assert "3" not in texts  # the finish has no number
    assert _magenta_pixels(out, tmp_path) > 100


def test_generate_pdf_waypoints_named(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / "wpt.pdf"
    pdf_generator.generate_pdf(
        _COURSE_EXT,
        paper_size="A4",
        orientation="portrait",
        gpx_routes=[_COURSE_PTS],
        gpx_waypoints=[{"x": 430500, "y": 6669000, "name": "Kota & laavu"}],
        out_pdf_path=str(out),
    )
    assert "Kota & laavu" in _pdf_text(out)


def test_waypoints_without_route_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / "wpt-only.pdf"
    pdf_generator.generate_pdf(
        _COURSE_EXT,
        paper_size="A4",
        orientation="portrait",
        gpx_routes=[],
        gpx_waypoints=[{"x": 430500, "y": 6669000, "name": "Lähde"}],
        out_pdf_path=str(out),
    )
    assert "Lähde" in _pdf_text(out)


def test_multi_pdf_passes_course_kwargs(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _fake_render)
    out = tmp_path / "multi.pdf"
    kwargs = {
        "paper_size": "A4",
        "orientation": "portrait",
        "gpx_routes": [_COURSE_PTS],
        "gpx_look": "course",
        "gpx_waypoints": [{"x": 430500, "y": 6669000, "name": "Torni"}],
    }
    pdf_generator.generate_multi_pdf([(_COURSE_EXT, kwargs)], str(out))
    assert "Torni" in _pdf_text(out)


# --- Total correction (kok.) and magnetic north lines --------------------------

_MN_EXT = Extent(428100, 6665230, 431900, 6670770)


def _white(extent, width_px, height_px, layer="maastokartta"):
    return Image.new("RGB", (width_px, height_px), (255, 255, 255))


def _text(path):
    import subprocess

    return subprocess.run(
        ["pdftotext", str(path), "-"], check=True, capture_output=True
    ).stdout.decode()


def _png(path, tmp_path, name="pg"):
    import subprocess
    from glob import glob

    subprocess.run(["pdftoppm", "-png", "-r", "60", str(path), str(tmp_path / name)], check=True)
    return Image.open(sorted(glob(str(tmp_path / f"{name}-*.png")))[0]).convert("RGB")


def _expected_kok(extent):
    from datetime import datetime

    from fastmap.services.north import format_correction, total_correction

    cx, cy = (extent.minx + extent.maxx) / 2, (extent.miny + extent.maxy) / 2
    today = datetime.now(pdf_generator._LOCAL_TZ).date()
    return format_correction(total_correction(cx, cy, today))


def test_footer_has_kok(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _white)
    out = tmp_path / "kok.pdf"
    pdf_generator.generate_pdf(
        _MN_EXT, paper_size="A4", orientation="portrait", out_pdf_path=str(out)
    )
    text = _text(out)
    assert _expected_kok(_MN_EXT) in text
    assert "kok. +" in text


def test_footer_long_title_keeps_scale_and_kok(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _white)
    out = tmp_path / "long.pdf"
    pdf_generator.generate_pdf(
        _MN_EXT,
        paper_size="A4",
        orientation="portrait",
        title="Pitkä otsikko " * 15,
        out_pdf_path=str(out),
    )
    text = _text(out)
    assert "1 : " in text and "kok." in text and "…" in text


def _grey_xs(img, row):
    px = img.load()
    # thin grey lines antialias at 60 dpi: anything clearly darker than white
    return [x for x in range(img.size[0]) if max(px[x, row]) < 235]


def test_magnetic_lines_are_slanted(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _white)
    out = tmp_path / "mag.pdf"
    pdf_generator.generate_pdf(
        _MN_EXT,
        paper_size="A4",
        orientation="portrait",
        magnetic_north=True,
        magnetic_spacing_m=500,
        out_pdf_path=str(out),
    )
    img = _png(out, tmp_path)
    h = img.size[1]
    top, bottom = _grey_xs(img, int(h * 0.15)), _grey_xs(img, int(h * 0.8))
    assert top and bottom
    assert set(top) != set(bottom)  # not vertical: the lines lean


def test_magnetic_spacing_larger_than_sheet(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _white)
    small = Extent(429000, 6666000, 429500, 6666700)
    pdf_generator.generate_pdf(
        small,
        paper_size="A4",
        orientation="portrait",
        magnetic_north=True,
        magnetic_spacing_m=2000,
        out_pdf_path=str(tmp_path / "s.pdf"),
    )


def _blue_pixels(img):
    px = img.load()
    w, h = img.size
    return sum(
        1
        for x in range(0, w, 2)
        for y in range(0, h, 2)
        if px[x, y][2] > 150 and px[x, y][0] < 90 and px[x, y][1] < 140
    )


def test_grid_turns_blue_only_with_magnetic(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _white)
    both = tmp_path / "both.pdf"
    grid = tmp_path / "grid.pdf"
    common = {"paper_size": "A4", "orientation": "portrait", "grid_mode": "full_coords"}
    pdf_generator.generate_pdf(_MN_EXT, magnetic_north=True, out_pdf_path=str(both), **common)
    pdf_generator.generate_pdf(_MN_EXT, out_pdf_path=str(grid), **common)
    assert _blue_pixels(_png(both, tmp_path, "b")) > 50
    assert _blue_pixels(_png(grid, tmp_path, "g")) == 0


def test_multi_pdf_magnetic_and_kok(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_generator, "render_extent_image", _white)
    out = tmp_path / "multi.pdf"
    kwargs = {"paper_size": "A4", "orientation": "portrait", "magnetic_north": True}
    pdf_generator.generate_multi_pdf([(_MN_EXT, kwargs)], str(out))
    assert _expected_kok(_MN_EXT) in _text(out)


def test_magnetic_lines_lean_east_for_a_positive_angle():
    """The top of each line is east (right) of its bottom: clockwise from grid north."""
    from reportlab.pdfgen import canvas as rl_canvas

    lines = []

    class Spy(rl_canvas.Canvas):
        def line(self, x1, y1, x2, y2):
            lines.append((x1, y1, x2, y2))

    c = Spy("unused.pdf")
    ext = Extent(0, 0, 1000, 1000)
    pdf_generator._draw_magnetic_lines(c, ext, 0, 0, 100, 100, angle_deg=15, spacing_m=250)
    assert lines
    for x1, y1, x2, y2 in lines:
        (bx, by), (tx, ty) = sorted([(x1, y1), (x2, y2)], key=lambda p: p[1])
        assert tx > bx  # leans east going north
        assert (tx - bx) / (ty - by) == pytest.approx(math.tan(math.radians(15)), rel=1e-9)
