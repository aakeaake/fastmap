import os
import re
import tempfile
import zipfile
from datetime import datetime

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from fastmap.core.config import (
    MML_API_KEY,
    MML_WMTS_URL,
    USER_AGENT,
)
from fastmap.schemas.map_request import BatchMapRequest, MapRequest
from fastmap.services.mml_source import (
    MMLError,
    MML_LAYERS,
    WMTS_MAX_LEVEL,
)
from fastmap.services.pdf_generator import (
    generate_multi_pdf,
    generate_pdf_to_temp,
)
from fastmap.services.print_layout import (
    clamp_extent_to_finland,
    content_area_mm,
)

router = APIRouter()


def _resolve_extent(req: MapRequest):
    cont_w_mm, cont_h_mm = content_area_mm(
        req.paper_size, req.orientation, req.margin_mm
    )
    extent = req.resolve_extent(content_aspect_wh=cont_h_mm / cont_w_mm)
    return clamp_extent_to_finland(extent)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M")


@router.post("/generate-map")
def generate_map(req: MapRequest):
    """Render a print-ready PDF of the requested EPSG:3067 extent."""
    if not MML_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server is missing MML_API_KEY configuration.",
        )

    try:
        extent = _resolve_extent(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = generate_pdf_to_temp(
            extent,
            paper_size=req.paper_size,
            orientation=req.orientation,
            layer=req.layer,
            dpi=req.dpi,
            margin_mm=req.margin_mm,
            title=req.title,
            grid_mode=req.grid_mode,
            grid_spacing_m=req.grid_spacing_m,
        )
    except MMLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Map data source failed: {exc}",
        ) from exc

    display_name = (
        f"fastmap_{req.paper_size}_{req.orientation}_"
        f"1-{result.actual_scale}_{_timestamp()}.pdf"
    )

    return FileResponse(
        result.path,
        media_type="application/pdf",
        filename=display_name,
        background=BackgroundTask(os.remove, result.path),
    )


def _req_kwargs(req: MapRequest) -> dict:
    return {
        "paper_size": req.paper_size,
        "orientation": req.orientation,
        "layer": req.layer,
        "dpi": req.dpi,
        "margin_mm": req.margin_mm,
        "title": req.title,
        "grid_mode": req.grid_mode,
        "grid_spacing_m": req.grid_spacing_m,
    }


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    s = s.strip("_")
    return s[:40] or "kartta"


def _remove_quietly(paths: list[str]) -> None:
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


@router.post("/generate-maps-batch")
def generate_maps_batch(batch: BatchMapRequest):
    """Render several maps as one multi-page PDF or a ZIP of PDFs."""
    if not MML_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server is missing MML_API_KEY configuration.",
        )

    try:
        pairs = [(_resolve_extent(m), m) for m in batch.maps]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if batch.output == "pdf":
        tmp = tempfile.NamedTemporaryFile(
            prefix="fastmap_batch_", suffix=".pdf", delete=False
        )
        tmp.close()
        try:
            generate_multi_pdf(
                [(extent, _req_kwargs(m)) for extent, m in pairs], tmp.name
            )
        except MMLError as exc:
            _remove_quietly([tmp.name])
            raise HTTPException(
                status_code=502, detail=f"Map data source failed: {exc}"
            ) from exc

        return FileResponse(
            tmp.name,
            media_type="application/pdf",
            filename=f"fastmap_batch_{len(pairs)}pages_{_timestamp()}.pdf",
            background=BackgroundTask(_remove_quietly, [tmp.name]),
        )

    # ZIP of individual PDFs
    pdf_paths: list[str] = []
    try:
        for extent, req in pairs:
            result = generate_pdf_to_temp(extent, **_req_kwargs(req))
            pdf_paths.append(result.path)
    except MMLError as exc:
        _remove_quietly(pdf_paths)
        raise HTTPException(
            status_code=502, detail=f"Map data source failed: {exc}"
        ) from exc

    zip_tmp = tempfile.NamedTemporaryFile(
        prefix="fastmap_maps_", suffix=".zip", delete=False
    )
    zip_tmp.close()
    with zipfile.ZipFile(zip_tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, (path, (_, req)) in enumerate(zip(pdf_paths, pairs), start=1):
            name_title = req.title or f"Kartta {i}"
            zf.write(path, arcname=f"{i:02d}_{_slug(name_title)}.pdf")

    return FileResponse(
        zip_tmp.name,
        media_type="application/zip",
        filename=f"fastmap_maps_{_timestamp()}.zip",
        background=BackgroundTask(_remove_quietly, [*pdf_paths, zip_tmp.name]),
    )


@router.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# NLS WMTS preview proxy: keeps the API key server-side.
# Frontend requests /api/nls-tiles/{level}/{col}/{row}.png?layer=name
# ---------------------------------------------------------------------------

_TILE_MAX = 1 << 15


@router.get("/api/nls-tiles/{level}/{col}/{row}.png")
def nls_tile(level: int, col: int, row: int, layer: str = "taustakartta"):
    if not MML_API_KEY:
        raise HTTPException(status_code=503, detail="Missing MML_API_KEY.")
    if not (
        0 <= level <= WMTS_MAX_LEVEL
        and 0 <= col < _TILE_MAX
        and 0 <= row < _TILE_MAX
    ):
        raise HTTPException(status_code=404, detail="Tile out of range")
    if layer not in MML_LAYERS:
        raise HTTPException(status_code=400, detail=f"Unknown layer '{layer}'")

    url = MML_WMTS_URL.format(layer=layer, z=level, y=row, x=col)
    resp = requests.get(
        url,
        params={"api-key": MML_API_KEY},
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502, detail=f"MML tile fetch failed ({resp.status_code})"
        )

    return Response(
        content=resp.content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
