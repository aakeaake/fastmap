"""Pure geometry and layout maths for print maps.

All extents are in EPSG:3067 (ETRS-TM35FIN) metres, which is a metric
projection - so paper millimetres at scale 1:N map directly to N/1000
metres of ground. This is what guarantees the printed scale is true.
"""

from __future__ import annotations

from dataclasses import dataclass

# Paper sizes: (short side, long side) in mm
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
}

# TM35FIN area bounds with a little slack
TM35FIN_BOUNDS = (-548576.0, 6291456.0, 1548576.0, 8388608.0)

MM_PER_INCH = 25.4


@dataclass(frozen=True)
class Extent:
    """Bounding box in EPSG:3067 metres."""

    minx: float
    miny: float
    maxx: float
    maxy: float

    @property
    def width_m(self) -> float:
        return self.maxx - self.minx

    @property
    def height_m(self) -> float:
        return self.maxy - self.miny

    @property
    def center(self) -> tuple[float, float]:
        return ((self.minx + self.maxx) / 2, (self.miny + self.maxy) / 2)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.minx, self.miny, self.maxx, self.maxy)


def oriented_page_mm(paper_size: str, orientation: str) -> tuple[float, float]:
    """Page dimensions (width, height) in mm for the given orientation."""
    short, long = PAPER_SIZES_MM[paper_size.upper()]
    return (long, short) if orientation == "landscape" else (short, long)


def content_area_mm(
    paper_size: str, orientation: str, margin_mm: float
) -> tuple[float, float]:
    """Printable content area (width, height) in mm after equal margins."""
    page_w, page_h = oriented_page_mm(paper_size, orientation)
    w = page_w - 2 * margin_mm
    h = page_h - 2 * margin_mm
    if w <= 0 or h <= 0:
        raise ValueError("Margin too large for paper size")
    return (w, h)


def content_pixels(
    paper_size: str,
    orientation: str,
    dpi: int,
    margin_mm: float,
) -> tuple[int, int]:
    """Raster size (width, height) in pixels for the content area at dpi."""
    w_mm, h_mm = content_area_mm(paper_size, orientation, margin_mm)
    return (
        round(w_mm / MM_PER_INCH * dpi),
        round(h_mm / MM_PER_INCH * dpi),
    )


def extent_for_center(
    center_x: float,
    center_y: float,
    scale: int,
    paper_size: str,
    orientation: str,
    margin_mm: float,
) -> Extent:
    """Ground extent covered by the content area at scale 1:N."""
    w_mm, h_mm = content_area_mm(paper_size, orientation, margin_mm)
    w_m = w_mm / 1000.0 * scale
    h_m = h_mm / 1000.0 * scale
    return Extent(
        minx=center_x - w_m / 2,
        miny=center_y - h_m / 2,
        maxx=center_x + w_m / 2,
        maxy=center_y + h_m / 2,
    )


def snap_extent_to_scale(
    bbox: Extent,
    scale: int,
    paper_size: str,
    orientation: str,
    margin_mm: float,
) -> Extent:
    """Snap a drawn bbox to exact scale and paper aspect around its centre.

    The UI enforces correct sizes already; this guards against float drag
    drift and lets other clients send approximate boxes.
    """
    w_mm, h_mm = content_area_mm(paper_size, orientation, margin_mm)
    w_m = w_mm / 1000.0 * scale
    h_m = h_mm / 1000.0 * scale
    cx, cy = bbox.center
    return Extent(
        minx=cx - w_m / 2,
        miny=cy - h_m / 2,
        maxx=cx + w_m / 2,
        maxy=cy + h_m / 2,
    )


def actual_scale(extent: Extent, content_w_mm: float) -> int:
    """True printed scale implied by extent over the content width."""
    return round(extent.width_m / (content_w_mm / 1000.0))


def with_aspect(extent: Extent, aspect_wh: float) -> Extent:
    """Keep centre and width; set height so height/width == aspect_wh."""
    cx, cy = extent.center
    h_m = extent.width_m * aspect_wh
    return Extent(
        minx=cx - extent.width_m / 2,
        miny=cy - h_m / 2,
        maxx=cx + extent.width_m / 2,
        maxy=cy + h_m / 2,
    )


def clamp_extent_to_finland(extent: Extent) -> Extent:
    """Clamp extent into the TM35FIN bounds, keeping its size."""
    w = extent.width_m
    h = extent.height_m
    minx = min(max(extent.minx, TM35FIN_BOUNDS[0]), TM35FIN_BOUNDS[2] - w)
    maxx = minx + w
    miny = min(max(extent.miny, TM35FIN_BOUNDS[1]), TM35FIN_BOUNDS[3] - h)
    maxy = miny + h
    return Extent(minx, miny, maxx, maxy)


# ---------------------------------------------------------------------------
# Scale bar helpers
# ---------------------------------------------------------------------------

NICE_DISTANCES_M = [
    50, 100, 200, 250, 500,
    1000, 2000, 2500, 5000, 10000, 20000, 50000,
]


def scale_bar_distance(actual_scale: int, content_w_mm: float, max_frac: float = 0.4) -> int:
    """Pick a nice round ground distance whose bar fits within the content width."""
    limit_mm = content_w_mm * max_frac
    best = NICE_DISTANCES_M[0]
    for dist in NICE_DISTANCES_M:
        bar_mm = dist / actual_scale * 1000.0
        if bar_mm <= limit_mm:
            best = dist
        else:
            break
    return best


def format_scale_label(scale_value: float) -> str:
    """Format 1:x with thin-space thousands separators."""
    s = f"{round(scale_value):,}".replace(",", " ")
    return f"1 : {s}"


def format_extent_name(extent: Extent) -> str:
    """Short human-readable place tag from TM35FIN coordinates."""
    lat = extent.center[1]
    return f"N {round(lat)} E {round(extent.center[0])}"
