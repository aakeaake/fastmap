"""Draw style fill and line layers as ReportLab vector paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Protocol

import numpy as np
import shapely
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import FILL_NON_ZERO, Canvas
from reportlab.pdfgen.pathobject import PDFPathObject
from shapely.geometry.base import BaseGeometry

from fastmap.services.print_layout import Extent

from .expressions import EvalContext
from .geometry import outline as polygon_outline
from .model import Feature
from .style import Style, StyleLayer

OUTLINE_PX = 0.25
MITER_LIMIT = 2.0  # MapLibre default line-miter-limit
_CAPS = {"butt": 0, "round": 1, "square": 2}
_JOINS = {"miter": 0, "round": 1, "bevel": 2}


class PatternDrawer(Protocol):
    """What draw_fill_line_layers needs from Symbols: patterns and icon layers."""

    def draw_icon_layer(
        self,
        c: Canvas,
        frame: MapFrame,
        layer: StyleLayer,
        features: list[Feature],
        zoom: float,
        px_mm: float,
    ) -> None: ...

    def draw_pattern(
        self,
        c: Canvas,
        name: str,
        clip_path: PDFPathObject,
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

    def geom_to_pt(self, geom: BaseGeometry | np.ndarray) -> BaseGeometry | np.ndarray:
        """Geometry (or an array of them, in one call) from metres to page points."""
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
            r, g, b, a = layer.color("background-color", ctx, "#000000")
            return (r, g, b, a * layer.number("background-opacity", ctx, 1.0))
    return (1.0, 1.0, 1.0, 1.0)


def _run_ops(values: list[float], n: int, close: bool) -> str:
    ops = ("%.2f %.2f m" + " %.2f %.2f l" * (n - 1)) % tuple(values)
    return ops + " h" if close else ops


class PdfPath(PDFPathObject):
    """A ReportLab path that takes whole point runs at once.

    ``moveTo``/``lineTo`` cost a call and a number formatting per point; maps
    have millions of points, so a run is formatted in one C-level ``%`` (0.01 pt,
    i.e. 0.004 mm). Relies on ReportLab keeping path operators in ``_code``.
    """

    def add_run(self, coords: np.ndarray, close: bool) -> None:
        """One subpath through ``coords`` (x, y first); nothing for under two points."""
        n = len(coords)
        if n >= 2:
            self._code.append(_run_ops(coords[:, :2].ravel().tolist(), n, close))

    def add_runs(self, coords: np.ndarray, index: np.ndarray, close: bool) -> None:
        """One subpath per run of equal ``index`` (``shapely.get_coordinates`` output)."""
        if not len(index):
            return
        cuts = (np.flatnonzero(np.diff(index)) + 1).tolist()
        flat = coords[:, :2].ravel().tolist()
        for a, b in zip([0, *cuts], [*cuts, len(index)], strict=True):
            if b - a >= 2:
                self._code.append(_run_ops(flat[2 * a : 2 * b], b - a, close))


def _polygon_path(geoms) -> PdfPath:
    """Polygons (array or list) as one path: each ring a closed subpath."""
    # counter-clockwise exteriors, clockwise holes: the nonzero fill cuts the holes
    polygons = shapely.get_parts(shapely.orient_polygons(np.asarray(geoms, dtype=object)))
    coords, index = shapely.get_coordinates(shapely.get_rings(polygons), return_index=True)
    path = PdfPath()
    path.add_runs(coords, index, close=True)
    return path


def _line_path(geoms) -> PdfPath:
    """Lines (array or list) as one path: each line part an open subpath."""
    lines = shapely.get_parts(np.asarray(geoms, dtype=object))
    coords, index = shapely.get_coordinates(lines, return_index=True)
    path = PdfPath()
    path.add_runs(coords, index, close=False)
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
        if layer.matches(ctx):
            yield f, ctx


class FillStyle(NamedTuple):
    sort_key: float
    fill: tuple
    outline: tuple | None
    opacity: float


class PatternStyle(NamedTuple):
    sort_key: float
    name: str
    opacity: float


class LineStyle(NamedTuple):
    sort_key: float
    rgb: tuple
    alpha: float
    width: float
    dash: tuple
    cap: int
    join: int
    offset: float


def _sorted_groups(groups: dict) -> list:
    """Groups keyed by a style tuple, in ascending ``sort_key`` order (stable)."""
    return sorted(groups.items(), key=lambda kv: kv[0].sort_key)


def _sort_key(layer: StyleLayer, prop: str, ctx: EvalContext) -> float:
    value = layer.get(prop, ctx, 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _draw_fill_layer(c, frame, layer, features, zoom, px_mm, symbols, tile_m) -> None:
    pattern = "fill-pattern" in layer.paint
    if pattern and symbols is None:
        return
    groups: dict[FillStyle | PatternStyle, list] = {}
    for f, ctx in _matching(layer, features, zoom, ("Polygon",)):
        opacity = layer.number("fill-opacity", ctx, 1.0)
        if opacity <= 0:
            continue
        sort_key = _sort_key(layer, "fill-sort-key", ctx)
        if pattern:
            name = layer.get("fill-pattern", ctx)
            if not name:
                continue
            key = PatternStyle(sort_key, name, opacity)
        else:
            fill = layer.color("fill-color", ctx, "#000000")
            outline = None
            if "fill-outline-color" in layer.paint and layer.get("fill-antialias", ctx, True):
                outline = layer.color("fill-outline-color", ctx, "rgba(0,0,0,0)")
                if outline[3] <= 0:
                    outline = None
            if fill[3] <= 0 and outline is None:
                continue
            key = FillStyle(sort_key, fill, outline, opacity)
        groups.setdefault(key, []).append(f.geometry)

    for key, geoms in _sorted_groups(groups):
        geoms_pt = frame.geom_to_pt(np.asarray(geoms, dtype=object))
        path = _polygon_path(geoms_pt)
        c.saveState()
        if isinstance(key, PatternStyle):
            minx, miny, maxx, maxy = shapely.total_bounds(geoms_pt)
            c.setFillAlpha(key.opacity)
            c.setStrokeAlpha(key.opacity)
            symbols.draw_pattern(c, key.name, path, (minx, miny, maxx, maxy), px_mm)
        else:
            fill, outline, opacity = key.fill, key.outline, key.opacity
            if fill[3] > 0:
                c.setFillColorRGB(*fill[:3])
                c.setFillAlpha(fill[3] * opacity)
                c.drawPath(path, stroke=0, fill=1, fillMode=FILL_NON_ZERO)
            if outline is not None:
                c.setStrokeColorRGB(*outline[:3])
                c.setStrokeAlpha(outline[3] * opacity)
                c.setLineWidth(OUTLINE_PX * px_mm * mm)
                outlines = np.array([polygon_outline(g, tile_m) for g in geoms], dtype=object)
                lines = frame.geom_to_pt(outlines)
                c.drawPath(_line_path(lines), stroke=1, fill=0)
        c.restoreState()


def _draw_line_layer(c, frame, layer, features, zoom, px_mm, tile_m) -> None:
    px_pt = px_mm * mm
    groups: dict[LineStyle, list] = {}
    for f, ctx in _matching(layer, features, zoom, ("LineString", "Polygon")):
        color = layer.color("line-color", ctx, "#000000")
        opacity = layer.number("line-opacity", ctx, 1.0)
        width = layer.number("line-width", ctx, 1.0) * px_pt
        alpha = color[3] * opacity
        if alpha <= 0 or width <= 0:
            continue
        dash = layer.get("line-dasharray", ctx)
        dash_pt = tuple(float(d) * width for d in dash) if dash else ()
        if not any(dash_pt):
            dash_pt = ()
        cap = _CAPS.get(layer.get("line-cap", ctx, "butt"), 0)
        join = _JOINS.get(layer.get("line-join", ctx, "miter"), 0)
        offset = layer.number("line-offset", ctx, 0.0) * px_pt
        lines = _as_lines(f.geometry, tile_m)
        if lines.is_empty:
            continue
        sort_key = _sort_key(layer, "line-sort-key", ctx)
        key = LineStyle(sort_key, color[:3], alpha, width, dash_pt, cap, join, offset)
        groups.setdefault(key, []).append(lines)

    for st, lines in _sorted_groups(groups):
        geoms = frame.geom_to_pt(np.asarray(lines, dtype=object))
        if st.offset:
            # MapLibre: positive offset is to the right; shapely: positive is left.
            geoms = shapely.offset_curve(geoms, -st.offset)
        c.saveState()
        c.setStrokeColorRGB(*st.rgb)
        c.setStrokeAlpha(st.alpha)
        c.setLineWidth(st.width)
        c.setLineCap(st.cap)
        c.setLineJoin(st.join)
        c.setMiterLimit(MITER_LIMIT)
        if st.dash:
            c.setDash(list(st.dash), 0)
        c.drawPath(_line_path(geoms), stroke=1, fill=0)
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

    Unconditional icon layers (``symbols.is_drawn_icon_layer``) are drawn in
    their style position too, so e.g. small rock patches can sit under the
    contours; icons that need collision placement are left to the labels.
    Features sharing the same evaluated paint are batched into one path.
    Fill-pattern layers and icons go to ``symbols`` (skipped when it is None);
    background and raster layers are not drawn here. Polygon outlines leave
    out stretches along the edges of ``tile_m`` tile cells (clipping seams).
    """
    from .symbols import is_drawn_icon_layer

    for layer in style.layers:
        if not layer.visible_at(zoom):
            continue
        icons = layer.type == "symbol" and is_drawn_icon_layer(layer)
        if layer.type not in ("fill", "line") and not icons:
            continue
        features = features_by_layer.get(layer.source_layer or "", [])
        if not features:
            continue
        if icons:
            if symbols is not None:
                symbols.draw_icon_layer(c, frame, layer, features, zoom, px_mm)
        elif layer.type == "fill":
            _draw_fill_layer(c, frame, layer, features, zoom, px_mm, symbols, tile_m)
        else:
            _draw_line_layer(c, frame, layer, features, zoom, px_mm, tile_m)
