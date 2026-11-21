"""Vector fill patterns and map icons, drawn as paths (no raster images).

The look follows the mmlv2 ``tools/v4/make_patterns.py`` pattern/symbol set and the
mtb-trailmap sprite. All source geometry is in image px at pixel ratio 2, so one image px is
half a style px, i.e. ``px_mm / 2`` mm on paper (times ``icon-size`` for icons).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import FILL_NON_ZERO, Canvas

from .draw import MapFrame
from .model import Feature
from .style import Style, StyleLayer

log = logging.getLogger(__name__)

PIXEL_RATIO = 2
MARKER_DIAMETER_MM = 0.6
MARKER_GREY = (0.5, 0.5, 0.5)
_WARNED: set[str] = set()  # names already warned about, once per process
_BLANK = ("", "#blank")


# ------------------------------------------------------------------ fill patterns


@dataclass(frozen=True)
class _Hatch:
    rgb: tuple[int, int, int]
    tile: int  # image px; the stripe period along x is ``period``
    period: float
    width: float
    direction: int  # +1: "/", -1: "\"


@dataclass(frozen=True)
class _HLines:
    rgb: tuple[int, int, int]
    period: float
    width: float


@dataclass(frozen=True)
class _Triangles:
    rgb: tuple[int, int, int]
    tile: int
    size: float
    points: tuple[tuple[float, float], ...]


_PATTERNS: dict[str, Any] = {
    "mmlhc_varvikko": _Hatch((242, 204, 0), 32, 16, 6, 1),
    "mmlhc_varvikko_fine": _Hatch((242, 204, 0), 24, 12, 2.2, 1),
    "mmlhc_avoin_metsamaa": _Hatch((184, 217, 0), 32, 16, 5, -1),
    "mmlhc_avoin_metsamaa_fine": _Hatch((184, 217, 0), 24, 12, 2, -1),
    "mmlhc_suo_vaikea": _HLines((64, 176, 230), 8, 2.4),
    "mmlhc_kivikko": _Triangles((0, 0, 0), 48, 9, ((10, 12), (34, 20), (18, 38), (42, 44))),
}
PATTERN_NAMES = frozenset(_PATTERNS)


def _rgb(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    return tuple(v / 255 for v in rgb)  # type: ignore[return-value]


def _range(lo: float, hi: float, step: float):
    k = math.floor(lo / step)
    while k * step <= hi:
        yield k
        k += 1


def _hatch_path(c: Canvas, p: _Hatch, bbox, s: float):
    minx, miny, maxx, maxy = bbox
    period = p.period * s
    path = c.beginPath()
    if p.direction > 0:  # "/": x - y = k * period
        for k in _range(minx - maxy, maxx - miny, period):
            d = k * period
            path.moveTo(minx, minx - d)
            path.lineTo(maxx, maxx - d)
    else:  # "\": x + y = k * period
        for k in _range(minx + miny, maxx + maxy, period):
            d = k * period
            path.moveTo(minx, d - minx)
            path.lineTo(maxx, d - maxx)
    return path


def _draw_hatch(c: Canvas, p: _Hatch, bbox, s: float) -> None:
    c.setStrokeColorRGB(*_rgb(p.rgb))
    c.setLineWidth(p.width * s)
    c.drawPath(_hatch_path(c, p, bbox, s), stroke=1, fill=0)


def _draw_hlines(c: Canvas, p: _HLines, bbox, s: float) -> None:
    minx, miny, maxx, maxy = bbox
    path = c.beginPath()
    for k in _range(miny, maxy, p.period * s):
        y = k * p.period * s
        path.moveTo(minx, y)
        path.lineTo(maxx, y)
    c.setStrokeColorRGB(*_rgb(p.rgb))
    c.setLineWidth(p.width * s)
    c.drawPath(path, stroke=1, fill=0)


def _draw_triangles(c: Canvas, p: _Triangles, bbox, s: float) -> None:
    minx, miny, maxx, maxy = bbox
    tile = p.tile * s
    h = p.size * math.sqrt(3) / 2
    path = c.beginPath()
    for i in _range(minx - tile, maxx, tile):
        for j in _range(miny - tile, maxy, tile):
            ox, oy = i * tile, (j + 1) * tile  # tile origin: image top-left
            for cx, cy in p.points:
                path.moveTo(ox + cx * s, oy - (cy - h / 2) * s)
                path.lineTo(ox + (cx + p.size / 2) * s, oy - (cy + h / 2) * s)
                path.lineTo(ox + (cx - p.size / 2) * s, oy - (cy + h / 2) * s)
                path.close()
    c.setFillColorRGB(*_rgb(p.rgb))
    c.drawPath(path, stroke=0, fill=1)


_PATTERN_DRAW = {_Hatch: _draw_hatch, _HLines: _draw_hlines, _Triangles: _draw_triangles}


# ------------------------------------------------------------------ icons
# Ops in image px (y down): ("seg", points, width), ("poly", points), ("disc", cx, cy, r),
# ("ring", cx, cy, r, width), ("arc", cx, cy, r, a0_deg, a1_deg, width).

_K = (0, 0, 0)
_BLUE = (0, 128, 255)


def _arc_points(cx, cy, r, a0, a1, step=15):
    n = max(2, int(abs(a1 - a0) / step) + 1)
    return [
        (
            cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / (n - 1))),
            cy - r * math.sin(math.radians(a0 + (a1 - a0) * i / (n - 1))),
        )
        for i in range(n)
    ]


def _seg(a, b, width=2.4):
    return ("seg", [a, b], width)


@dataclass(frozen=True)
class _Icon:
    w: int
    h: int
    layers: tuple[tuple[tuple[int, int, int], tuple], ...]  # (rgb, ops)


def _icon(w, h, *layers):
    return _Icon(w, h, tuple(layers))


_THIN = 1.6
_ICONS: dict[str, _Icon] = {
    "mmlhc_sym_32710": _icon(20, 24, (_K, (("seg", [(3, 22), (10, 2), (17, 22)], _THIN),))),
    "mmlhc_sym_32714": _icon(
        20,
        28,
        (_K, (("seg", [(3, 26), (10, 13), (17, 26)], _THIN), ("ring", 10, 7, 4.5, _THIN))),
    ),
    "mmlhc_sym_34600": _icon(
        14, 14, (_K, (_seg((7, 2), (7, 12), _THIN), _seg((1.5, 12), (12.5, 12), _THIN)))
    ),
    # small open rock: the colour of the large open-rock fill (#d1c7d1), small dot
    "mmlhc_sym_34100": _icon(10, 10, ((209, 199, 209), (("disc", 5, 5, 2.6),))),
    "mmlhc_sym_12200": _icon(
        20, 20, (_K, (_seg((3, 3), (17, 17), _THIN), _seg((17, 3), (3, 17), _THIN)))
    ),
    "mmlhc_sym_36392": _icon(
        16, 28, (_BLUE, (_seg((8, 26), (8, 6)), ("poly", [(2, 10), (8, 1), (14, 10)])))
    ),
    "mmlhc_sym_32713": _icon(20, 20, (_K, (("seg", _arc_points(10, 10, 7, -30, 240), _THIN),))),
    "mmlhc_sym_32891": _icon(
        16, 20, (_K, (_seg((5, 3), (5, 17), _THIN), _seg((11, 3), (11, 17), _THIN)))
    ),
    "mmlhc_sym_36100": _icon(
        20,
        20,
        (_K, (_seg((3, 2), (3, 11)), _seg((17, 2), (17, 11)))),
        (
            _K,
            (
                (
                    "seg",
                    [
                        (10 + 7 * math.cos(math.radians(a)), 11 + 7 * math.sin(math.radians(a)))
                        for a in range(0, 181, 15)
                    ],
                    1.8,
                ),
            ),
        ),
        (_BLUE, (("disc", 10, 10, 4.5),)),
    ),
    "mmlhc_sym_36400": _icon(20, 22, (_BLUE, (("seg", [(3, 2), (10, 20), (17, 2)], _THIN),))),
    "mmlhc_poi_44800": _icon(
        24, 24, (_K, (_seg((12, 1), (12, 23)), _seg((1, 12), (23, 12)), ("disc", 12, 12, 5)))
    ),
    "mmlhc_sym_32715": _icon(28, 20, (_K, (_seg((3, 2), (9.5, 18)), _seg((25, 2), (18.5, 18))))),
    "mmlhc_sym_44591": _icon(40, 8, (_K, (_seg((3, 4), (37, 4), 4),))),
    "mmlhc_sym_45200": _icon(
        28, 32, (_K, (_seg((4, 3), (4, 29), 3.6), _seg((24, 3), (24, 29), 3.6)))
    ),
    "mmlhc_poi_45710": _icon(
        28,
        22,
        (
            _K,
            (
                ("poly", [(14.0, 11.5), (20.0, 0.5), (8.0, 0.5)]),
                ("poly", [(15.47, 13.31), (25.08, 20.98), (27.37, 10.22)]),
                ("poly", [(12.53, 13.31), (0.63, 10.22), (2.92, 20.98)]),
            ),
        ),
    ),
    # mtb-trailmap sprite symbols (butt-capped bars, square ends)
    "triangle_11": _icon(34, 34, ((68, 68, 68), (("poly", [(17, 8), (26, 24), (8, 24)]),))),
    "tm_mml_22392_suurjannitelinjan_pylvas": _icon(
        64,
        64,
        (
            _K,
            (
                _seg((12, 12), (52, 52), 4.5),
                _seg((52, 12), (12, 52), 4.5),
                ("disc", 12, 12, 3.6),
                ("disc", 52, 12, 3.6),
                ("disc", 12, 52, 3.6),
                ("disc", 52, 52, 3.6),
            ),
        ),
    ),
    "mml-vesikivi_pinnassa": _icon(
        64, 64, (_K, (("bar", (12, 32), (52, 32), 4.5), ("bar", (32, 12), (32, 52), 4.5)))
    ),
    "mml-vesikivi_vedenpaallinen": _icon(
        64, 64, (_K, (("bar", (12, 47), (52, 47), 4.5), ("bar", (32, 12), (32, 47), 4.5)))
    ),
}
ICON_NAMES = frozenset(_ICONS)


def _draw_ops(c: Canvas, ops: tuple, rgb: tuple[int, int, int]) -> None:
    color = _rgb(rgb)
    c.setFillColorRGB(*color)
    c.setStrokeColorRGB(*color)
    c.setLineJoin(1)
    for op in ops:
        kind = op[0]
        if kind in ("seg", "bar"):
            pts = op[1] if kind == "seg" else [op[1], op[2]]
            c.setLineCap(1 if kind == "seg" else 0)
            c.setLineWidth(op[2] if kind == "seg" else op[3])
            path = c.beginPath()
            path.moveTo(*pts[0])
            for pt in pts[1:]:
                path.lineTo(*pt)
            c.drawPath(path, stroke=1, fill=0)
        elif kind == "poly":
            path = c.beginPath()
            path.moveTo(*op[1][0])
            for pt in op[1][1:]:
                path.lineTo(*pt)
            path.close()
            c.drawPath(path, stroke=0, fill=1)
        elif kind == "disc":
            c.circle(op[1], op[2], op[3], stroke=0, fill=1)
        elif kind == "ring":
            c.setLineWidth(op[4])
            c.circle(op[1], op[2], op[3], stroke=1, fill=0)


# ------------------------------------------------------------------ public class


class Symbols:
    """Draws the style's fill patterns and map icons as vector paths."""

    def _warn_once(self, kind: str, name: str) -> None:
        if name not in _WARNED:
            _WARNED.add(name)
            log.warning("no vector drawing for %s %r", kind, name)

    def draw_pattern(
        self,
        c: Canvas,
        name: str,
        clip_path: Any,
        bbox_pt: tuple[float, float, float, float],
        px_mm: float,
    ) -> None:
        pattern = _PATTERNS.get(name)
        if pattern is None:
            self._warn_once("pattern", name)
            return
        c.saveState()
        c.clipPath(clip_path, stroke=0, fill=0, fillMode=FILL_NON_ZERO)
        _PATTERN_DRAW[type(pattern)](c, pattern, bbox_pt, px_mm * mm / PIXEL_RATIO)
        c.restoreState()

    def draw_icon(
        self,
        c: Canvas,
        name: str,
        x: float,
        y: float,
        size: float,
        rotation_deg: float,
        px_mm: float,
    ) -> None:
        icon = _ICONS.get(name)
        c.saveState()
        if icon is None:
            self._warn_once("icon", name)
            c.setFillColorRGB(*MARKER_GREY)
            c.circle(x, y, MARKER_DIAMETER_MM / 2 * mm, stroke=0, fill=1)
            c.restoreState()
            return
        s = size * px_mm * mm / PIXEL_RATIO
        c.translate(x, y)
        c.rotate(-rotation_deg)  # style rotation is clockwise, PDF's is anticlockwise
        c.scale(s, -s)
        c.translate(-icon.w / 2, -icon.h / 2)
        for rgb, ops in icon.layers:
            _draw_ops(c, ops, rgb)
        c.restoreState()


# ------------------------------------------------------------------ style walking


def _outputs(expr: Any) -> list[Any]:
    """Sub-expressions of ``expr`` that can be its result value."""
    if isinstance(expr, dict):  # legacy {"stops": [[z, v], ...]}
        return [v for _, v in expr.get("stops", [])]
    if not isinstance(expr, list) or not expr or not isinstance(expr[0], str):
        return []
    op = expr[0]
    if op == "match":
        return expr[3:-1:2] + expr[-1:]
    if op == "case":
        return expr[2:-1:2] + expr[-1:]
    if op == "step":
        return expr[2:3] + expr[4::2]
    if op == "coalesce":
        return expr[1:]
    if op == "literal":
        return expr[1:2]
    return []


def _strings(expr: Any) -> set[str]:
    if isinstance(expr, str):
        return {expr}
    out: set[str] = set()
    for sub in _outputs(expr):
        out |= _strings(sub)
    return out


def referenced_names(style: Style) -> tuple[set[str], set[str]]:
    """(pattern names, icon names) the style can ask for."""
    patterns: set[str] = set()
    icons: set[str] = set()
    for layer in style.layers:
        if "fill-pattern" in layer.paint:
            patterns |= _strings(layer.paint["fill-pattern"])
        if "icon-image" in layer.layout:
            icons |= _strings(layer.layout["icon-image"])
    return patterns - set(_BLANK), icons - set(_BLANK)


def icon_size_pt(name: str, size: float, px_mm: float) -> tuple[float, float]:
    """Unrotated (width, height) of icon ``name`` on paper, in pt."""
    icon = _ICONS.get(name)
    if icon is None:
        d = MARKER_DIAMETER_MM * mm
        return (d, d)
    s = size * px_mm * mm / PIXEL_RATIO
    return (icon.w * s, icon.h * s)


# ------------------------------------------------------------------ icon layers


def placed_by_labels(layer: StyleLayer) -> bool:
    """True if this layer's icons go through collision placement (``labels.place``).

    Only icon-only layers with ``icon-allow-overlap: true`` are drawn unconditionally by
    :func:`draw_icon_layers`; icons that may collide, or that share a unit with a text
    label, are placed (and drawn) by the label code.
    """
    return "text-field" in layer.layout or layer.layout.get("icon-allow-overlap") is not True


def _icon_layers(style: Style, zoom: float) -> list[StyleLayer]:
    return [
        ly
        for ly in style.layers
        if ly.type == "symbol"
        and "icon-image" in ly.layout
        and ly.visible_at(zoom)
        and not placed_by_labels(ly)
    ]


def draw_icon_layers(
    c: Canvas,
    frame: MapFrame,
    style: Style,
    features_by_layer: dict[str, list[Feature]],
    zoom: float,
    px_mm: float,
    symbols: Symbols,
) -> None:
    """Draw the icons of visible icon-only symbol layers that allow overlap.

    These are drawn unconditionally; all other icons are placed by ``labels.place``.
    """
    from .draw import _matching

    for layer in _icon_layers(style, zoom):
        features = features_by_layer.get(layer.source_layer or "", [])
        for f, ctx in _matching(layer, features, zoom, ("Point",)):
            name = layer.get("icon-image", ctx)
            if not name or name in _BLANK:
                continue
            opacity = float(layer.get("icon-opacity", ctx, 1.0))
            if opacity <= 0:
                continue
            size = float(layer.get("icon-size", ctx, 1.0))
            rotation = float(layer.get("icon-rotate", ctx, 0.0))
            geom = f.geometry
            for pt in getattr(geom, "geoms", [geom]):
                if pt.is_empty:
                    continue
                x, y = frame.to_pt(pt.x, pt.y)
                c.saveState()
                c.setFillAlpha(opacity)
                c.setStrokeAlpha(opacity)
                symbols.draw_icon(c, name, x, y, size, rotation, px_mm)
                c.restoreState()
