import re
from pathlib import Path

import pytest
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from fastmap.services.print_layout import Extent
from fastmap.vector import VECTOR_SCALES, render_vector_map
from fastmap.vector.draw import MapFrame

_STREAM = re.compile(rb"<<((?:[^<>]|<<[^<>]*>>)*)>>\s*stream\r?\n")
_LENGTH = re.compile(rb"/Length (\d+)(?!\d| \d+ R)")


def _page_content(data: bytes) -> bytes:
    """Decode the PDF's non-image streams (same approach as test_pdf_generator)."""
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


def _extent(center, size_mm, scale):
    half = size_mm / 1000 * scale / 2
    return Extent(center[0] - half, center[1] - half, center[0] + half, center[1] + half)


def _render(path: Path, center, scale=25000, size_mm=150):
    rect = (20 * mm, 30 * mm, size_mm * mm, size_mm * mm)
    c = Canvas(str(path), pagesize=(200 * mm, 200 * mm))
    render_vector_map(c, _extent(center, size_mm, scale), rect, scale)
    c.showPage()
    c.save()
    return rect, path.read_bytes()


def test_vector_scales():
    assert VECTOR_SCALES == frozenset({25000, 50000})


def test_map_frame_to_pt():
    frame = MapFrame(Extent(1000, 2000, 2000, 4000), 10, 20, 100, 200)
    assert frame.to_pt(1000, 2000) == pytest.approx((10, 20))
    assert frame.to_pt(2000, 4000) == pytest.approx((110, 220))
    assert frame.to_pt(1500, 3000) == pytest.approx((60, 120))


def test_render_offline_is_vector(tmp_path, offline_tiles):
    rect, data = _render(tmp_path / "v.pdf", offline_tiles)
    assert b"/Subtype /Image" not in data
    content = _page_content(data)
    ops = set(re.findall(rb"(?<![A-Za-z])(re|m|l|S|f|B)(?![A-Za-z])", content))
    assert {b"re", b"m", b"l"} <= ops
    assert ops & {b"S", b"B"} and ops & {b"f", b"B"}
    x, y, w, h = rect
    clip = re.search(rb"([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) re W\*? n", content)
    assert clip, "no clip rect"
    assert [float(v) for v in clip.groups()] == pytest.approx([x, y, w, h], abs=0.01)
    # far more than a background: fills and lines were drawn
    assert content.count(b" l") > 1000


def test_render_rejects_other_scale(tmp_path):
    c = Canvas(str(tmp_path / "x.pdf"))
    with pytest.raises(ValueError, match="1:25 000 and 1:50 000"):
        render_vector_map(c, Extent(0, 0, 100, 100), (0, 0, 100, 100), 20000)


def _style(*layers):
    from fastmap.vector.style import Style, StyleLayer

    return Style(
        [
            StyleLayer(
                id=ly["id"],
                type=ly["type"],
                source_layer=ly.get("source-layer"),
                minzoom=ly.get("minzoom", 0),
                maxzoom=ly.get("maxzoom", 24),
                filter=ly.get("filter"),
                paint=ly.get("paint", {}),
                layout=ly.get("layout", {}),
            )
            for ly in layers
        ]
    )


def _canvas_content(tmp_path, draw):
    c = Canvas(str(tmp_path / "s.pdf"))
    draw(c)
    c.showPage()
    c.save()
    return _page_content((tmp_path / "s.pdf").read_bytes())


def test_line_width_dash_and_batching(tmp_path):
    from shapely.geometry import LineString

    from fastmap.vector.draw import draw_fill_line_layers
    from fastmap.vector.model import Feature

    style = _style(
        {
            "id": "l",
            "type": "line",
            "source-layer": "tie",
            "filter": ["==", ["get", "k"], 1],
            "paint": {"line-color": "#ff0000", "line-width": 2, "line-dasharray": [3, 1]},
        }
    )
    frame = MapFrame(Extent(0, 0, 100, 100), 0, 0, 100, 100)
    feats = [
        Feature("tie", "LineString", LineString([(10, 10), (90, 10)]), {"k": 1}),
        Feature("tie", "LineString", LineString([(10, 50), (90, 50)]), {"k": 1}),
        Feature("tie", "LineString", LineString([(10, 90), (90, 90)]), {"k": 2}),
    ]
    content = _canvas_content(
        tmp_path,
        lambda c: draw_fill_line_layers(c, frame, style, {"tie": feats}, 14, 0.5, None),
    )
    width = 2 * 0.5 * mm
    assert f"{width:.5g}".encode() in content
    dash = re.search(rb"\[([\d. ]+)\] 0 d", content)
    assert [float(v) for v in dash.group(1).split()] == pytest.approx([3 * width, width], rel=1e-3)
    assert len(re.findall(rb"(?m)^S$", content)) == 1  # two features, one batched path
    assert b"10 90 m" not in content  # filtered out


def test_fill_pattern_delegated_or_skipped(tmp_path):
    from shapely.geometry import box

    from fastmap.vector.draw import draw_fill_line_layers
    from fastmap.vector.model import Feature

    style = _style(
        {"id": "p", "type": "fill", "source-layer": "a", "paint": {"fill-pattern": "dots"}}
    )
    frame = MapFrame(Extent(0, 0, 100, 100), 0, 0, 100, 100)
    feats = {"a": [Feature("a", "Polygon", box(10, 10, 20, 20), {})]}
    calls = []

    class FakeSymbols:
        def draw_pattern(self, c, name, clip_path, bbox_pt, px_mm):
            calls.append((name, bbox_pt, px_mm))

    _canvas_content(
        tmp_path, lambda c: draw_fill_line_layers(c, frame, style, feats, 14, 0.28, None)
    )
    assert calls == []
    _canvas_content(
        tmp_path,
        lambda c: draw_fill_line_layers(c, frame, style, feats, 14, 0.28, FakeSymbols()),
    )
    assert calls == [("dots", pytest.approx((10, 10, 20, 20)), 0.28)]
