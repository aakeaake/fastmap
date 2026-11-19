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
from datetime import datetime
from zoneinfo import ZoneInfo

from PIL import Image
from reportlab import rl_config
from reportlab.lib.colors import Color, black
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from fastmap.services.mml_source import MML_LAYERS, pick_wmts_level, render_extent_image
from fastmap.services.print_layout import (
    FOOTER_MM,
    Extent,
    actual_scale,
    content_area_mm,
    format_scale_label,
    oriented_page_mm,
)

# See the module docstring. With the rl_accel C extension (a dependency)
# ASCII85 is cheap (~0.08 s per A4 map), so this is about file size:
# 4.18 MB -> 3.35 MB for an A4 1:50 000 map.
rl_config.useA85 = 0

_LOCAL_TZ = ZoneInfo("Europe/Helsinki")
_HEX_COLOR = re.compile(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})")


def attribution() -> str:
    """MML attribution, dated in Finnish time when called (once per document)."""
    return f"© Maanmittauslaitos {datetime.now(_LOCAL_TZ):%m/%Y}"


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
    """Coordinate in km: '429' for whole km, '428.5' for half-km lines."""
    return f"{value_m / 1000:g}"


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
) -> None:
    """Draw thin grey grid lines over the map content area."""
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
    c.setStrokeColor(Color(0.35, 0.35, 0.35))
    c.setLineWidth(0.3)
    for _, px in xs:  # vertical lines (south-north)
        c.line(px, y0, px, y0 + h)
    for _, py in ys:  # horizontal lines (west-east) - full grid only
        c.line(x0, py, x0 + w, py)
    c.restoreState()

    # coordinate labels at edges
    if not show_coords:
        return
    font, size = "Helvetica", 5.5
    c.setFillColor(Color(0.35, 0.35, 0.35))
    c.setFont(font, size)
    label_pad = 1.5  # mm from edge
    gap = 1 * mm  # minimum clear space between neighbouring labels
    step_pt = spacing_m / (extent.maxx - extent.minx) * w

    # Thin labels when lines are too dense, keeping labelled lines aligned to
    # multiples of the label interval so they stay the same across pages.
    if xs:
        widest = max(c.stringWidth(_grid_label(gx), font, size) for gx, _ in xs)
        every = _label_every(step_pt, widest + gap) * spacing_m
        for gx, px in xs:
            if gx % every:
                continue
            label = _grid_label(gx)
            c.drawString(px - c.stringWidth(label, font, size) / 2, y0 + label_pad * mm, label)

    every = _label_every(spacing_m / (extent.maxy - extent.miny) * h, size + gap) * spacing_m
    for gy, py in ys:
        if gy % every:
            continue
        c.drawString(x0 + label_pad * mm, py - 2, _grid_label(gy))


def _draw_page(
    c: canvas.Canvas,
    img: Image.Image,
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
    gpx_width: int = 5,
    gpx_opacity: float = 0.6,
) -> int:
    """Draw one full page: map, footer line below it. Returns true scale."""
    cont_w_mm, cont_h_mm = content_area_mm(paper_size, orientation, margin_mm)
    scale_value = actual_scale(extent, cont_w_mm)

    margin = margin_mm * mm  # the margin line, measured from the page edge
    x0 = margin
    y0 = margin + FOOTER_MM * mm  # map bottom: the footer band sits below it
    w = cont_w_mm * mm
    h = cont_h_mm * mm

    # Map image fills the content area exactly -> printed scale is exact
    c.drawImage(ImageReader(img), x0, y0, w, h)

    # optional grid lines
    _draw_grid_lines(c, extent, x0, y0, w, h, mode=grid_mode, spacing_m=grid_spacing_m)

    # optional GPX routes
    if gpx_routes:
        ext_w = extent.maxx - extent.minx
        ext_h = extent.maxy - extent.miny
        if ext_w > 0 and ext_h > 0:
            c.saveState()
            clip = c.beginPath()
            clip.rect(x0, y0, w, h)
            c.clipPath(clip, stroke=0, fill=0)
            r, g, b = _parse_hex_color(gpx_color)
            c.setStrokeColor(Color(r, g, b, alpha=gpx_opacity))
            c.setLineWidth(gpx_width)
            for route in gpx_routes:
                p = c.beginPath()
                for i, (gx, gy) in enumerate(route):
                    px = (gx - extent.minx) / ext_w * w + x0
                    py = (gy - extent.miny) / ext_h * h + y0
                    if i == 0:
                        p.moveTo(px, py)
                    else:
                        p.lineTo(px, py)
                c.drawPath(p, stroke=1, fill=0)
            c.restoreState()

    _draw_footer(c, x0, margin, w, title, format_scale_label(scale_value), attribution_text)

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
    gpx_width: int = 5,
    gpx_opacity: float = 0.6,
) -> PrintResult:
    """Render ``extent`` and write a scaled PDF page.

    Returns a PrintResult with the true printed scale.
    """
    if layer not in MML_LAYERS:
        raise ValueError(f"Unknown layer '{layer}'")
    _parse_hex_color(gpx_color)  # fail before the slow tile download

    dpi_val = dpi or 300
    page_w_mm, page_h_mm = oriented_page_mm(paper_size, orientation)
    content_w_mm = page_w_mm - 2 * margin_mm
    px_w_est = round(content_w_mm / 25.4 * dpi_val)

    if zoom_level is None:
        target_res = extent.width_m / px_w_est
        zoom_level = pick_wmts_level(target_res)

    res = 8192.0 / 2**zoom_level
    px_w = round(extent.width_m / res)
    px_h = round(extent.height_m / res)

    img = render_extent_image(extent, px_w, px_h, layer=layer)

    nominal_title = format_scale_label(
        actual_scale(extent, content_area_mm(paper_size, orientation, margin_mm)[0])
    )
    c = canvas.Canvas(out_pdf_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    c.setTitle(title or f"FastMap {nominal_title}")
    scale_value = _draw_page(
        c,
        img,
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
    )
    c.showPage()
    c.save()
    img.close()

    return PrintResult(
        path=out_pdf_path,
        actual_scale=scale_value,
        extent=extent,
        width_px=img.size[0],
        height_px=img.size[1],
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

        dpi_val = dpi or 300
        page_w_mm, _ = oriented_page_mm(paper_size, orientation)
        content_w_mm = page_w_mm - 2 * margin_mm
        px_w_est = round(content_w_mm / 25.4 * dpi_val)

        if zoom_level is None:
            target_res = extent.width_m / px_w_est
            zoom_level = pick_wmts_level(target_res)

        res = 8192.0 / 2**zoom_level
        px_w = round(extent.width_m / res)
        px_h = round(extent.height_m / res)
        img = render_extent_image(extent, px_w, px_h, layer=layer)

        page_w_pt, page_h_pt = (v * mm for v in oriented_page_mm(paper_size, orientation))
        if c is None:
            c = canvas.Canvas(out_pdf_path, pagesize=(page_w_pt, page_h_pt))
            c.setTitle(doc_title or kwargs.get("title") or "FastMap")
        else:
            c.setPageSize((page_w_pt, page_h_pt))

        scale_value = _draw_page(
            c,
            img,
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
        )
        results.append(
            PrintResult(
                path=out_pdf_path,
                actual_scale=scale_value,
                extent=extent,
                width_px=img.size[0],
                height_px=img.size[1],
            )
        )
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
