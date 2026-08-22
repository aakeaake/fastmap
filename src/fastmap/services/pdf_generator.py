"""Compose a print-ready PDF page from an EPSG:3067 map extent.

The rendered raster is placed at the exact content-area rectangle of the
page, so the printed scale equals the requested nominal scale. No temp
image files are needed - the PIL image is embedded directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image
from reportlab.lib.colors import black
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
)

ATTRIBUTION = "© Maanmittauslaitos, CC BY 4.0"
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
    """Plain black text drawn over the map imagery."""
    if align_right:
        x -= c.stringWidth(text, font, size)
    c.setFillColor(black)
    c.setFont(font, size)
    c.drawString(x, y, text)


def _draw_page(
    c: canvas.Canvas,
    img: Image.Image,
    extent: Extent,
    *,
    paper_size: str,
    orientation: str,
    margin_mm: float,
    title: str | None,
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
    dpi: int = DEFAULT_DPI,
    margin_mm: float = 7.0,
    title: str | None = None,
    out_pdf_path: str = "map.pdf",
) -> PrintResult:
    """Render ``extent`` and write a scaled PDF page.

    Returns a PrintResult with the true printed scale.
    """
    if layer not in MML_LAYERS:
        raise ValueError(f"Unknown layer '{layer}'")

    page_w_mm, page_h_mm = oriented_page_mm(paper_size, orientation)
    px_w, px_h = content_pixels(paper_size, orientation, dpi, margin_mm)

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
        dpi = kwargs.get("dpi", DEFAULT_DPI)
        margin_mm = kwargs.get("margin_mm", 7.0)

        px_w, px_h = content_pixels(paper_size, orientation, dpi, margin_mm)
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
        )
        results.append(PrintResult(
            path=out_pdf_path,
            actual_scale=scale_value,
            extent=extent,
            width_px=px_w,
            height_px=px_h,
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
