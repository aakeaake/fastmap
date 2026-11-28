"""Compose a print-ready PDF page from an EPSG:3067 map extent.

The rendered raster is placed at the exact content-area rectangle of the
page, so the printed scale equals the requested nominal scale. No temp
image files are needed - the PIL image is embedded directly.

Process-wide side effect, on purpose: importing this module sets ReportLab's
global ``rl_config.useA85 = 0``, so every PDF this process writes uses binary
Flate streams instead of ASCII85 text on top. ASCII85 only makes a PDF
7-bit-safe, which nothing here needs, and it makes map PDFs ~20 % larger.
FastMap is the only ReportLab user in the process, so import order can't
change another component's output.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from PIL import Image
from reportlab import rl_config
from reportlab.lib.colors import Color, black
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from fastmap.services.mml_source import (
    MML_LAYERS,
    VECTOR_LAYER,
    pick_wmts_level,
    render_extent_image,
)
from fastmap.services.north import format_correction, total_correction
from fastmap.services.pdf_image import draw_palette_image
from fastmap.services.print_layout import (
    FOOTER_MM,
    Extent,
    actual_scale,
    content_area_mm,
    format_scale_label,
    oriented_page_mm,
)
from fastmap.services.route_draw import draw_route
from fastmap.vector import VECTOR_SCALES, render_vector_map

# See the module docstring. With the rl_accel C extension (a dependency)
# ASCII85 is cheap (~0.08 s per A4 map), so this is about file size:
# 4.18 MB -> 3.35 MB for an A4 1:50 000 map.
rl_config.useA85 = 0

_LOCAL_TZ = ZoneInfo("Europe/Helsinki")
_HEX_COLOR = re.compile(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})")


def attribution() -> str:
    """MML attribution, dated in Finnish time when called (once per document)."""
    return f"© Maanmittauslaitos, CC BY 4.0, {datetime.now(_LOCAL_TZ):%m/%Y}"


# Footer line under the map (PDF base font: nothing embedded, 0 bytes added)
_FOOTER_FONT = "Courier"
_FOOTER_SIZE = 7.0
_FOOTER_GAP_MM = 2.0  # minimum space between the title part and the attribution


def _parse_hex_color(value: str) -> tuple[float, float, float]:
    """'#rrggbb' -> (r, g, b) in 0..1. Raises ValueError for anything else."""
    m = _HEX_COLOR.fullmatch(value)
    if not m:
        raise ValueError(f"Invalid colour {value!r}, expected '#rrggbb'")
    r, g, b = (int(part, 16) / 255 for part in m.groups())
    return r, g, b


def _grid_label(value_m: int) -> str:
    """Coordinate in metres ÷ 100: '3855' for E 385 500, '66725' for N 6 672 500.

    No decimals at any grid spacing (all spacings are multiples of 100 m).
    """
    return str(value_m // 100)


# Grid coordinate labels (PDF base font, like the footer)
_LABEL_FONT = "Courier"
_LABEL_SIZE = 5.5
_LABEL_COLOR = black  # coordinates print black, like the footer
_GRID_COLOR = Color(0.35, 0.35, 0.35)
# With magnetic north lines on, the coordinate grid and its labels turn light
# blue so the black magnetic lines stand out against the map
_GRID_BLUE = Color(0x6F / 255, 0xA8 / 255, 0xE6 / 255)
_MAGNETIC_COLOR = black
# Labels go in the margin, outside the map, when it is at least this wide;
# in a narrower margin they fall back to inside the map edges.
LABEL_MIN_MARGIN_MM = 3.0
_LABEL_OFFSET_MM = 1.0  # outside: baseline distance from the map edge
_LABEL_INSET_MM = 1.5  # inside fallback: distance from the map edge


def _grid_values(lo: float, hi: float, spacing_m: int) -> list[int]:
    """Grid coordinates (multiples of ``spacing_m``) inside ``[lo, hi]``."""
    start = math.ceil(lo / spacing_m) * spacing_m
    return list(range(start, math.floor(hi) + 1, spacing_m))


def _label_every(step_pt: float, needed_pt: float) -> int:
    """Smallest 1-2-5 multiple of the grid step that leaves ``needed_pt`` of room."""
    if step_pt <= 0:
        return 1
    decade = 1
    while True:
        for k in (decade, 2 * decade, 5 * decade):
            if k * step_pt >= needed_pt:
                return k
        decade *= 10


@dataclass(frozen=True)
class PrintResult:
    path: str
    actual_scale: int
    extent: Extent
    width_px: int
    height_px: int


def _draw_footer(
    c: canvas.Canvas,
    x0: float,
    y0: float,
    w: float,
    title: str | None,
    scale_label: str,
    attribution_text: str,
) -> None:
    """One line under the map: ``title · scale`` left, attribution right.

    ``y0`` is the margin line: the bottom of the text (descenders) sits on
    it. A title that would run into the attribution is shortened with "…".
    """
    font, size = _FOOTER_FONT, _FOOTER_SIZE
    baseline = y0 - pdfmetrics.getDescent(font, size)
    right_x = x0 + w - c.stringWidth(attribution_text, font, size)
    room = right_x - _FOOTER_GAP_MM * mm - x0

    left = f"{title} · {scale_label}" if title else scale_label
    if c.stringWidth(left, font, size) > room and title:
        tail = f"… · {scale_label}"
        cut = title
        while cut and c.stringWidth(cut + tail, font, size) > room:
            cut = cut[:-1]
        left = cut.rstrip() + tail

    c.setFillColor(black)
    c.setFont(font, size)
    c.drawString(x0, baseline, left)
    c.drawString(right_x, baseline, attribution_text)


def _draw_grid_lines(
    c: canvas.Canvas,
    extent: Extent,
    x0: float,
    y0: float,
    w: float,
    h: float,
    *,
    mode: str,
    spacing_m: int,
    margin_mm: float,
    color: Color = _GRID_COLOR,
    label_color: Color = _LABEL_COLOR,
) -> None:
    """Draw thin grid lines (grey unless ``color``) over the map content area."""
    if mode == "off":
        return
    show_coords = mode in ("vertical_coords", "full_coords")
    show_horizontal = mode in ("full", "full_coords")

    xs = [
        (gx, (gx - extent.minx) / (extent.maxx - extent.minx) * w + x0)
        for gx in _grid_values(extent.minx, extent.maxx, spacing_m)
    ]
    ys = (
        [
            (gy, (gy - extent.miny) / (extent.maxy - extent.miny) * h + y0)
            for gy in _grid_values(extent.miny, extent.maxy, spacing_m)
        ]
        if show_horizontal
        else []
    )

    c.saveState()
    c.setStrokeColor(color)
    c.setLineWidth(0.3)
    for _, px in xs:  # vertical lines (south-north)
        c.line(px, y0, px, y0 + h)
    for _, py in ys:  # horizontal lines (west-east) - full grid only
        c.line(x0, py, x0 + w, py)
    c.restoreState()

    # coordinate labels: east labels on the top edge, north labels on the left
    if not show_coords:
        return
    font, size = _LABEL_FONT, _LABEL_SIZE
    c.setFillColor(label_color)
    c.setFont(font, size)
    gap = 1 * mm  # minimum clear space between neighbouring labels
    outside = margin_mm >= LABEL_MIN_MARGIN_MM
    offset = _LABEL_OFFSET_MM * mm
    inset = _LABEL_INSET_MM * mm

    def width(label: str) -> float:
        return c.stringWidth(label, font, size)

    # Thin labels when lines are too dense, keeping labelled lines aligned to
    # multiples of the label interval so they stay the same across pages.
    if xs:
        step_pt = spacing_m / (extent.maxx - extent.minx) * w
        widest = max(width(_grid_label(gx)) for gx, _ in xs)
        every = _label_every(step_pt, widest + gap) * spacing_m
        y = y0 + h + offset if outside else y0 + inset
        for gx, px in xs:
            label = _grid_label(gx)
            left = px - width(label) / 2
            if gx % every or left < x0 or left + width(label) > x0 + w:
                continue  # thinned out, or would run past a map corner
            c.drawString(left, y, label)

    if ys:
        step_pt = spacing_m / (extent.maxy - extent.miny) * h
        # Rotated labels take their length along the edge, upright ones their height
        needed = max(width(_grid_label(gy)) for gy, _ in ys) if outside else size
        every = _label_every(step_pt, needed + gap) * spacing_m
        for gy, py in ys:
            label = _grid_label(gy)
            if gy % every:
                continue
            if outside:
                start = py - width(label) / 2
                if start < y0 or start + width(label) > y0 + h:
                    continue  # would run past a map corner
                # Rotated 90° anticlockwise, reading upward, left of the map
                c.saveState()
                c.translate(x0 - offset, py)
                c.rotate(90)
                c.drawCentredString(0, 0, label)
                c.restoreState()
            else:
                if py - 2 < y0 or py - 2 + size > y0 + h:
                    continue
                c.drawString(x0 + inset, py - 2, label)


def _draw_magnetic_lines(
    c: canvas.Canvas,
    extent: Extent,
    x0: float,
    y0: float,
    w: float,
    h: float,
    *,
    angle_deg: float,
    spacing_m: int,
) -> None:
    """Magnetic north lines: turned clockwise from grid north by ``angle_deg``,
    ``spacing_m`` apart across the lines, clipped to the map box."""
    t = math.radians(angle_deg)
    ct, st = math.cos(t), math.sin(t)
    # u is the ground coordinate across the lines; each line is u = k * spacing
    corners = [(x, y) for x in (extent.minx, extent.maxx) for y in (extent.miny, extent.maxy)]
    us = [x * ct - y * st for x, y in corners]
    k0, k1 = math.ceil(min(us) / spacing_m), math.floor(max(us) / spacing_m)
    # the line u = k*s runs along (sin t, cos t) through (k*s*cos t, -k*s*sin t);
    # draw it far enough both ways to cross the whole extent
    reach = math.hypot(extent.maxx - extent.minx, extent.maxy - extent.miny)
    cx, cy = (extent.minx + extent.maxx) / 2, (extent.miny + extent.maxy) / 2
    sx = w / (extent.maxx - extent.minx)
    sy = h / (extent.maxy - extent.miny)

    def paper(gx: float, gy: float) -> tuple[float, float]:
        return x0 + (gx - extent.minx) * sx, y0 + (gy - extent.miny) * sy

    c.saveState()
    clip = c.beginPath()
    clip.rect(x0, y0, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    c.setStrokeColor(_MAGNETIC_COLOR)
    c.setLineWidth(0.3)
    for k in range(k0, k1 + 1):
        u = k * spacing_m
        # the point of the line nearest the extent centre, then out both ways
        v = cx * st + cy * ct  # coordinate along the lines
        px, py = u * ct + v * st, -u * st + v * ct
        a = paper(px - reach * st, py - reach * ct)
        b = paper(px + reach * st, py + reach * ct)
        c.line(a[0], a[1], b[0], b[1])
    c.restoreState()


def _render_raster(extent, page_w_mm, margin_mm, dpi, zoom_level, layer):
    """Fetch the raster image for ``extent`` at the zoom level it needs."""
    px_w_est = round((page_w_mm - 2 * margin_mm) / 25.4 * (dpi or 300))
    if zoom_level is None:
        zoom_level = pick_wmts_level(extent.width_m / px_w_est)
    res = 8192.0 / 2**zoom_level
    return render_extent_image(
        extent, round(extent.width_m / res), round(extent.height_m / res), layer=layer
    )


def _vector_scale(extent: Extent, paper_size: str, orientation: str, margin_mm: float) -> int:
    """Nominal vector scale (25 000 / 50 000) for a snapped extent."""
    actual = actual_scale(extent, content_area_mm(paper_size, orientation, margin_mm)[0])
    nominal = min(VECTOR_SCALES, key=lambda s: abs(s - actual))
    if abs(nominal - actual) > nominal * 0.01:
        raise ValueError("The vector map supports scales 1:25 000 and 1:50 000 only")
    return nominal


class MapDrawer(Protocol):
    """Draws a map image or vector map into a page rectangle.

    ``x, y`` is the rectangle's lower-left corner and ``w, h`` its size, in PDF
    points; the map must fill it exactly, which is what keeps the scale true.
    """

    def __call__(self, c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None: ...


def _raster_drawer(img: Image.Image) -> MapDrawer:
    def draw(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
        if img.mode == "P":
            draw_palette_image(c, img, x, y, w, h)  # 1 byte/pixel instead of RGB's 3
        else:
            c.drawImage(ImageReader(img), x, y, w, h)

    return draw


def _vector_drawer(extent: Extent, scale: int) -> MapDrawer:
    def draw(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
        c.saveState()
        try:
            render_vector_map(c, extent, (x, y, w, h), scale)
        finally:
            c.restoreState()

    return draw


def _draw_page(
    c: canvas.Canvas,
    draw_map: MapDrawer,
    extent: Extent,
    *,
    paper_size: str,
    orientation: str,
    margin_mm: float,
    title: str | None,
    attribution_text: str,
    grid_mode: str = "off",
    grid_spacing_m: int = 1000,
    gpx_routes: list[list[list[float]]] | None = None,
    gpx_color: str = "#ff00ff",
    gpx_width: float = 5,
    gpx_opacity: float = 0.6,
    gpx_look: str = "line",
    gpx_waypoints: list[dict] | None = None,
    magnetic_north: bool = False,
    magnetic_spacing_m: int = 1000,
    when: date | None = None,
) -> int:
    """Draw one full page: map, footer line below it. Returns true scale.

    The footer gives the total correction (grid -> magnetic north) for the
    sheet's centre on ``when`` (today in Finland when None).
    """
    cont_w_mm, cont_h_mm = content_area_mm(paper_size, orientation, margin_mm)
    scale_value = actual_scale(extent, cont_w_mm)

    margin = margin_mm * mm  # the margin line, measured from the page edge
    x0 = margin
    y0 = margin + FOOTER_MM * mm  # map bottom: the footer band sits below it
    w = cont_w_mm * mm
    h = cont_h_mm * mm

    # The map fills the content area exactly -> printed scale is exact
    draw_map(c, x0, y0, w, h)

    when = when or datetime.now(_LOCAL_TZ).date()
    angle = total_correction((extent.minx + extent.maxx) / 2, (extent.miny + extent.maxy) / 2, when)

    # optional grid lines, blue when magnetic north lines are on too
    blue = {"color": _GRID_BLUE, "label_color": _GRID_BLUE} if magnetic_north else {}
    _draw_grid_lines(
        c,
        extent,
        x0,
        y0,
        w,
        h,
        mode=grid_mode,
        spacing_m=grid_spacing_m,
        margin_mm=margin_mm,
        **blue,
    )
    if magnetic_north:
        _draw_magnetic_lines(c, extent, x0, y0, w, h, angle_deg=angle, spacing_m=magnetic_spacing_m)

    # optional GPX route (line or course) and waypoints
    draw_route(
        c,
        extent,
        x0,
        y0,
        w,
        h,
        routes=gpx_routes or [],
        look=gpx_look,
        waypoints=gpx_waypoints or [],
        rgb=_parse_hex_color(gpx_color),
        width=gpx_width,
        opacity=gpx_opacity,
    )

    # The scale and the correction are never shortened; only the title is
    footer_label = f"{format_scale_label(scale_value)} · {format_correction(angle)}"
    _draw_footer(c, x0, margin, w, title, footer_label, attribution_text)

    return scale_value


def generate_pdf(
    extent: Extent,
    *,
    paper_size: str,
    orientation: str,
    layer: str = "maastokartta",
    dpi: int | None = None,
    zoom_level: int | None = None,
    margin_mm: float = 7.0,
    title: str | None = None,
    out_pdf_path: str = "map.pdf",
    grid_mode: str = "off",
    grid_spacing_m: int = 1000,
    gpx_routes: list[list[list[float]]] | None = None,
    gpx_color: str = "#ff00ff",
    gpx_width: float = 5,
    gpx_opacity: float = 0.6,
    gpx_look: str = "line",
    gpx_waypoints: list[dict] | None = None,
    magnetic_north: bool = False,
    magnetic_spacing_m: int = 1000,
) -> PrintResult:
    """Render ``extent`` and write a scaled PDF page.

    Returns a PrintResult with the true printed scale.
    """
    if layer not in MML_LAYERS:
        raise ValueError(f"Unknown layer '{layer}'")
    _parse_hex_color(gpx_color)  # fail before the slow tile download

    page_w_mm, page_h_mm = oriented_page_mm(paper_size, orientation)
    if layer == VECTOR_LAYER:
        draw_map = _vector_drawer(extent, _vector_scale(extent, paper_size, orientation, margin_mm))
        img = None
    else:
        img = _render_raster(extent, page_w_mm, margin_mm, dpi, zoom_level, layer)
        draw_map = _raster_drawer(img)

    nominal_title = format_scale_label(
        actual_scale(extent, content_area_mm(paper_size, orientation, margin_mm)[0])
    )
    c = canvas.Canvas(out_pdf_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    c.setTitle(title or f"FastMap {nominal_title}")
    scale_value = _draw_page(
        c,
        draw_map,
        extent,
        paper_size=paper_size,
        orientation=orientation,
        margin_mm=margin_mm,
        title=title,
        attribution_text=attribution(),
        grid_mode=grid_mode,
        grid_spacing_m=grid_spacing_m,
        gpx_routes=gpx_routes,
        gpx_color=gpx_color,
        gpx_width=gpx_width,
        gpx_opacity=gpx_opacity,
        gpx_look=gpx_look,
        gpx_waypoints=gpx_waypoints,
        magnetic_north=magnetic_north,
        magnetic_spacing_m=magnetic_spacing_m,
    )
    c.showPage()
    c.save()
    if img is not None:
        img.close()

    return PrintResult(
        path=out_pdf_path,
        actual_scale=scale_value,
        extent=extent,
        width_px=img.size[0] if img is not None else 0,
        height_px=img.size[1] if img is not None else 0,
    )


def generate_multi_pdf(
    items,
    out_pdf_path: str,
    doc_title: str | None = None,
) -> list[PrintResult]:
    """Render several ``(extent, kwargs)`` pairs as one multi-page PDF.

    ``kwargs`` mirrors :func:`generate_pdf`'s keyword arguments, so pages
    may freely mix paper sizes and orientations.
    """
    results: list[PrintResult] = []
    c: canvas.Canvas | None = None
    items = list(items)
    # Check every page before any slow tile download starts
    for _, kwargs in items:
        layer = kwargs.get("layer", "maastokartta")
        if layer not in MML_LAYERS:
            raise ValueError(f"Unknown layer '{layer}'")
        _parse_hex_color(kwargs.get("gpx_color", "#ff00ff"))

    attribution_text = attribution()  # one date for every page of the document
    today = datetime.now(_LOCAL_TZ).date()
    for extent, kwargs in items:
        layer = kwargs.get("layer", "maastokartta")
        paper_size = kwargs["paper_size"]
        orientation = kwargs["orientation"]
        dpi = kwargs.get("dpi")
        zoom_level = kwargs.get("zoom_level")
        margin_mm = kwargs.get("margin_mm", 7.0)
        grid_mode = kwargs.get("grid_mode", "off")
        grid_spacing_m = kwargs.get("grid_spacing_m", 1000)
        gpx_routes = kwargs.get("gpx_routes", [])
        gpx_color = kwargs.get("gpx_color", "#ff00ff")
        gpx_width = kwargs.get("gpx_width", 5)
        gpx_opacity = kwargs.get("gpx_opacity", 0.6)

        page_w_mm, _ = oriented_page_mm(paper_size, orientation)
        if layer == VECTOR_LAYER:
            draw_map = _vector_drawer(
                extent, _vector_scale(extent, paper_size, orientation, margin_mm)
            )
            img = None
        else:
            img = _render_raster(extent, page_w_mm, margin_mm, dpi, zoom_level, layer)
            draw_map = _raster_drawer(img)

        page_w_pt, page_h_pt = (v * mm for v in oriented_page_mm(paper_size, orientation))
        if c is None:
            c = canvas.Canvas(out_pdf_path, pagesize=(page_w_pt, page_h_pt))
            c.setTitle(doc_title or kwargs.get("title") or "FastMap")
        else:
            c.setPageSize((page_w_pt, page_h_pt))

        scale_value = _draw_page(
            c,
            draw_map,
            extent,
            paper_size=paper_size,
            orientation=orientation,
            margin_mm=margin_mm,
            title=kwargs.get("title"),
            attribution_text=attribution_text,
            grid_mode=grid_mode,
            grid_spacing_m=grid_spacing_m,
            gpx_routes=gpx_routes,
            gpx_color=gpx_color,
            gpx_width=gpx_width,
            gpx_opacity=gpx_opacity,
            gpx_look=kwargs.get("gpx_look", "line"),
            gpx_waypoints=kwargs.get("gpx_waypoints", []),
            magnetic_north=kwargs.get("magnetic_north", False),
            magnetic_spacing_m=kwargs.get("magnetic_spacing_m", 1000),
            when=today,
        )
        results.append(
            PrintResult(
                path=out_pdf_path,
                actual_scale=scale_value,
                extent=extent,
                width_px=img.size[0] if img is not None else 0,
                height_px=img.size[1] if img is not None else 0,
            )
        )
        if img is not None:
            img.close()
        c.showPage()

    if c is not None:
        c.save()
    return results


def generate_pdf_to_temp(extent, **kwargs) -> PrintResult:
    """Convenience wrapper writing into a unique temporary file."""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(prefix="fastmap_", suffix=".pdf", delete=False)
    tmp.close()
    kwargs["out_pdf_path"] = tmp.name
    return generate_pdf(extent, **kwargs)


__all__ = [
    "attribution",
    "generate_pdf",
    "generate_multi_pdf",
    "generate_pdf_to_temp",
    "PrintResult",
]
