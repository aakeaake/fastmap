"""Draw style fill and line layers as ReportLab vector paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import shapely
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import FILL_NON_ZERO, Canvas
from shapely.geometry.polygon import orient

from fastmap.services.print_layout import Extent

from .colors import parse_color
from .expressions import EvalContext, filter_matches
from .geometry import outline as polygon_outline
from .model import Feature
from .style import Style, StyleLayer

OUTLINE_PX = 0.25
MITER_LIMIT = 2.0  # MapLibre default line-miter-limit
_CAPS = {"butt": 0, "round": 1, "square": 2}
_JOINS = {"miter": 0, "round": 1, "bevel": 2}


class PatternDrawer(Protocol):
    """What draw needs from the Task 7 ``Symbols`` class."""

    def draw_pattern(
        self,
        c: Canvas,
        name: str,
        clip_path: Any,
        bbox_pt: tuple[float, float, float, float],
        px_mm: float,
    ) -> None: ...


@dataclass(frozen=True)
class MapFrame:
    """Maps EPSG:3067 metres in ``extent`` onto the page rectangle (pt)."""

    extent: Extent
    x0: float
    y0: float
    w: float
    h: float

    @property
    def sx(self) -> float:
        return self.w / self.extent.width_m

    @property
    def sy(self) -> float:
        return self.h / self.extent.height_m

    def to_pt(self, x: float, y: float) -> tuple[float, float]:
        return (
            self.x0 + (x - self.extent.minx) * self.sx,
            self.y0 + (y - self.extent.miny) * self.sy,
        )

    def geom_to_pt(self, geom):
        scale = np.array([self.sx, self.sy])
        offset = np.array(
            [self.x0 - self.extent.minx * self.sx, self.y0 - self.extent.miny * self.sy]
        )
        return shapely.transform(geom, lambda a: a * scale + offset)


def background_color(style: Style, zoom: float) -> tuple[float, float, float, float]:
    """The style's visible background layer colour (with opacity); white if none."""
    ctx = EvalContext({}, zoom, "Polygon")
    for layer in style.layers:
        if layer.type == "background" and layer.visible_at(zoom):
            r, g, b, a = parse_color(layer.get("background-color", ctx, "#000000"))
            return (r, g, b, a * float(layer.get("background-opacity", ctx, 1.0)))
    return (1.0, 1.0, 1.0, 1.0)


def _parts(geom):
    return getattr(geom, "geoms", [geom])


def _add_coords(path, coords, close: bool) -> None:
    if len(coords) < 2:
        return
    path.moveTo(*coords[0][:2])
    for x, y in coords[1:, :2]:
        path.lineTo(x, y)
    if close:
        path.close()


def _polygon_path(c: Canvas, geoms):
    path = c.beginPath()
    for g in geoms:
        for poly in _parts(g):
            if poly.is_empty:
                continue
            poly = orient(poly, 1.0)
            _add_coords(path, np.asarray(poly.exterior.coords), True)
            for ring in poly.interiors:
                _add_coords(path, np.asarray(ring.coords), True)
    return path


def _line_path(c: Canvas, geoms):
    path = c.beginPath()
    for g in geoms:
        for line in _parts(g):
            if not line.is_empty:
                _add_coords(path, np.asarray(line.coords), False)
    return path


def _as_lines(geom, tile_m: float | None):
    """Polygon outlines as lines (line layers on polygon sources draw outlines)."""
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return polygon_outline(geom, tile_m)
    return geom


def _matching(layer: StyleLayer, features: list[Feature], zoom: float, types: tuple[str, ...]):
    for f in features:
        if f.geom_type not in types:
            continue
        ctx = EvalContext(f.props, zoom, f.geom_type)
        if layer.filter is None or filter_matches(layer.filter, ctx):
            yield f, ctx


def _sorted_groups(groups: dict) -> list:
    """Groups keyed by (sort_key, style...) in ascending sort-key order (stable)."""
    return sorted(groups.items(), key=lambda kv: kv[0][0])


def _sort_key(layer: StyleLayer, prop: str, ctx: EvalContext) -> float:
    value = layer.get(prop, ctx, 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _draw_fill_layer(c, frame, layer, features, zoom, px_mm, symbols, tile_m) -> None:
    pattern = "fill-pattern" in layer.paint
    if pattern and symbols is None:
        return
    groups: dict[tuple, list] = {}
    for f, ctx in _matching(layer, features, zoom, ("Polygon",)):
        opacity = float(layer.get("fill-opacity", ctx, 1.0))
        if opacity <= 0:
            continue
        sort_key = _sort_key(layer, "fill-sort-key", ctx)
        if pattern:
            name = layer.get("fill-pattern", ctx)
            if not name:
                continue
            key = (sort_key, name, opacity)
        else:
            fill = parse_color(layer.get("fill-color", ctx, "#000000"))
            outline = None
            if "fill-outline-color" in layer.paint and layer.get("fill-antialias", ctx, True):
                outline = parse_color(layer.get("fill-outline-color", ctx))
                if outline[3] <= 0:
                    outline = None
            if fill[3] <= 0 and outline is None:
                continue
            key = (sort_key, fill, outline, opacity)
        groups.setdefault(key, []).append(f.geometry)

    for key, geoms in _sorted_groups(groups):
        geoms_pt = [frame.geom_to_pt(g) for g in geoms]
        path = _polygon_path(c, geoms_pt)
        c.saveState()
        if pattern:
            _, name, opacity = key
            minx, miny, maxx, maxy = shapely.total_bounds(geoms_pt)
            c.setFillAlpha(opacity)
            c.setStrokeAlpha(opacity)
            symbols.draw_pattern(c, name, path, (minx, miny, maxx, maxy), px_mm)
        else:
            _, fill, outline, opacity = key
            if fill[3] > 0:
                c.setFillColorRGB(*fill[:3])
                c.setFillAlpha(fill[3] * opacity)
                c.drawPath(path, stroke=0, fill=1, fillMode=FILL_NON_ZERO)
            if outline is not None:
                c.setStrokeColorRGB(*outline[:3])
                c.setStrokeAlpha(outline[3] * opacity)
                c.setLineWidth(OUTLINE_PX * px_mm * mm)
                lines = [frame.geom_to_pt(polygon_outline(g, tile_m)) for g in geoms]
                c.drawPath(_line_path(c, lines), stroke=1, fill=0)
        c.restoreState()


def _draw_line_layer(c, frame, layer, features, zoom, px_mm, tile_m) -> None:
    px_pt = px_mm * mm
    groups: dict[tuple, list] = {}
    for f, ctx in _matching(layer, features, zoom, ("LineString", "Polygon")):
        color = parse_color(layer.get("line-color", ctx, "#000000"))
        opacity = float(layer.get("line-opacity", ctx, 1.0))
        width = float(layer.get("line-width", ctx, 1.0)) * px_pt
        alpha = color[3] * opacity
        if alpha <= 0 or width <= 0:
            continue
        dash = layer.get("line-dasharray", ctx)
        dash_pt = tuple(float(d) * width for d in dash) if dash else ()
        if not any(dash_pt):
            dash_pt = ()
        cap = _CAPS.get(layer.get("line-cap", ctx, "butt"), 0)
        join = _JOINS.get(layer.get("line-join", ctx, "miter"), 0)
        offset = float(layer.get("line-offset", ctx, 0.0)) * px_pt
        lines = _as_lines(f.geometry, tile_m)
        if lines.is_empty:
            continue
        geom = frame.geom_to_pt(lines)
        if offset:
            # MapLibre: positive offset is to the right; shapely: positive is left.
            geom = shapely.offset_curve(geom, -offset)
            if geom.is_empty:
                continue
        key = (_sort_key(layer, "line-sort-key", ctx), color[:3], alpha, width, dash_pt, cap, join)
        groups.setdefault(key, []).append(geom)

    for key, geoms in _sorted_groups(groups):
        _, rgb, alpha, width, dash_pt, cap, join = key
        c.saveState()
        c.setStrokeColorRGB(*rgb)
        c.setStrokeAlpha(alpha)
        c.setLineWidth(width)
        c.setLineCap(cap)
        c.setLineJoin(join)
        c.setMiterLimit(MITER_LIMIT)
        if dash_pt:
            c.setDash(list(dash_pt), 0)
        c.drawPath(_line_path(c, geoms), stroke=1, fill=0)
        c.restoreState()


def draw_fill_line_layers(
    c: Canvas,
    frame: MapFrame,
    style: Style,
    features_by_layer: dict[str, list[Feature]],
    zoom: float,
    px_mm: float,
    symbols: PatternDrawer | None = None,
    tile_m: float | None = None,
) -> None:
    """Draw every visible fill and line layer of ``style`` in style order.

    Features sharing the same evaluated paint are batched into one path.
    Fill-pattern layers go to ``symbols`` (skipped when it is None); symbol,
    background and raster layers are not drawn here. Polygon outlines leave
    out stretches along the edges of ``tile_m`` tile cells (clipping seams).
    """
    for layer in style.layers:
        if layer.type not in ("fill", "line") or not layer.visible_at(zoom):
            continue
        features = features_by_layer.get(layer.source_layer or "", [])
        if not features:
            continue
        if layer.type == "fill":
            _draw_fill_layer(c, frame, layer, features, zoom, px_mm, symbols, tile_m)
        else:
            _draw_line_layer(c, frame, layer, features, zoom, px_mm, tile_m)
