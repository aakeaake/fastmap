from typing import Literal

from pydantic import BaseModel, Field, model_validator

from fastmap.services.print_layout import (
    TM35FIN_BOUNDS,
    Extent,
    extent_for_center,
    snap_extent_to_scale,
    with_aspect,
)

PaperSize = Literal["A4", "A3"]
Orientation = Literal["portrait", "landscape"]
MMLLayer = Literal["maastokartta", "taustakartta", "selkokartta", "ortokuva"]


class BBox(BaseModel):
    """Bounding box in EPSG:3067 (ETRS-TM35FIN) metres."""

    minx: float
    miny: float
    maxx: float
    maxy: float


class MapRequest(BaseModel):
    """Map generation request.

    Either ``bbox`` (EPSG:3067 corners) or ``center_x``/``center_y`` +
    ``scale`` must be given. With a bbox and a nominal ``scale``, the box
    is snapped to exact scale/paper aspect around its centre; without a
    scale the width is kept and only the aspect is enforced. The true
    printed scale is always derived from the final extent.
    """

    # Option A: explicit extent (preferred - UI sends this)
    bbox: BBox | None = None

    # Option B: centre point + nominal scale
    center_x: float | None = Field(default=None, ge=TM35FIN_BOUNDS[0], le=TM35FIN_BOUNDS[2])
    center_y: float | None = Field(default=None, ge=TM35FIN_BOUNDS[1], le=TM35FIN_BOUNDS[3])
    scale: int | None = Field(default=None, ge=100, le=2_000_000)

    paper_size: PaperSize = "A4"
    orientation: Orientation = "portrait"
    layer: MMLLayer = "maastokartta"
    dpi: int = Field(default=300, ge=72, le=600)
    margin_mm: float = Field(default=7.0, ge=0.0, le=30.0)
    title: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _check_location(self) -> "MapRequest":
        if self.bbox is None and not (
            self.center_x is not None and self.center_y is not None and self.scale is not None
        ):
            raise ValueError(
                "Provide either 'bbox' or all of 'center_x', 'center_y' and 'scale'"
            )
        return self

    def resolve_extent(self, content_aspect_wh: float) -> Extent:
        """Resolve the request into an exact EPSG:3067 Extent.

        ``content_aspect_wh`` is the printable content area's
        height/width ratio, used when only a free-form bbox is supplied.
        """
        if self.bbox is not None:
            raw = Extent(
                self.bbox.minx, self.bbox.miny, self.bbox.maxx, self.bbox.maxy
            )
            if raw.width_m <= 0 or raw.height_m <= 0:
                raise ValueError("bbox must have positive width and height")
            if raw.width_m > 500_000 or raw.height_m > 500_000:
                raise ValueError("bbox is unreasonably large (> 500 km)")
            if self.scale is not None:
                return snap_extent_to_scale(
                    raw,
                    self.scale,
                    self.paper_size,
                    self.orientation,
                    self.margin_mm,
                )
            return with_aspect(raw, content_aspect_wh)

        return extent_for_center(
            self.center_x,
            self.center_y,
            self.scale,
            self.paper_size,
            self.orientation,
            self.margin_mm,
        )


class BatchMapRequest(BaseModel):
    """Several maps rendered in one request.

    ``output`` selects the delivery format: a single multi-page PDF (pages
    may mix paper sizes/orientations) or a ZIP of individual PDFs.
    """

    maps: list[MapRequest] = Field(min_length=1, max_length=25)
    output: Literal["pdf", "zip"] = "pdf"
