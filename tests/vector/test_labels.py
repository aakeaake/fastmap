import shutil
import subprocess

import pytest
from reportlab.pdfbase import pdfmetrics
from shapely.geometry import LineString, Point
from test_render import _render, _style

from fastmap.services.print_layout import Extent
from fastmap.vector.draw import MapFrame
from fastmap.vector.fonts import font_for, register_fonts
from fastmap.vector.labels import Candidate, collect_candidates, place
from fastmap.vector.model import Feature

FRAME = MapFrame(Extent(0, 0, 200, 200), 0, 0, 200, 200)
BLACK = (0.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


def _cand(text="Label", anchor=(100, 100), priority=(0,), line=None, **kw):
    register_fonts()
    return Candidate(
        text=text,
        font="NotoSans-Regular",
        size_pt=10,
        color=BLACK,
        halo_color=WHITE,
        halo_pt=kw.pop("halo_pt", 1),
        priority=priority,
        anchor_pts=[] if line is not None else [(anchor[0], anchor[1], 0.0)],
        line=line,
        icon=None,
        allow_overlap=kw.pop("allow_overlap", False),
        ignore_placement=kw.pop("ignore_placement", False),
        padding_pt=kw.pop("padding_pt", 0.0),
        variable_anchors=kw.pop("variable_anchors", []),
        **kw,
    )


def test_higher_priority_wins_overlap():
    low = _cand("Second", priority=(5,))
    high = _cand("First", anchor=(105, 102), priority=(1,))
    placed = place([low, high], FRAME)
    assert [p.candidate.text for p in placed] == ["First"]


def test_allow_overlap_keeps_both():
    a = _cand("First", priority=(1,))
    b = _cand("Second", anchor=(105, 102), priority=(5,), allow_overlap=True)
    assert len(place([a, b], FRAME)) == 2


def test_box_crossing_frame_edge_dropped():
    assert place([_cand("Edge", anchor=(3, 100))], FRAME) == []
    assert len(place([_cand("Inside", anchor=(50, 100))], FRAME)) == 1


def test_variable_anchor_falls_back_to_second():
    first = _cand("First", anchor=(100, 60), priority=(1,))
    second = _cand("Second", anchor=(100, 52), priority=(2,), variable_anchors=["center", "top"])
    placed = place([first, second], FRAME)
    assert len(placed) == 2
    sec = next(p for p in placed if p.candidate.text == "Second")
    assert sec.anchor == "top"
    assert all(y < 52 for _, _, y, _ in sec.glyphs)  # text hangs below the anchor


def _line_glyphs(coords):
    placed = place([_cand("12345", line=LineString(coords), spacing_pt=1000)], FRAME)
    assert len(placed) == 1
    return placed[0].glyphs


def test_line_label_horizontal():
    glyphs = _line_glyphs([(10, 100), (190, 100)])
    assert "".join(g[0] for g in glyphs) == "12345"
    assert all(abs(g[3]) < 1e-6 for g in glyphs)
    xs = [g[1] for g in glyphs]
    assert xs == sorted(xs) and xs[0] < xs[-1]


def test_line_label_right_to_left_is_flipped():
    glyphs = _line_glyphs([(190, 100), (10, 100)])
    assert "".join(g[0] for g in glyphs) == "12345"
    assert all(abs(g[3] % 360) < 1e-6 or abs(g[3] % 360 - 360) < 1e-6 for g in glyphs)
    xs = [g[1] for g in glyphs]
    assert xs == sorted(xs) and xs[0] < xs[-1]


def test_line_label_on_zigzag_rejected():
    coords = [(10 + 4 * i, 100 + 4 * (i % 2)) for i in range(46)]
    cand = _cand("12345", line=LineString(coords), spacing_pt=40, max_angle=45)
    assert place([cand], FRAME) == []


def test_font_for():
    name = font_for(["Noto Sans Italic"])
    assert name == "NotoSans-Italic"
    assert name in pdfmetrics.getRegisteredFontNames()
    assert font_for(["Noto Sans Bold"]) == "NotoSans-Bold"
    assert font_for(["Comic Sans"]) == "NotoSans-Regular"
    register_fonts()  # idempotent


def test_collect_text_field_tokens_transform_and_wrap():
    style = _style(
        {
            "id": "names",
            "type": "symbol",
            "source-layer": "n",
            "layout": {
                "text-field": "{a}   {b}",
                "text-transform": "uppercase",
                "text-size": 10,
                "text-max-width": 3,
                "text-font": ["Noto Sans Bold"],
            },
            "paint": {"text-color": "#ff0000", "text-halo-width": 2},
        }
    )
    feats = {
        "n": [
            Feature("n", "Point", Point(100, 100), {"a": "Iso", "b": "Kivi", "prioriteetti": 7}),
            Feature("n", "Point", Point(50, 50), {}),  # empty text -> no label
        ]
    }
    cands = collect_candidates(style, feats, 14, FRAME, 0.5)
    assert len(cands) == 1
    c = cands[0]
    assert c.text == "ISO\nKIVI"
    assert c.font == "NotoSans-Bold"
    assert c.size_pt == pytest.approx(10 * 0.5 * 72 / 25.4)
    assert c.halo_pt == pytest.approx(2 * 0.5 * 72 / 25.4)
    assert c.color[:3] == (1.0, 0.0, 0.0)
    assert c.priority == (0, 0.0, 7, -0.0)  # layer 0, no sort key, prioriteetti 7


def test_icon_routing_no_double_drawing(tmp_path):
    from test_render import _canvas_content

    from fastmap.vector.symbols import Symbols, draw_icon_layers

    style = _style(
        {
            "id": "free",
            "type": "symbol",
            "source-layer": "p",
            "layout": {"icon-image": "mmlhc_sym_34100", "icon-allow-overlap": True},
        },
        {
            "id": "placed",
            "type": "symbol",
            "source-layer": "p",
            "layout": {"icon-image": "mmlhc_sym_12200", "icon-offset": [0, -10]},
        },
    )
    feats = {"p": [Feature("p", "Point", Point(100, 100), {})]}
    cands = collect_candidates(style, feats, 14, FRAME, 0.28)
    assert [c.icon for c in cands] == ["mmlhc_sym_12200"]
    placed = place(cands, FRAME)
    assert len(placed) == 1
    ix, iy = placed[0].icon_xy
    assert ix == pytest.approx(100) and iy > 100  # offset -10 px (up) raises the icon
    calls = []

    class Spy(Symbols):
        def draw_icon(self, c, name, *a):
            calls.append(name)

    _canvas_content(tmp_path, lambda c: draw_icon_layers(c, FRAME, style, feats, 14, 0.28, Spy()))
    assert calls == ["mmlhc_sym_34100"]


def test_offline_render_has_labels(tmp_path, offline_tiles):
    _, data = _render(tmp_path / "v.pdf", offline_tiles)
    assert b"/Subtype /Image" not in data
    assert b"NotoSans" in data
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext not installed")
    text = subprocess.run(
        ["pdftotext", str(tmp_path / "v.pdf"), "-"], capture_output=True, check=True, text=True
    ).stdout
    assert "Alkulla" in text
    # dropped while contour labels were placed before names (now top layers go first)
    assert "Hjortronmossen" in text and "Storkärr" in text


def test_later_layer_name_beats_earlier_contour_label():
    style = _style(
        {
            "id": "contour-label",
            "type": "symbol",
            "source-layer": "korkeus",
            "layout": {"symbol-placement": "line", "text-field": "{h}", "text-size": 20},
        },
        {
            "id": "names",
            "type": "symbol",
            "source-layer": "nimisto",
            "layout": {"text-field": "{nimi}", "text-size": 20},
        },
    )
    feats = {
        "korkeus": [
            Feature("korkeus", "LineString", LineString([(20, 100), (180, 100)]), {"h": 60})
        ],
        "nimisto": [Feature("nimisto", "Point", Point(100, 100), {"nimi": "Kaurasuo"})],
    }
    cands = collect_candidates(style, feats, 14, FRAME, 0.28)
    assert len(cands) == 2
    placed = place(cands, FRAME)
    assert [p.candidate.text for p in placed] == ["Kaurasuo"]


def test_point_label_dropped_when_only_its_halo_crosses_the_edge():
    w = pdfmetrics.stringWidth("Edge", "NotoSans-Regular", 10)
    ax = 0.5 + w / 2  # bare text box starts 0.5 pt inside the frame
    assert len(place([_cand("Edge", anchor=(ax, 100), halo_pt=0)], FRAME)) == 1
    assert place([_cand("Edge", anchor=(ax, 100), halo_pt=1)], FRAME) == []


def test_line_label_crossing_frame_edge_dropped():
    crossing = _cand("12345", line=LineString([(-60, 100), (25, 100)]), spacing_pt=1000)
    assert place([crossing], FRAME) == []
    # cap box would fit 5.5 pt above the bottom edge; descenders and halo do not
    low = _cand("12345", line=LineString([(10, 5.5), (190, 5.5)]), spacing_pt=1000)
    assert place([low], FRAME) == []
    high = _cand("12345", line=LineString([(10, 12), (190, 12)]), spacing_pt=1000)
    assert len(place([high], FRAME)) == 1


def test_line_label_rejected_by_spike_between_glyph_centres():
    # ~2 pt spike, 1 pt high, sits between the 3rd and 4th glyph centres
    coords = [(10, 100), (102.9, 100), (103.0, 101), (103.1, 100), (190, 100)]
    cand = _cand("12345", line=LineString(coords), spacing_pt=1000, max_angle=45)
    assert place([cand], FRAME) == []


def test_line_label_rejected_when_colliding_with_placed_box():
    blocker = _cand("Name", anchor=(100, 100), priority=(0,))
    line = _cand("12345", line=LineString([(10, 100), (190, 100)]), spacing_pt=1000, priority=(1,))
    other = _cand("678", line=LineString([(10, 150), (190, 150)]), spacing_pt=1000, priority=(1,))
    placed = place([line, other, blocker], FRAME)
    assert sorted(p.candidate.text for p in placed) == ["678", "Name"]


def test_collect_applies_text_and_halo_scale():
    style = _style(
        {
            "id": "names",
            "type": "symbol",
            "source-layer": "n",
            "layout": {"text-field": "{a}", "text-size": 10, "text-padding": 2},
            "paint": {"text-halo-width": 2},
        }
    )
    feats = {"n": [Feature("n", "Point", Point(100, 100), {"a": "Nimi"})]}
    (c,) = collect_candidates(style, feats, 14, FRAME, 0.5, text_scale=0.6, halo_scale=0.25)
    px_pt = 0.5 * 72 / 25.4
    assert c.size_pt == pytest.approx(10 * px_pt * 0.6)
    assert c.halo_pt == pytest.approx(2 * px_pt * 0.25)
    assert c.padding_pt == pytest.approx(2 * px_pt)  # collision padding is not text size
