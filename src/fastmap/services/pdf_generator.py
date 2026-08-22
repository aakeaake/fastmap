"""Compose a print-ready PDF page from an EPSG:3067 map extent.

The rendered raster is placed at the exact content-area rectangle of the
page, so the printed scale equals the requested nominal scale. No temp
image files are needed - the PIL image is embedded directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from PIL import Image
from reportlab.lib.colors import white, black
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from fastmap.core.config import DEFAULT_DPI
from fastmap.services.mml_source import MML_LAYERS, render_extent_image
from fastmap.services.print_layout import (
    Extent,
    actual_scale,
    content_area_mm,
    content_pixels,
    format_scale_label,
    oriented_page_mm,
    scale_bar_distance,
)

ATTRIBUTION = "© Maanmittauslaitos, CC BY 4.0"
_INSET_MM = 5.0


@dataclass(frozen=True)
class PrintResult:
    path: str
    actual_scale: int
    extent: Extent
    width_px: int
    height_px: int


def _format_distance(dist_m: int) -> str:
    if dist_m >= 1000:
        km = dist_m / 1000.0
        text = f"{km:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{text} km"
    return f"{dist_m} m"


def _draw_frame(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setStrokeColor(black)
    c.setLineWidth(0.5)
    c.rect(x, y, w, h, stroke=1, fill=0)


def _draw_scale_bar(
    c: canvas.Canvas,
    x_right: float,
    y_bottom: float,
    bar_mm: float,
    dist_m: int,
) -> None:
    """Alternating-segment scale bar anchored at its right edge."""
    bar_w = bar_mm * mm
    bar_h = 2.2 * mm
    n_seg = 4
    seg_w = bar_w / n_seg

    pad = 1.5 * mm
    box_x = x_right - bar_w - pad
    box_y = y_bottom - 3.2 * mm - bar_h

    # Background plate so the bar stays readable on any map colour
    c.setFillColor(white)
    c.setStrokeColor(black)
    c.setLineWidth(0.5)
    c.rect(box_x, box_y, bar_w + 2 * pad, bar_h + 3.6 * mm, stroke=1, fill=1)

    seg_y = box_y + 1.8 * mm
    for i in range(n_seg):
        c.setFillColor(black if i % 2 == 0 else white)
        c.setStrokeColor(black)
        c.rect(box_x + pad + i * seg_w, seg_y, seg_w, bar_h, stroke=1, fill=1)

    c.setFillColor(black)
    c.setFont("Helvetica", 7)
    c.drawCentredString(
        box_x + pad + bar_w / 2,
        seg_y + bar_h + 1.2 * mm,
        _format_distance(dist_m),
    )


def generate_pdf(
    extent: Extent,
    *,
    paper_size: str,
    orientation: str,
    layer: str = "maastokartta",
    dpi: int = DEFAULT_DPI,
    margin_mm: float = 10.0,
    title: str | None = None,
    out_pdf_path: str = "map.pdf",
) -> PrintResult:
    """Render ``extent`` and write a scaled PDF page.

    Returns a PrintResult with the true printed scale.
    """
    if layer not in MML_LAYERS:
        raise ValueError(f"Unknown layer '{layer}'")

    page_w_mm, page_h_mm = oriented_page_mm(paper_size, orientation)
    cont_w_mm, cont_h_mm = content_area_mm(paper_size, orientation, margin_mm)
    px_w, px_h = content_pixels(paper_size, orientation, dpi, margin_mm)

    img = render_extent_image(extent, px_w, px_h, layer=layer)

    scale_value = actual_scale(extent, cont_w_mm)

    c = canvas.Canvas(out_pdf_path, pagesize=(page_w_mm * mm, page_h_mm * mm))
    c.setTitle(title or f"FastMap {format_scale_label(scale_value)}")

    # Map image fills the content area exactly -> printed scale is exact
    x0 = margin_mm * mm
    y0 = margin_mm * mm
    w = cont_w_mm * mm
    h = cont_h_mm * mm
    c.drawImage(ImageReader(img), x0, y0, w, h)
    _draw_frame(c, x0, y0, w, h)

    # --- margin texts ---
    c.setFillColor(black)
    c.setFont("Helvetica", 7)

    # bottom-left: license attribution
    c.drawString(x0, (_INSET_MM + 1) * mm, ATTRIBUTION)

    # bottom-right: scale + date
    info_text = f"{format_scale_label(scale_value)}   {date.today().strftime('%d.%m.%Y')}"
    c.drawRightString((page_w_mm - _INSET_MM) * mm, (_INSET_MM + 1) * mm, info_text)

    # top-centre: optional title
    if title:
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(page_w_mm * mm / 2, (page_h_mm - _INSET_MM - 2) * mm, title)

    # scale bar inside the map area, bottom-right
    dist_m = scale_bar_distance(scale_value, cont_w_mm)
    bar_mm = dist_m / scale_value * 1000.0
    _draw_scale_bar(
        c,
        x_right=(page_w_mm - margin_mm - _INSET_MM) * mm,
        y_bottom=(margin_mm + _INSET_MM) * mm,
        bar_mm=bar_mm,
        dist_m=dist_m,
    )

    c.showPage()
    c.save()

    return PrintResult(
        path=out_pdf_path,
        actual_scale=scale_value,
        extent=extent,
        width_px=px_w,
        height_px=px_h,
    )


def generate_pdf_to_temp(extent, **kwargs) -> PrintResult:
    """Convenience wrapper writing into a unique temporary file."""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(prefix="fastmap_", suffix=".pdf", delete=False)
    tmp.close()
    kwargs["out_pdf_path"] = tmp.name
    return generate_pdf(extent, **kwargs)


__all__ = ["generate_pdf", "generate_pdf_to_temp", "PrintResult"]
