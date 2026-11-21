import logging

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
