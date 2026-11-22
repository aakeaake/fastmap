import logging

import pytest
from test_render import _canvas_content, _render

from fastmap.vector.style import load_style
from fastmap.vector.symbols import ICON_NAMES, PATTERN_NAMES, Symbols, referenced_names


def test_every_referenced_name_has_drawing():
    patterns, icons = referenced_names(load_style())
    assert patterns and icons
    assert patterns <= PATTERN_NAMES, patterns - PATTERN_NAMES
    assert icons <= ICON_NAMES, icons - ICON_NAMES
    assert "" not in icons and "#blank" not in icons


def test_referenced_names_walks_expressions():
    from test_render import _style

    style = _style(
        {
            "id": "a",
            "type": "symbol",
            "layout": {"icon-image": ["match", ["get", "k"], 1, "x", [2, 3], "y", "#blank"]},
        },
        {
            "id": "b",
            "type": "fill",
            "paint": {"fill-pattern": ["step", ["zoom"], "lo", 14, "hi"]},
        },
    )
    assert referenced_names(style) == ({"lo", "hi"}, {"x", "y"})


def test_unknown_icon_warns_once(tmp_path, caplog):
    sym = Symbols()
    with caplog.at_level(logging.WARNING):
        content = _canvas_content(
            tmp_path,
            lambda c: [sym.draw_icon(c, "nope", 10, 10, 1, 0, 0.28) for _ in range(3)],
        )
    assert len([r for r in caplog.records if "nope" in r.getMessage()]) == 1
    assert b" c" in content  # a marker circle was still drawn


def test_icon_drawn_with_size_and_rotation(tmp_path):
    sym = Symbols()
    content = _canvas_content(
        tmp_path, lambda c: sym.draw_icon(c, "mmlhc_sym_32710", 50, 60, 2, 90, 0.28)
    )
    assert b" cm" in content and b" l" in content


def test_pattern_clipped_to_path(tmp_path):
    sym = Symbols()

    def draw(c):
        path = c.beginPath()
        path.rect(10, 10, 50, 50)
        sym.draw_pattern(c, "mmlhc_suo_vaikea", path, (10, 10, 60, 60), 0.28)

    content = _canvas_content(tmp_path, draw)
    assert b"W" in content and content.count(b" l") > 5


def test_render_with_symbols_still_vector(tmp_path, offline_tiles):
    _, data = _render(tmp_path / "v.pdf", offline_tiles)
    assert b"/Subtype /Image" not in data


def test_small_open_rock_dot_matches_open_rock_fill():
    """F4: the 34100 point symbol uses the large open-rock area colour, small."""
    from fastmap.vector.colors import parse_color
    from fastmap.vector.expressions import EvalContext
    from fastmap.vector.symbols import _ICONS

    layer = next(ly for ly in load_style().layers if ly.id == "maasto_alue-kallio")
    fill = layer.get("fill-color", EvalContext({"kohdeluokka": 34100}, 13, "Polygon"))
    ((rgb, ops),) = _ICONS["mmlhc_sym_34100"].layers
    assert tuple(v / 255 for v in rgb) == parse_color(fill)[:3]
    ((kind, _, _, radius),) = ops
    assert kind == "disc"
    # printed size at 1:25 000: bigger than the old 0.44 mm, smaller than the
    # reference map's ~0.8 mm (user's call)
    from fastmap.vector.profiles import PROFILES
    from fastmap.vector.style import scale_to_zoom, style_for

    profile = PROFILES[25000]
    rock = next(ly for ly in style_for(profile).layers if ly.id == "mml-kallio-piste")
    ctx = EvalContext(
        {"kohdeluokka": 34100}, scale_to_zoom(25000, 6_664_000) + profile.zoom_offset, "Point"
    )
    diameter_mm = 2 * radius * rock.number("icon-size", ctx, 1) * profile.px_mm / 2
    assert 0.55 <= diameter_mm <= 0.7


def test_small_open_rock_is_drawn_under_the_contours(tmp_path):
    from shapely.geometry import LineString, Point

    from fastmap.services.print_layout import Extent
    from fastmap.vector.draw import MapFrame, draw_fill_line_layers
    from fastmap.vector.model import Feature
    from fastmap.vector.profiles import PROFILES
    from fastmap.vector.style import style_for

    profile = PROFILES[25000]
    frame = MapFrame(Extent(0, 0, 1000, 1000), 0, 0, 200, 200)
    features = {
        "maasto_piste": [Feature("maasto_piste", "Point", Point(500, 500), {"kohdeluokka": 34100})],
        "korkeus": [
            Feature(
                "korkeus",
                "LineString",
                LineString([(0, 500), (1000, 500)]),
                {"kohdeluokka": 52100, "korkeusarvo": 20000},
            )
        ],
    }
    content = _canvas_content(
        tmp_path,
        lambda c: draw_fill_line_layers(
            c, frame, style_for(profile), features, 13.6, profile.px_mm, Symbols()
        ),
    ).decode("latin-1")
    rock_fill = content.find(".819608 .780392 .819608 rg")  # #d1c7d1
    contour = content.find(" RG")
    assert 0 <= rock_fill < contour, "rock dot must come before the contour stroke"


REFERENCE = {  # path text copied from the reference print map (0.04 mm units)
    "mmlhc_sym_32710": "-10 0 m 0 40 l 10 0 l S",
    "mmlhc_sym_32714": "-10 0 m 0 20 l 10 0 l -6.4 20.3 m",
    "mmlhc_sym_32713": "-8.6 -1.3 m -12.6 1.5 -15 6.1 -15 11 c",
    "mmlhc_poi_44800": "-15 0 m 15 0 l 0 -15 m 0 35 l -7 25 m 0 35 l 7 25 l S",
    "mmlhc_sym_36100": "8 10 m 8 0 l 8 -4.4 4.4 -8 0 -8 c",
    "mmlhc_poi_45710": "0 0 m -18 20 0 20 0 40 c 18 20 0 20 0 0 c f",
}


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_forest_and_mast_symbols_are_the_reference_paths(name):
    from fastmap.vector.symbols import _ICONS

    ops = [op for _, shapes in _ICONS[name].layers for op in shapes]
    assert any(op[0] == "ref" and REFERENCE[name] in op[1] for op in ops)


@pytest.mark.parametrize("icon_size", [1.0, 1.48])  # the style's icon-size must not apply
def test_reference_symbols_print_at_reference_size_at_25k(tmp_path, icon_size):
    import re

    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from fastmap.vector.profiles import PROFILES
    from fastmap.vector.symbols import Symbols

    path = tmp_path / "s.pdf"
    c = canvas.Canvas(str(path), pagesize=(100, 100), pageCompression=0)
    Symbols().draw_icon(c, "mmlhc_sym_32710", 50, 50, icon_size, 0, PROFILES[25000].px_mm)
    c.save()
    text = path.read_bytes().decode("latin-1")
    # the conifer "Λ" is 20 x 40 units of 0.04 mm: 0.8 mm x 1.6 mm on paper
    scales = [float(m) for m in re.findall(r"([-\d.]+) 0 0 [-\d.]+ [-\d.]+ [-\d.]+ cm", text)]
    unit_pt = 1.0
    for v in scales:
        unit_pt *= abs(v)
    assert unit_pt * 40 == pytest.approx(1.6 * mm, rel=0.02)


def test_collision_box_of_a_reference_icon_ignores_icon_size():
    from fastmap.vector.profiles import PROFILES
    from fastmap.vector.symbols import icon_size_pt

    px = PROFILES[25000].px_mm
    assert icon_size_pt("mmlhc_sym_32710", 1.48, px) == icon_size_pt("mmlhc_sym_32710", 1.0, px)


# ------------------------------------------------------------------ symbols.json


def _symbols_raw():
    import json

    from fastmap.vector.symbols import SYMBOLS_PATH

    return json.loads(SYMBOLS_PATH.read_text(encoding="utf-8"))


def _load_symbols(tmp_path, raw):
    import json

    from fastmap.vector.symbols import load_symbols

    path = tmp_path / "symbols.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_symbols(path)


def test_symbols_json_loads_and_validates():
    from fastmap.vector.symbols import _ICONS, _PATTERNS, load_symbols

    patterns, icons = load_symbols()
    assert patterns == _PATTERNS and icons == _ICONS
    raw = _symbols_raw()
    assert set(raw["patterns"]) == PATTERN_NAMES and set(raw["icons"]) == ICON_NAMES


def test_every_style_reference_is_in_symbols_json():
    raw = _symbols_raw()
    patterns, icons = referenced_names(load_style())
    assert patterns <= set(raw["patterns"]), patterns - set(raw["patterns"])
    assert icons <= set(raw["icons"]), icons - set(raw["icons"])


@pytest.mark.parametrize("where", ["top", "pattern", "ref icon", "own icon", "layer"])
def test_symbols_json_rejects_unknown_key(tmp_path, where):
    from fastmap.vector.expressions import StyleError

    raw = _symbols_raw()
    target = {
        "top": raw,
        "pattern": raw["patterns"]["mmlhc_suo_vaikea"],
        "ref icon": raw["icons"]["mmlhc_sym_32710"],
        "own icon": raw["icons"]["mmlhc_sym_34100"],
        "layer": raw["icons"]["mmlhc_sym_34100"]["layers"][0],
    }[where]
    target["colour"] = [1, 2, 3]
    with pytest.raises(StyleError, match="unknown key"):
        _load_symbols(tmp_path, raw)


def test_symbols_json_rejects_unknown_op_and_bad_arguments(tmp_path):
    from fastmap.vector.expressions import StyleError

    raw = _symbols_raw()
    raw["icons"]["mmlhc_sym_34100"]["layers"][0]["ops"].append(["arc", 5, 5, 2, 0, 90, 1])
    with pytest.raises(StyleError, match="unknown op 'arc'"):
        _load_symbols(tmp_path, raw)
    raw = _symbols_raw()
    raw["icons"]["mmlhc_sym_34100"]["layers"][0]["ops"] = [["disc", 5, 5]]
    with pytest.raises(StyleError, match="expected 3 arguments"):
        _load_symbols(tmp_path, raw)
    raw = _symbols_raw()
    raw["patterns"]["mmlhc_kivikko"]["kind"] = "dots"
    with pytest.raises(StyleError, match="kind"):
        _load_symbols(tmp_path, raw)
    raw = _symbols_raw()
    raw["icons"]["mmlhc_sym_32710"]["anchor"] = "center"
    with pytest.raises(StyleError, match="anchor"):
        _load_symbols(tmp_path, raw)
