"""Collision-aware placement of map labels and placed icons (simplified MapLibre).

Candidates are collected from the style's symbol layers, sorted by priority and placed
greedily: a candidate is kept only if its collision boxes stay inside the map frame and
do not overlap boxes already placed. Point labels try their variable anchors in order;
line labels are laid out glyph by glyph along the line every ``symbol-spacing``.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from shapely.geometry import LineString

from .colors import parse_color
from .draw import MapFrame, _matching
from .expressions import EvalContext
from .fonts import font_for, register_fonts
from .model import Feature
from .style import Style, StyleLayer
from .symbols import Symbols, icon_size_pt, placed_by_labels

LINE_HEIGHT = 1.2  # ems, MapLibre text-line-height default
CAP_MIDDLE = 0.36  # ems from the baseline to the middle of capitals and digits
CAP_HEIGHT = 0.72  # ems, Noto Sans cap height (rounded)
DEFAULT_SPACING_PX = 250
DEFAULT_MAX_ANGLE = 45.0
DEFAULT_MAX_WIDTH_EMS = 10
DEFAULT_PADDING_PX = 2
GRID_CELL_PT = 24.0
_BLANK = ("", "#blank")
_TOKEN = re.compile(r"\{([^{}]+)\}")

Box = tuple[float, float, float, float]  # minx, miny, maxx, maxy in pt


@dataclass
class Candidate:
    text: str
    font: str
    size_pt: float
    color: tuple[float, float, float, float]
    halo_color: tuple[float, float, float, float]
    halo_pt: float
    priority: tuple
    anchor_pts: list[tuple[float, float, float]]  # (x, y, angle) in pt, point placement
    line: LineString | None  # in pt, line placement
    icon: str | None
    allow_overlap: bool
    ignore_placement: bool
    padding_pt: float
    variable_anchors: list[str]
    spacing_pt: float = DEFAULT_SPACING_PX * 0.28 * mm
    max_angle: float = DEFAULT_MAX_ANGLE
    icon_size: float = 1.0
    icon_rotate: float = 0.0  # degrees clockwise
    icon_offset_pt: tuple[float, float] = (0.0, 0.0)  # style direction: +y is down
    icon_opacity: float = 1.0
    icon_allow_overlap: bool = False
    icon_ignore_placement: bool = False
    px_mm: float = 0.28


@dataclass
class Placement:
    candidate: Candidate
    glyphs: list[tuple[str, float, float, float]]  # (text, x, y baseline-left, angle CCW°)
    anchor: str | None = None
    icon_xy: tuple[float, float] | None = None


# ------------------------------------------------------------------ text helpers


@lru_cache(maxsize=8192)
def _advance(ch: str, font: str) -> float:
    """Advance width of ``ch`` in ems."""
    return stringWidth(ch, font, 1000) / 1000


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _text(layer: StyleLayer, ctx: EvalContext) -> str:
    raw = layer.layout.get("text-field")
    if raw is None:
        return ""
    if isinstance(raw, str):  # legacy "{prop}" token string
        value = _TOKEN.sub(lambda m: _as_text(ctx.props.get(m.group(1))), raw)
    else:
        value = _as_text(layer.get("text-field", ctx))
    transform = layer.get("text-transform", ctx, "none")
    if transform == "uppercase":
        value = value.upper()
    elif transform == "lowercase":
        value = value.lower()
    return value.strip()


def _wrap(text: str, font: str, max_ems: float) -> str:
    """Greedy word wrap at ``max_ems`` (widths measured at font size 1)."""
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}" if line else word
            if line and stringWidth(trial, font, 1) > max_ems:
                lines.append(line.strip())
                line = word
            else:
                line = trial
        lines.append(line.strip())
    return "\n".join(lines)


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


# ------------------------------------------------------------------ collection


def _priority(layer: StyleLayer, ctx: EvalContext, index: int) -> tuple:
    key = _number(layer.get("symbol-sort-key", ctx))
    if key is None:
        key = _number(ctx.props.get("prioriteetti")) or 0.0
    relevance = _number(ctx.props.get("mittakaavarelevanssi")) or 0.0
    return (key, -relevance, index)


def _alpha(color: tuple[float, float, float, float], opacity: float):
    return (color[0], color[1], color[2], color[3] * opacity)


def _icon_fields(layer: StyleLayer, ctx: EvalContext, px_pt: float) -> dict:
    name = layer.get("icon-image", ctx)
    opacity = float(layer.get("icon-opacity", ctx, 1.0))
    if not name or name in _BLANK or opacity <= 0:
        return {}
    size = float(layer.get("icon-size", ctx, 1.0))
    ox, oy = (layer.get("icon-offset", ctx) or [0, 0])[:2]
    return {
        "icon": name,
        "icon_size": size,
        "icon_rotate": float(layer.get("icon-rotate", ctx, 0.0)),
        "icon_offset_pt": (float(ox) * size * px_pt, float(oy) * size * px_pt),
        "icon_opacity": opacity,
        "icon_allow_overlap": bool(layer.get("icon-allow-overlap", ctx, False)),
        "icon_ignore_placement": bool(layer.get("icon-ignore-placement", ctx, False)),
    }


def _layer_candidates(layer, index, features, zoom, frame, px_mm, with_icons):
    px_pt = px_mm * mm
    for f, ctx in _matching(layer, features, zoom, ("Point", "LineString", "Polygon")):
        line_placement = layer.get("symbol-placement", ctx, "point") != "point"
        if line_placement == (f.geom_type == "Point"):
            continue  # point placement needs points, line placement needs lines/rings
        icon = _icon_fields(layer, ctx, px_pt) if with_icons and not line_placement else {}
        text = _text(layer, ctx)
        size_pt = float(layer.get("text-size", ctx, 16)) * px_pt
        opacity = float(layer.get("text-opacity", ctx, 1.0))
        if size_pt <= 0 or opacity <= 0:
            text = ""
        if not text and not icon:
            continue
        font = font_for(layer.get("text-font", ctx, ["Noto Sans Regular"]))
        if text and not line_placement:
            max_ems = float(layer.get("text-max-width", ctx, DEFAULT_MAX_WIDTH_EMS))
            text = _wrap(text, font, max_ems)
        variable = layer.get("text-variable-anchor", ctx) or []
        common = dict(
            text=text,
            font=font,
            size_pt=size_pt,
            color=_alpha(parse_color(layer.get("text-color", ctx, "#000000")), opacity),
            halo_color=_alpha(
                parse_color(layer.get("text-halo-color", ctx, "rgba(0,0,0,0)")), opacity
            ),
            halo_pt=float(layer.get("text-halo-width", ctx, 0.0)) * px_pt,
            priority=_priority(layer, ctx, index),
            icon=None,
            allow_overlap=bool(layer.get("text-allow-overlap", ctx, False)),
            ignore_placement=bool(layer.get("text-ignore-placement", ctx, False)),
            padding_pt=float(layer.get("text-padding", ctx, DEFAULT_PADDING_PX)) * px_pt,
            variable_anchors=list(variable) or [layer.get("text-anchor", ctx, "center")],
            spacing_pt=float(layer.get("symbol-spacing", ctx, DEFAULT_SPACING_PX)) * px_pt,
            max_angle=float(layer.get("text-max-angle", ctx, DEFAULT_MAX_ANGLE)),
            px_mm=px_mm,
        )
        common.update(icon)
        if line_placement:
            geom = f.geometry.boundary if f.geom_type == "Polygon" else f.geometry
            for part in getattr(geom, "geoms", [geom]):
                if not part.is_empty and part.length > 0:
                    yield Candidate(anchor_pts=[], line=frame.geom_to_pt(part), **common)
        else:
            pts = [frame.to_pt(p.x, p.y) for p in getattr(f.geometry, "geoms", [f.geometry])]
            yield Candidate(anchor_pts=[(x, y, 0.0) for x, y in pts], line=None, **common)


def collect_candidates(
    style: Style,
    features_by_layer: dict[str, list[Feature]],
    zoom: float,
    frame: MapFrame,
    px_mm: float,
) -> list[Candidate]:
    """Label (and placed-icon) candidates of every visible symbol layer."""
    register_fonts()
    out: list[Candidate] = []
    for index, layer in enumerate(style.layers):
        if layer.type != "symbol" or not layer.visible_at(zoom):
            continue
        with_icons = "icon-image" in layer.layout and placed_by_labels(layer)
        if "text-field" not in layer.layout and not with_icons:
            continue
        features = features_by_layer.get(layer.source_layer or "", [])
        out.extend(_layer_candidates(layer, index, features, zoom, frame, px_mm, with_icons))
    return out


# ------------------------------------------------------------------ collision index


class _Grid:
    """Uniform grid of placed boxes; insert and overlap query are ~O(1) per box."""

    def __init__(self, cell: float = GRID_CELL_PT):
        self.cell = cell
        self.cells: dict[tuple[int, int], list[Box]] = defaultdict(list)

    def _keys(self, b: Box):
        c = self.cell
        for i in range(math.floor(b[0] / c), math.floor(b[2] / c) + 1):
            for j in range(math.floor(b[1] / c), math.floor(b[3] / c) + 1):
                yield (i, j)

    def hits(self, b: Box) -> bool:
        for key in self._keys(b):
            for o in self.cells.get(key, ()):
                if o[0] < b[2] and b[0] < o[2] and o[1] < b[3] and b[1] < o[3]:
                    return True
        return False

    def add(self, b: Box) -> None:
        for key in self._keys(b):
            self.cells[key].append(b)


def _inside(b: Box, bounds: Box) -> bool:
    return b[0] >= bounds[0] and b[1] >= bounds[1] and b[2] <= bounds[2] and b[3] <= bounds[3]


def _pad(b: Box, p: float) -> Box:
    return (b[0] - p, b[1] - p, b[2] + p, b[3] + p)


def _rotated_box(cx: float, cy: float, w: float, h: float, angle_deg: float) -> Box:
    a = math.radians(angle_deg)
    ca, sa = abs(math.cos(a)), abs(math.sin(a))
    hw, hh = (w * ca + h * sa) / 2, (w * sa + h * ca) / 2
    return (cx - hw, cy - hh, cx + hw, cy + hh)


def _fits(box: Box, bounds: Box, grid: _Grid, pad: float, allow_overlap: bool) -> bool:
    return _inside(box, bounds) and (allow_overlap or not grid.hits(_pad(box, pad)))


# ------------------------------------------------------------------ point placement


def _anchor_origin(anchor: str, ax: float, ay: float, w: float, h: float):
    """Top-left corner of a w x h text block placed with ``anchor`` at (ax, ay)."""
    if anchor.endswith("left"):
        left = ax
    elif anchor.endswith("right"):
        left = ax - w
    else:
        left = ax - w / 2
    if anchor.startswith("top"):
        top = ay
    elif anchor.startswith("bottom"):
        top = ay + h
    else:
        top = ay + h / 2
    return left, top


def _icon_box(cand: Candidate, ax: float, ay: float) -> tuple[Box, tuple[float, float]]:
    w, h = icon_size_pt(cand.icon, cand.icon_size, cand.px_mm)
    a = math.radians(cand.icon_rotate)  # clockwise on screen (y down)
    ox, oy = cand.icon_offset_pt
    dx = ox * math.cos(a) - oy * math.sin(a)
    dy = ox * math.sin(a) + oy * math.cos(a)
    x, y = ax + dx, ay - dy  # page y is up
    return _rotated_box(x, y, w, h, cand.icon_rotate), (x, y)


def _place_point(cand: Candidate, anchor_pt, grid: _Grid, bounds: Box) -> Placement | None:
    ax, ay, _ = anchor_pt
    pad = cand.padding_pt
    icon_box = icon_xy = None
    if cand.icon:
        icon_box, icon_xy = _icon_box(cand, ax, ay)
        if not _fits(icon_box, bounds, grid, pad, cand.icon_allow_overlap):
            return None
    glyphs: list[tuple[str, float, float, float]] = []
    text_box = chosen = None
    if cand.text:
        size = cand.size_pt
        lines = cand.text.split("\n")
        widths = [stringWidth(t, cand.font, size) for t in lines]
        w, lh = max(widths), LINE_HEIGHT * size
        h = lh * len(lines)
        for anchor in cand.variable_anchors or ["center"]:
            left, top = _anchor_origin(anchor, ax, ay, w, h)
            box = (left, top - h, left + w, top)
            if _fits(box, bounds, grid, pad, cand.allow_overlap):
                text_box, chosen = box, anchor
                break
        if text_box is None:
            return None
        for i, (t, lw) in enumerate(zip(lines, widths, strict=True)):
            baseline = top - (i + 1) * lh + (lh - CAP_HEIGHT * size) / 2
            glyphs.append((t, left + (w - lw) / 2, baseline, 0.0))
        if not cand.ignore_placement:
            grid.add(_pad(text_box, pad))
    if icon_box is not None and not cand.icon_ignore_placement:
        grid.add(_pad(icon_box, pad))
    return Placement(cand, glyphs, chosen, icon_xy)


# ------------------------------------------------------------------ line placement


def _normalize(angle: np.ndarray) -> np.ndarray:
    return (angle + 180.0) % 360.0 - 180.0


def _place_line(cand: Candidate, grid: _Grid, bounds: Box) -> list[Placement]:
    coords = np.asarray(cand.line.coords)[:, :2]
    seg = np.diff(coords, axis=0)
    seglen = np.hypot(seg[:, 0], seg[:, 1])
    keep = seglen > 1e-9
    if not keep.any() or not cand.text:
        return []
    coords = np.vstack([coords[:1], coords[1:][keep]])
    seg, seglen = seg[keep], seglen[keep]
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    total = cum[-1]
    seg_angle = np.degrees(np.arctan2(seg[:, 1], seg[:, 0]))

    size = cand.size_pt
    chars = list(cand.text)
    adv = np.array([_advance(ch, cand.font) * size for ch in chars])
    width = adv.sum()
    if width <= 0 or width > total:
        return []
    offs = np.cumsum(adv) - adv / 2 - width / 2  # glyph centres relative to label centre
    spacing = max(cand.spacing_pt, 1e-6)
    centres = [total / 2] if total < spacing else np.arange(spacing / 2, total, spacing)

    def at(s):
        return np.interp(s, cum, coords[:, 0]), np.interp(s, cum, coords[:, 1])

    out = []
    for dc in centres:
        if dc - width / 2 < 0 or dc + width / 2 > total:
            continue
        (x0, x1), _ = at(np.array([dc - width / 2, dc + width / 2]))
        flip = x1 < x0  # keep text reading left to right
        s = dc - offs if flip else dc + offs
        k = np.clip(np.searchsorted(cum, s, side="right") - 1, 0, len(seg) - 1)
        angles = _normalize(seg_angle[k] + (180.0 if flip else 0.0))
        if len(angles) > 1 and np.abs(_normalize(np.diff(angles))).max() > cand.max_angle:
            continue
        gx, gy = at(s)
        boxes = [
            _rotated_box(x, y, a_w, size, a)
            for x, y, a_w, a in zip(gx, gy, adv, angles, strict=True)
        ]
        if not all(_fits(b, bounds, grid, cand.padding_pt, cand.allow_overlap) for b in boxes):
            continue
        glyphs = []
        for ch, x, y, a_w, a in zip(chars, gx, gy, adv, angles, strict=True):
            if ch.isspace():
                continue
            r = math.radians(a)
            ux, uy = -a_w / 2, -CAP_MIDDLE * size  # glyph origin relative to its centre
            ox = x + ux * math.cos(r) - uy * math.sin(r)
            oy = y + ux * math.sin(r) + uy * math.cos(r)
            glyphs.append((ch, float(ox), float(oy), float(a)))
        if not cand.ignore_placement:
            for b in boxes:
                grid.add(_pad(b, cand.padding_pt))
        out.append(Placement(cand, glyphs))
    return out


# ------------------------------------------------------------------ public API


def place(candidates: list[Candidate], frame: MapFrame) -> list[Placement]:
    """Greedy collision-aware placement in priority order (lowest tuple first)."""
    bounds = (frame.x0, frame.y0, frame.x0 + frame.w, frame.y0 + frame.h)
    grid = _Grid()
    out: list[Placement] = []
    for cand in sorted(candidates, key=lambda c: c.priority):
        if cand.line is not None:
            out.extend(_place_line(cand, grid, bounds))
            continue
        for anchor_pt in cand.anchor_pts:
            placement = _place_point(cand, anchor_pt, grid, bounds)
            if placement is not None:
                out.append(placement)
    return out


def _text_pass(c: Canvas, p: Placement, mode: int) -> None:
    cand = p.candidate
    t = c.beginText()
    t.setFont(cand.font, cand.size_pt)
    t.setTextRenderMode(mode)
    for text, x, y, angle in p.glyphs:
        if angle:
            r = math.radians(angle)
            cos, sin = math.cos(r), math.sin(r)
            t.setTextTransform(cos, sin, -sin, cos, x, y)
        else:
            t.setTextOrigin(x, y)
        t.textOut(text)
    c.drawText(t)


def draw(c: Canvas, placements: list[Placement]) -> None:
    """Draw placed icons, then text halos (stroked text), then the filled text."""
    symbols = Symbols()
    for p in placements:
        cand = p.candidate
        if p.icon_xy is None:
            continue
        c.saveState()
        c.setFillAlpha(cand.icon_opacity)
        c.setStrokeAlpha(cand.icon_opacity)
        symbols.draw_icon(c, cand.icon, *p.icon_xy, cand.icon_size, cand.icon_rotate, cand.px_mm)
        c.restoreState()
    texts = [p for p in placements if p.glyphs]
    # Text render mode lives in the graphics state and ReportLab only emits a change
    # from its own default, so the stroked halo pass gets its own save/restore.
    c.saveState()
    c.setLineJoin(1)
    c.setLineCap(1)
    for p in texts:
        cand = p.candidate
        if cand.halo_pt <= 0 or cand.halo_color[3] <= 0:
            continue
        c.setStrokeColorRGB(*cand.halo_color[:3])
        c.setStrokeAlpha(cand.halo_color[3])
        c.setLineWidth(2 * cand.halo_pt)
        _text_pass(c, p, 1)
    c.restoreState()
    c.saveState()
    for p in texts:
        cand = p.candidate
        if cand.color[3] <= 0:
            continue
        c.setFillColorRGB(*cand.color[:3])
        c.setFillAlpha(cand.color[3])
        _text_pass(c, p, 0)
    c.restoreState()
