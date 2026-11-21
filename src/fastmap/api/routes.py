import logging
import os
import re
import tempfile
import time
import zipfile
from datetime import datetime

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from fastmap.core.config import (
    JOB_TTL_S,
    MAX_PENDING_JOBS,
    MML_API_KEY,
    MML_WMTS_URL,
    RENDER_WORKERS,
    USER_AGENT,
)
from fastmap.schemas.map_request import BatchMapRequest, MapRequest
from fastmap.services.jobs import JobStore, QueueFull
from fastmap.services.mml_source import (
    MML_LAYERS,
    VECTOR_LAYER,
    WMTS_MAX_LEVEL,
    MMLError,
)
from fastmap.services.pdf_generator import (
    attribution,
    generate_multi_pdf,
    generate_pdf_to_temp,
)
from fastmap.services.print_layout import (
    clamp_extent_to_finland,
    content_area_mm,
)

log = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Rendering: every map (sync or async) goes through one bounded job store
# ---------------------------------------------------------------------------

jobs = JobStore(workers=RENDER_WORKERS, max_pending=MAX_PENDING_JOBS, ttl_s=JOB_TTL_S)

_BUSY = HTTPException(
    status_code=503,
    detail="Palvelu on ruuhkautunut, yritä hetken kuluttua uudelleen.",
    headers={"Retry-After": "30"},
)


def _require_key() -> None:
    if not MML_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server is missing MML_API_KEY configuration.",
        )


def _resolve_extent(req: MapRequest):
    cont_w_mm, cont_h_mm = content_area_mm(req.paper_size, req.orientation, req.margin_mm)
    extent = req.resolve_extent(content_aspect_wh=cont_h_mm / cont_w_mm)
    return clamp_extent_to_finland(extent)


def _resolve_or_422(maps: list[MapRequest]) -> list:
    try:
        return [(_resolve_extent(m), m) for m in maps]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _timestamp() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S")


def _req_kwargs(req: MapRequest) -> dict:
    return req.model_dump(exclude={"bbox", "center_x", "center_y", "scale"})


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


def _render_single(extent, req: MapRequest) -> dict:
    """Render one map to a temp PDF; returns the job result fields."""
    t0 = time.monotonic()
    log.info(
        "generate-map  %s %s 1:%s  layer=%s  zoom=%s",
        req.paper_size,
        req.orientation,
        req.scale,
        req.layer,
        req.zoom_level,
    )
    result = generate_pdf_to_temp(extent, **_req_kwargs(req))
    name = req.title or f"{req.paper_size}{req.orientation}_{result.actual_scale}"
    filename = f"fastmap_{name}_{_timestamp()}.pdf"
    log.info(
        "generate-map done in %.1fs  -> %s  (%dx%d px)",
        time.monotonic() - t0,
        filename,
        result.width_px,
        result.height_px,
    )
    return {
        "path": result.path,
        "filename": filename,
        "media_type": "application/pdf",
        "actual_scale": result.actual_scale,
    }


def _render_batch(pairs: list, output: str) -> dict:
    """Render several maps as one multi-page PDF or a ZIP of PDFs."""
    t0 = time.monotonic()
    log.info("generate-maps-batch  %d maps  output=%s", len(pairs), output)

    if output == "pdf":
        tmp = tempfile.NamedTemporaryFile(prefix="fastmap_batch_", suffix=".pdf", delete=False)
        tmp.close()
        try:
            generate_multi_pdf([(extent, _req_kwargs(m)) for extent, m in pairs], tmp.name)
        except Exception:
            _remove_quietly([tmp.name])
            raise
        result = {
            "path": tmp.name,
            "filename": f"fastmap_{len(pairs)}pages_{_timestamp()}.pdf",
            "media_type": "application/pdf",
        }
    else:
        pdf_paths: list[str] = []
        zip_path: str | None = None
        try:
            for i, (extent, req) in enumerate(pairs, start=1):
                log.info("generate-maps-batch  map %d/%d", i, len(pairs))
                pdf_paths.append(generate_pdf_to_temp(extent, **_req_kwargs(req)).path)
            zip_tmp = tempfile.NamedTemporaryFile(
                prefix="fastmap_maps_", suffix=".zip", delete=False
            )
            zip_tmp.close()
            zip_path = zip_tmp.name
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, (path, (_, req)) in enumerate(zip(pdf_paths, pairs, strict=True), start=1):
                    zf.write(path, arcname=f"{i:02d}_{_slug(req.title or f'Kartta {i}')}.pdf")
        except Exception:
            if zip_path:
                _remove_quietly([zip_path])  # partial ZIP
            raise
        finally:
            _remove_quietly(pdf_paths)
        result = {
            "path": zip_path,
            "filename": f"fastmap_{len(pairs)}maps_{_timestamp()}.zip",
            "media_type": "application/zip",
        }

    log.info("generate-maps-batch done in %.1fs  -> %s", time.monotonic() - t0, result["filename"])
    return result


def _run_now(fn) -> dict:
    """Render synchronously on an idle worker, mapping errors to HTTP.

    Sync requests never queue: waiting behind other renders could outlast the
    proxy's idle timeout, leaving a render (and its temp file, normally deleted
    by the response's background task) for a client that has gone. They get
    503 + Retry-After instead; the UI uses the async endpoints.
    """
    try:
        return jobs.run(fn)
    except QueueFull as exc:
        raise _BUSY from exc
    except MMLError as exc:
        log.warning("render failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Map data source failed: {exc}") from exc


def _file_response(result: dict) -> FileResponse:
    return FileResponse(
        result["path"],
        media_type=result["media_type"],
        filename=result["filename"],
        background=BackgroundTask(_remove_quietly, [result["path"]]),
    )


def _submit(fn) -> dict:
    try:
        return {"job_id": jobs.submit(fn)}
    except QueueFull as exc:
        raise _BUSY from exc


@router.post("/generate-map")
def generate_map(req: MapRequest):
    """Render a print-ready PDF of the requested EPSG:3067 extent."""
    _require_key()
    [(extent, _)] = _resolve_or_422([req])
    return _file_response(_run_now(lambda: _render_single(extent, req)))


@router.post("/generate-map-async")
def generate_map_async(req: MapRequest):
    """Start PDF generation in background, return job ID for polling."""
    _require_key()
    [(extent, _)] = _resolve_or_422([req])
    return _submit(lambda: _render_single(extent, req))


@router.post("/generate-maps-batch")
def generate_maps_batch(batch: BatchMapRequest):
    """Render several maps as one multi-page PDF or a ZIP of PDFs."""
    _require_key()
    pairs = _resolve_or_422(batch.maps)
    return _file_response(_run_now(lambda: _render_batch(pairs, batch.output)))


@router.post("/generate-maps-batch-async")
def generate_maps_batch_async(batch: BatchMapRequest):
    """Start batch generation in background, return job ID for polling."""
    _require_key()
    pairs = _resolve_or_422(batch.maps)
    return _submit(lambda: _render_batch(pairs, batch.output))


@router.get("/map-status/{job_id}")
def map_status(job_id: str):
    """Poll this to check job progress. Returns status + download_url when done."""
    jobs.sweep()
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if job["status"] == "done":
        result = {
            "status": "done",
            "download_url": f"/map-download/{job_id}",
            "filename": job["filename"],
        }
        if "actual_scale" in job:
            result["actual_scale"] = job["actual_scale"]
        return result
    if job["status"] == "error":
        return {"status": "error", "error": job["error"]}
    return {"status": "pending"}


@router.get("/map-download/{job_id}")
def map_download(job_id: str):
    """Download the completed file. Cleans up the temp file after serving."""
    # One atomic step: a second download or a sweep can't delete the file
    # while this response is still streaming it.
    job = jobs.take_done(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Job not ready yet")
    return _file_response(job)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/api/attribution")
def get_attribution():
    """The MML licence line printed on PDFs, so the frontend shows the same text."""
    return {"text": attribution()}


# ---------------------------------------------------------------------------
# NLS WMTS preview proxy: keeps the API key server-side.
# Frontend requests /api/nls-tiles/{level}/{col}/{row}.png?layer=name
# ---------------------------------------------------------------------------

_TILE_MAX = 1 << 15


@router.get("/api/nls-tiles/{level}/{col}/{row}.png")
def nls_tile(level: int, col: int, row: int, layer: str = "taustakartta"):
    if not MML_API_KEY:
        raise HTTPException(status_code=503, detail="Missing MML_API_KEY.")
    if not (0 <= level <= WMTS_MAX_LEVEL and 0 <= col < _TILE_MAX and 0 <= row < _TILE_MAX):
        raise HTTPException(status_code=404, detail="Tile out of range")
    if layer not in MML_LAYERS:
        raise HTTPException(status_code=400, detail=f"Unknown layer '{layer}'")

    # The vector map has no raster tiles of its own: preview with the raster map
    raster_layer = "maastokartta" if layer == VECTOR_LAYER else layer
    url = MML_WMTS_URL.format(layer=raster_layer, z=level, y=row, x=col)
    try:
        resp = requests.get(
            url,
            params={"api-key": MML_API_KEY},
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
    except requests.RequestException as exc:
        # requests' message contains the full URL incl. the api-key query param
        log.warning("tile fetch failed  %s %s", url, type(exc).__name__)
        raise HTTPException(status_code=502, detail="MML tile fetch failed") from None
    if resp.status_code != 200:
        log.warning("tile fetch failed  %s %d", url, resp.status_code)
        raise HTTPException(status_code=502, detail=f"MML tile fetch failed ({resp.status_code})")

    return Response(
        content=resp.content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
