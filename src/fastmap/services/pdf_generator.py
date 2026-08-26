"""Compose a print-ready PDF page from an EPSG:3067 map extent.

The rendered raster is placed at the exact content-area rectangle of the
page, so the printed scale equals the requested nominal scale. No temp
image files are needed - the PIL image is embedded directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PIL import Image
from reportlab.lib.colors import black, Color
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from fastmap.core.config import DEFAULT_ZOOM
from fastmap.services.mml_source import MML_LAYERS, pick_wmts_level, render_extent_image
from fastmap.services.print_layout import (
    Extent,
    actual_scale,
    content_area_mm,
    format_scale_label,
    oriented_page_mm,
)

ATTRIBUTION = f"© Maanmittauslaitos, CC BY 4.0 — Maastotietokanta {datetime.now().strftime('%m/%Y')}"
_TEXT_INSET_MM = 2.0  # overlay text distance from the content-area corner


@dataclass(frozen=True)
class PrintResult:
    path: str
    actual_scale: int
    extent: Extent
    width_px: int
    height_px: int


def _draw_overlay_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    *,
    font: str = "Helvetica",
    size: float = 7,
    align_right: bool = False,
) -> None:
    """Black text on a semi-transparent white background for legibility."""
    if align_right:
        x -= c.stringWidth(text, font, size)
    pad = 1
    tw = c.stringWidth(text, font, size)
    c.saveState()
    c.setFillColor(Color(1, 1, 1, alpha=0.50))
    c.rect(x - pad, y - pad, tw + 2 * pad, size + 2 * pad, stroke=0, fill=1)
    c.restoreState()
    c.setFillColor(black)
    c.setFont(font, size)
    c.drawString(x, y, text)


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

    c.saveState()
    c.setStrokeColor(Color(0.35, 0.35, 0.35))
    c.setLineWidth(0.3)

    # vertical lines (south-north)
    start_x = int(extent.minx // spacing_m) * spacing_m
    for gx in range(start_x, int(extent.maxx) + spacing_m, spacing_m):
        if gx < extent.minx or gx > extent.maxx:
            continue
        px = (gx - extent.minx) / (extent.maxx - extent.minx) * w + x0
        c.line(px, y0, px, y0 + h)

    # horizontal lines (west-east) — full grid only
    start_y = int(extent.miny // spacing_m) * spacing_m
    if show_horizontal:
        for gy in range(start_y, int(extent.maxy) + spacing_m, spacing_m):
            if gy < extent.miny or gy > extent.maxy:
                continue
            py = (gy - extent.miny) / (extent.maxy - extent.miny) * h + y0
            c.line(x0, py, x0 + w, py)

    c.restoreState()

    # coordinate labels at edges
    if not show_coords:
        return
    c.setFillColor(Color(0.35, 0.35, 0.35))
    c.setFont("Helvetica", 5.5)
    label_pad = 1.5  # mm from edge

    for gx in range(start_x, int(extent.maxx) + spacing_m, spacing_m):
        if gx < extent.minx or gx > extent.maxx:
            continue
        px = (gx - extent.minx) / (extent.maxx - extent.minx) * w + x0
        label = f"{gx // 1000}"
        c.drawString(px - c.stringWidth(label, "Helvetica", 5.5) / 2, y0 + label_pad * mm, label)

    if show_horizontal:
        for gy in range(start_y, int(extent.maxy) + spacing_m, spacing_m):
            if gy < extent.miny or gy > extent.maxy:
                continue
            py = (gy - extent.miny) / (extent.maxy - extent.miny) * h + y0
            label = f"{gy // 1000}"
            c.drawString(x0 + label_pad * mm, py - 2, label)


def _draw_page(
    c: canvas.Canvas,
    img: Image.Image,
    extent: Extent,
    *,
    paper_size: str,
    orientation: str,
    margin_mm: float,
    title: str | None,
    grid_mode: str = "off",
    grid_spacing_m: int = 1000,
    gpx_routes: list[list[list[float]]] | None = None,
    gpx_color: str = "#ff00ff",
    gpx_width: int = 5,
    gpx_opacity: float = 0.6,
) -> int:
    """Draw one full page (map plus inside-corner overlays). Returns true scale."""
    cont_w_mm, cont_h_mm = content_area_mm(paper_size, orientation, margin_mm)
    scale_value = actual_scale(extent, cont_w_mm)

    x0 = margin_mm * mm
    y0 = margin_mm * mm
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
            # parse hex color and apply opacity
            r = int(gpx_color[1:3], 16) / 255
            g = int(gpx_color[3:5], 16) / 255
            b = int(gpx_color[5:7], 16) / 255
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

    pad = _TEXT_INSET_MM * mm

    # inside bottom-left: license attribution
    _draw_overlay_text(c, x0 + pad, y0 + pad, ATTRIBUTION)

    # inside bottom-right: printed scale
    _draw_overlay_text(
        c,
        x0 + w - pad,
        y0 + pad,
        format_scale_label(scale_value),
        align_right=True,
    )

    # inside top-right: optional title
    if title:
        _draw_overlay_text(
            c,
            x0 + w - pad,
            y0 + h - pad - 9,
            title,
            font="Helvetica-Bold",
            size=9,
            align_right=True,
        )

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

    dpi_val = dpi or 300
    page_w_mm, page_h_mm = oriented_page_mm(paper_size, orientation)
    content_w_mm = page_w_mm - 2 * margin_mm
    content_w_m = content_w_mm / 1000.0 * (extent.width_m / (content_w_mm / 1000.0))
    px_w_est = round(content_w_mm / 25.4 * dpi_val)

    if zoom_level is None:
        target_res = extent.width_m / px_w_est
        zoom_level = pick_wmts_level(target_res)

    res = 8192.0 / 2 ** zoom_level
    px_w = round(extent.width_m / res)
    px_h = round(extent.height_m / res)

    img = render_extent_image(extent, px_w, px_h, layer=layer)

    nominal_title = format_scale_label(
        actual_scale(extent, content_area_mm(paper_size, orientation, margin_mm)[0])
    )
    c = canvas.Canvas(out_pdf_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    c.setTitle(title or f"FastMap {nominal_title}")
    scale_value = _draw_page(
        c, img, extent,
        paper_size=paper_size,
        orientation=orientation,
        margin_mm=margin_mm,
        title=title,
        grid_mode=grid_mode,
        grid_spacing_m=grid_spacing_m,
        gpx_routes=gpx_routes,
        gpx_color=gpx_color,
        gpx_width=gpx_width,
        gpx_opacity=gpx_opacity,
    )
    c.showPage()
    c.save()

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
    for extent, kwargs in items:
        layer = kwargs.get("layer", "maastokartta")
        if layer not in MML_LAYERS:
            raise ValueError(f"Unknown layer '{layer}'")
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

        res = 8192.0 / 2 ** zoom_level
        px_w = round(extent.width_m / res)
        px_h = round(extent.height_m / res)
        img = render_extent_image(extent, px_w, px_h, layer=layer)

        page_w_pt, page_h_pt = (
            v * mm for v in oriented_page_mm(paper_size, orientation)
        )
        if c is None:
            c = canvas.Canvas(out_pdf_path, pagesize=(page_w_pt, page_h_pt))
            c.setTitle(doc_title or kwargs.get("title") or "FastMap")
        else:
            c.setPageSize((page_w_pt, page_h_pt))

        scale_value = _draw_page(
            c, img, extent,
            paper_size=paper_size,
            orientation=orientation,
            margin_mm=margin_mm,
            title=kwargs.get("title"),
            grid_mode=grid_mode,
            grid_spacing_m=grid_spacing_m,
            gpx_routes=gpx_routes,
            gpx_color=gpx_color,
            gpx_width=gpx_width,
            gpx_opacity=gpx_opacity,
        )
        results.append(PrintResult(
            path=out_pdf_path,
            actual_scale=scale_value,
            extent=extent,
            width_px=img.size[0],
            height_px=img.size[1],
        ))
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
    "generate_pdf",
    "generate_multi_pdf",
    "generate_pdf_to_temp",
    "PrintResult",
]
