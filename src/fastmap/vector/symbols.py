"""Vector fill patterns and map icons, drawn as paths (no raster images).

The patterns and icons themselves are data in ``styles/symbols.json`` (loaded and
validated at import); this module holds the drawing mechanics. The look follows the
mmlv2 ``tools/v4/make_patterns.py`` pattern/symbol set, the mtb-trailmap sprite and the
user's reference print map. Pattern and own-icon geometry is in image px at pixel ratio 2,
so one image px is half a style px, i.e. ``px_mm / 2`` mm on paper (times ``icon-size``
for icons).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import FILL_NON_ZERO, Canvas

from .draw import MapFrame
from .expressions import StyleError
from .geometry import parts
from .model import Feature
from .profiles import PROFILES
from .style import Style, StyleLayer

log = logging.getLogger(__name__)

PIXEL_RATIO = 2
MARKER_DIAMETER_MM = 0.6
MARKER_GREY = (0.5, 0.5, 0.5)
_WARNED: set[str] = set()  # names already warned about, once per process
_BLANK = ("", "#blank")


# ------------------------------------------------------------------ fill patterns
# Each pattern kind's parameters come from symbols.json ("kind": "hatch", "hlines",
# "triangles"); the kinds stay in code because each needs its own drawing function.


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
# Own icons are drawn from ops in image px (y down), as loaded from symbols.json:
# ("seg", points, width), ("bar", a, b, width), ("poly", points), ("disc", cx, cy, r),
# ("ring", cx, cy, r, width); reference icons use the internal ("ref", ...) op.


@dataclass(frozen=True)
class _Icon:
    w: float
    h: float
    layers: tuple[tuple[tuple[int, int, int], tuple], ...]  # (rgb, ops)
    paper_size: bool = False  # fixed paper size: ignore the style's icon-size


def _icon_scale(icon: _Icon, size: float, px_mm: float) -> float:
    """pt per icon unit: px_mm per two units (sprites are @2x), times icon-size."""
    return (1.0 if icon.paper_size else size) * px_mm * mm / PIXEL_RATIO


_K = (0, 0, 0)

# Symbols copied from the user's reference print map: its PDF path operators,
# in its units of 0.04 mm on paper, y up, origin at the symbol's anchor. They
# print at the reference's size at 1:25 000 and scale like the other icons.
_REF_UNIT = 0.04 / (PROFILES[25000].px_mm / PIXEL_RATIO)  # icon units per ref unit
_REF_LINE = 2.5  # the reference's symbol line: 0.1 mm


_REF_OPS = frozenset({"m", "l", "c", "h", "S", "s", "f", "rg", "RG", "q", "Q"})


def _parse_ref(text: str) -> tuple[tuple[str, tuple[float, ...]], ...]:
    """PDF operators with their operands, from reference path text (parsed once)."""
    ops: list[tuple[str, tuple[float, ...]]] = []
    nums: list[float] = []
    for tok in text.split():
        if tok in _REF_OPS:
            ops.append((tok, tuple(nums)))
            nums = []
        else:
            nums.append(float(tok))
    return tuple(ops)


def _ref_icon(text: str) -> _Icon:
    """An icon from reference path text, anchored like the reference.

    The reference puts each symbol's own origin on the map point (the base of a
    tree symbol, a mast's dot), so the icon box is made symmetric around it.
    Printed at the reference's paper size: the style's ``icon-size`` (tuned
    for mmlv2's own icons) does not apply.
    """
    ops = _parse_ref(text)
    coords = [v for op, args in ops if op in ("m", "l", "c") for v in args]
    pad = _REF_LINE / 2
    half_w = (max(abs(v) for v in coords[0::2]) + pad) * _REF_UNIT
    half_h = (max(abs(v) for v in coords[1::2]) + pad) * _REF_UNIT
    return _Icon(
        2 * half_w, 2 * half_h, ((_K, (("ref", text, half_w, half_h, ops),)),), paper_size=True
    )


# ------------------------------------------------------------------ symbols.json

SYMBOLS_PATH = Path(__file__).resolve().parent / "styles" / "symbols.json"

_NOTE_KEYS = frozenset({"note", "notes"})
_PATTERN_KINDS: dict[str, type] = {"hatch": _Hatch, "hlines": _HLines, "triangles": _Triangles}
# argument kinds per op: "n" number, "p" point [x, y], "P" list of points
_OP_ARGS = {"seg": "Pn", "bar": "ppn", "poly": "P", "disc": "nnn", "ring": "nnnn"}
_MIN_POINTS = {"seg": 2, "poly": 3}


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_keys(raw: Any, required: set[str], optional: set[str], where: str) -> None:
    if not isinstance(raw, dict):
        raise StyleError(f"{where}: must be an object")
    allowed = required | optional | _NOTE_KEYS
    extra = sorted(set(raw) - allowed)
    if extra:
        raise StyleError(f"{where}: unknown key(s) {extra}; allowed: {sorted(allowed)}")
    missing = sorted(required - set(raw))
    if missing:
        raise StyleError(f"{where}: missing {missing}")


def _rgb_value(v: Any, where: str) -> tuple[int, int, int]:
    if not (
        isinstance(v, list)
        and len(v) == 3
        and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in v)
    ):
        raise StyleError(f"{where}: rgb must be [r, g, b] with integers 0-255")
    return (v[0], v[1], v[2])


def _point(v: Any, where: str) -> tuple[float, float]:
    if not (isinstance(v, list) and len(v) == 2 and all(_is_number(c) for c in v)):
        raise StyleError(f"{where}: expected a point [x, y], got {v!r}")
    return (v[0], v[1])


def _points(v: Any, n_min: int, where: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(v, list) or len(v) < n_min:
        raise StyleError(f"{where}: expected a list of at least {n_min} points")
    return tuple(_point(p, where) for p in v)


def _pattern(name: str, raw: Any) -> Any:
    where = f"pattern {name!r}"
    kind = raw.get("kind") if isinstance(raw, dict) else None
    cls = _PATTERN_KINDS.get(kind)  # type: ignore[arg-type]
    if cls is None:
        raise StyleError(f"{where}: kind must be one of {sorted(_PATTERN_KINDS)}, got {kind!r}")
    names = {f.name for f in fields(cls)}
    _check_keys(raw, names | {"kind"}, set(), where)
    args: dict[str, Any] = {}
    for key in names:
        value = raw[key]
        if key == "rgb":
            args[key] = _rgb_value(value, where)
        elif key == "points":
            args[key] = _points(value, 1, where)
        elif key in ("tile", "direction"):
            if not isinstance(value, int) or isinstance(value, bool):
                raise StyleError(f"{where}: {key} must be an integer")
            if key == "direction" and value not in (1, -1):
                raise StyleError(f"{where}: direction must be 1 or -1")
            args[key] = value
        elif not _is_number(value):
            raise StyleError(f"{where}: {key} must be a number")
        else:
            args[key] = value
    return cls(**args)


def _op(raw: Any, where: str) -> tuple:
    if not isinstance(raw, list) or not raw or raw[0] not in _OP_ARGS:
        name = raw[0] if isinstance(raw, list) and raw else raw
        raise StyleError(f"{where}: unknown op {name!r}; ops: {sorted(_OP_ARGS)}")
    kind, args = raw[0], raw[1:]
    spec = _OP_ARGS[kind]
    where = f"{where} op {kind!r}"
    if len(args) != len(spec):
        raise StyleError(f"{where}: expected {len(spec)} arguments, got {len(args)}")
    out: list[Any] = [kind]
    for t, a in zip(spec, args, strict=True):
        if t == "n":
            if not _is_number(a):
                raise StyleError(f"{where}: expected a number, got {a!r}")
            out.append(a)
        elif t == "p":
            out.append(_point(a, where))
        else:
            out.append(_points(a, _MIN_POINTS[kind], where))
    return tuple(out)


def _icon_from(name: str, raw: Any) -> _Icon:
    where = f"icon {name!r}"
    if isinstance(raw, dict) and "path" in raw:
        _check_keys(raw, {"path", "anchor"}, set(), where)
        if raw["anchor"] != "origin":
            raise StyleError(f"{where}: anchor must be 'origin'")
        text = raw["path"]
        try:
            if not isinstance(text, str) or not _parse_ref(text):
                raise ValueError
            return _ref_icon(text)
        except ValueError:
            raise StyleError(f"{where}: path is not PDF path text") from None
    _check_keys(raw, {"size", "layers"}, set(), where)
    w, h = _point(raw["size"], f"{where} size")
    layers = raw["layers"]
    if not isinstance(layers, list) or not layers:
        raise StyleError(f"{where}: layers must be a non-empty list")
    out = []
    for i, layer in enumerate(layers):
        lw = f"{where} layer {i}"
        _check_keys(layer, {"rgb", "ops"}, set(), lw)
        if not isinstance(layer["ops"], list) or not layer["ops"]:
            raise StyleError(f"{lw}: ops must be a non-empty list")
        out.append((_rgb_value(layer["rgb"], lw), tuple(_op(op, lw) for op in layer["ops"])))
    return _Icon(w, h, tuple(out))


def load_symbols(path: Path = SYMBOLS_PATH) -> tuple[dict[str, Any], dict[str, _Icon]]:
    """(patterns, icons) from ``path``, validated (unknown keys or ops raise StyleError)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    _check_keys(raw, {"patterns", "icons"}, set(), path.name)
    for key in ("patterns", "icons"):
        if not isinstance(raw[key], dict):
            raise StyleError(f"{path.name}: {key} must be an object")
    patterns = {name: _pattern(name, p) for name, p in raw["patterns"].items()}
    icons = {name: _icon_from(name, ic) for name, ic in raw["icons"].items()}
    return patterns, icons


_PATTERNS, _ICONS = load_symbols()
PATTERN_NAMES = frozenset(_PATTERNS)
ICON_NAMES = frozenset(_ICONS)


def _ref_path(c: Canvas, ops: tuple[tuple[str, tuple[float, ...]], ...]) -> None:
    """Draw parsed reference operators: paths (m l c h), paint (S s f), colours, q/Q."""
    path = c.beginPath()
    for op, args in ops:
        if op == "m":
            path.moveTo(*args)
        elif op == "l":
            path.lineTo(*args)
        elif op == "c":
            path.curveTo(*args)
        elif op in ("h", "s"):
            path.close()
        elif op == "rg":
            c.setFillColorRGB(*args)
        elif op == "RG":
            c.setStrokeColorRGB(*args)
        elif op == "q":
            c.saveState()
        elif op == "Q":
            c.restoreState()
        if op in ("S", "s"):
            c.drawPath(path, stroke=1, fill=0)
            path = c.beginPath()
        elif op == "f":
            c.drawPath(path, stroke=0, fill=1)
            path = c.beginPath()


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
        elif kind == "ref":  # ("ref", text, x, y, parsed ops): reference units, y up
            c.saveState()
            c.translate(op[2], op[3])
            c.scale(_REF_UNIT, -_REF_UNIT)
            c.setLineWidth(_REF_LINE)
            c.setLineCap(0)
            c.setLineJoin(0)
            _ref_path(c, op[4])
            c.restoreState()


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
        s = _icon_scale(icon, size, px_mm)
        c.translate(x, y)
        c.rotate(-rotation_deg)  # style rotation is clockwise, PDF's is anticlockwise
        c.scale(s, -s)
        c.translate(-icon.w / 2, -icon.h / 2)
        for rgb, ops in icon.layers:
            _draw_ops(c, ops, rgb)
        c.restoreState()

    def draw_icon_layer(self, c, frame, layer, features, zoom, px_mm) -> None:
        """Draw an unconditional icon layer (for draw_fill_line_layers)."""
        draw_icon_layer(c, frame, layer, features, zoom, px_mm, self)


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
    s = _icon_scale(icon, size, px_mm)
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
        if ly.type == "symbol" and is_drawn_icon_layer(ly) and ly.visible_at(zoom)
    ]


def is_drawn_icon_layer(layer: StyleLayer) -> bool:
    """An icon-only layer whose icons are drawn unconditionally (no collisions)."""
    return layer.type == "symbol" and "icon-image" in layer.layout and not placed_by_labels(layer)


def draw_icon_layer(
    c: Canvas,
    frame: MapFrame,
    layer: StyleLayer,
    features: list[Feature],
    zoom: float,
    px_mm: float,
    symbols: Symbols,
) -> None:
    """Draw one unconditional icon layer's icons (see :func:`is_drawn_icon_layer`)."""
    from .draw import _matching

    for f, ctx in _matching(layer, features, zoom, ("Point",)):
        name = layer.get("icon-image", ctx)
        if not name or name in _BLANK:
            continue
        opacity = layer.number("icon-opacity", ctx, 1.0)
        if opacity <= 0:
            continue
        size = layer.number("icon-size", ctx, 1.0)
        rotation = layer.number("icon-rotate", ctx, 0.0)
        for pt in parts(f.geometry):
            if pt.is_empty:
                continue
            x, y = frame.to_pt(pt.x, pt.y)
            c.saveState()
            c.setFillAlpha(opacity)
            c.setStrokeAlpha(opacity)
            symbols.draw_icon(c, name, x, y, size, rotation, px_mm)
            c.restoreState()


def draw_icon_layers(
    c: Canvas,
    frame: MapFrame,
    style: Style,
    features_by_layer: dict[str, list[Feature]],
    zoom: float,
    px_mm: float,
    symbols: Symbols,
) -> None:
    """Draw every unconditional icon layer, in style order (icons only).

    The map itself draws these interleaved with the fills and lines
    (``draw.draw_fill_line_layers``); all other icons are placed by ``labels.place``.
    """
    for layer in _icon_layers(style, zoom):
        features = features_by_layer.get(layer.source_layer or "", [])
        draw_icon_layer(c, frame, layer, features, zoom, px_mm, symbols)
