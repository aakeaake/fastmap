import logging
import os
import re
import tempfile
import threading
import time
import uuid
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

log = logging.getLogger(__name__)
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


# ---------------------------------------------------------------------------
# Async job store (in-memory, single-worker safe)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _resolve_extent(req: MapRequest):
    cont_w_mm, cont_h_mm = content_area_mm(
        req.paper_size, req.orientation, req.margin_mm
    )
    extent = req.resolve_extent(content_aspect_wh=cont_h_mm / cont_w_mm)
    return clamp_extent_to_finland(extent)


def _timestamp() -> str:
    return datetime.now().strftime("%y%m%d%H%M%S")


@router.post("/generate-map")
def generate_map(req: MapRequest):
    """Render a print-ready PDF of the requested EPSG:3067 extent."""
    import time

    if not MML_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server is missing MML_API_KEY configuration.",
        )

    try:
        extent = _resolve_extent(req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    t0 = time.monotonic()
    log.info(
        "generate-map  %s %s 1:%s  layer=%s  zoom=%s",
        req.paper_size, req.orientation, req.scale, req.layer, req.zoom_level,
    )

    try:
        result = generate_pdf_to_temp(
            extent,
            paper_size=req.paper_size,
            orientation=req.orientation,
            layer=req.layer,
            dpi=req.dpi,
            zoom_level=req.zoom_level,
            margin_mm=req.margin_mm,
            title=req.title,
            grid_mode=req.grid_mode,
            grid_spacing_m=req.grid_spacing_m,
            gpx_routes=req.gpx_routes,
            gpx_color=req.gpx_color,
            gpx_width=req.gpx_width,
            gpx_opacity=req.gpx_opacity,
        )
    except MMLError as exc:
        log.warning("generate-map failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"Map data source failed: {exc}",
        ) from exc

    elapsed = time.monotonic() - t0
    name = req.title or f"{req.paper_size}{req.orientation}_{result.actual_scale}"
    display_name = f"fastmap_{name}_{_timestamp()}.pdf"
    log.info(
        "generate-map done in %.1fs  -> %s  (%dx%d px)",
        elapsed, display_name, result.width_px, result.height_px,
    )

    return FileResponse(
        result.path,
        media_type="application/pdf",
        filename=display_name,
        background=BackgroundTask(os.remove, result.path),
    )


# ---------------------------------------------------------------------------
# Async generation (avoids 50s idle-timeout wind-down)
# ---------------------------------------------------------------------------

def _run_job(job_id: str, req: MapRequest) -> None:
    """Background thread: generate PDF and update job status."""
    try:
        t0 = time.monotonic()
        extent = _resolve_extent(req)
        log.info("async job %s started", job_id)
        result = generate_pdf_to_temp(
            extent,
            paper_size=req.paper_size,
            orientation=req.orientation,
            layer=req.layer,
            dpi=req.dpi,
            zoom_level=req.zoom_level,
            margin_mm=req.margin_mm,
            title=req.title,
            grid_mode=req.grid_mode,
            grid_spacing_m=req.grid_spacing_m,
            gpx_routes=req.gpx_routes,
            gpx_color=req.gpx_color,
            gpx_width=req.gpx_width,
            gpx_opacity=req.gpx_opacity,
        )
        name = req.title or f"{req.paper_size}{req.orientation}_{result.actual_scale}"
        display_name = f"fastmap_{name}_{_timestamp()}.pdf"
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["path"] = result.path
            _jobs[job_id]["filename"] = display_name
            _jobs[job_id]["actual_scale"] = result.actual_scale
        log.info("async job %s done in %.1fs  -> %s", job_id, time.monotonic() - t0, display_name)
    except Exception as exc:
        log.warning("async job %s failed: %s", job_id, exc)
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)


@router.post("/generate-map-async")
def generate_map_async(req: MapRequest):
    """Start PDF generation in background, return job ID for polling."""
    if not MML_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server is missing MML_API_KEY configuration.",
        )
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending"}

    t = threading.Thread(target=_run_job, args=(job_id, req), daemon=True)
    t.start()
    return {"job_id": job_id}


@router.get("/map-status/{job_id}")
def map_status(job_id: str):
    """Poll this to check job progress. Returns status + download_url when done."""
    with _jobs_lock:
        job = _jobs.get(job_id)
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
    """Download the completed PDF. Cleans up the temp file after serving."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Job not ready yet")

    path = job["path"]
    filename = job["filename"]
    media_type = job.get("media_type", "application/pdf")
    with _jobs_lock:
        _jobs.pop(job_id, None)
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        background=BackgroundTask(os.remove, path),
    )


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


@router.post("/generate-maps-batch")
def generate_maps_batch(batch: BatchMapRequest):
    """Render several maps as one multi-page PDF or a ZIP of PDFs."""
    import time

    if not MML_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server is missing MML_API_KEY configuration.",
        )

    try:
        pairs = [(_resolve_extent(m), m) for m in batch.maps]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    t0 = time.monotonic()
    log.info(
        "generate-maps-batch  %d maps  output=%s",
        len(pairs), batch.output,
    )

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
            log.warning("generate-maps-batch failed: %s", exc)
            raise HTTPException(
                status_code=502, detail=f"Map data source failed: {exc}"
            ) from exc

        elapsed = time.monotonic() - t0
        log.info("generate-maps-batch done in %.1fs  -> %d pages", elapsed, len(pairs))
        return FileResponse(
            tmp.name,
            media_type="application/pdf",
            filename=f"fastmap_{len(pairs)}pages_{_timestamp()}.pdf",
            background=BackgroundTask(_remove_quietly, [tmp.name]),
        )

    # ZIP of individual PDFs
    pdf_paths: list[str] = []
    try:
        for i, (extent, req) in enumerate(pairs, start=1):
            log.info("generate-maps-batch  map %d/%d", i, len(pairs))
            result = generate_pdf_to_temp(extent, **_req_kwargs(req))
            pdf_paths.append(result.path)
    except MMLError as exc:
        _remove_quietly(pdf_paths)
        log.warning("generate-maps-batch failed at map %d: %s", len(pdf_paths) + 1, exc)
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

    elapsed = time.monotonic() - t0
    log.info("generate-maps-batch done in %.1fs  -> ZIP %d files", elapsed, len(pairs))
    return FileResponse(
        zip_tmp.name,
        media_type="application/zip",
        filename=f"fastmap_{len(pairs)}maps_{_timestamp()}.zip",
        background=BackgroundTask(_remove_quietly, [*pdf_paths, zip_tmp.name]),
    )


# ---------------------------------------------------------------------------
# Async batch generation (avoids 50s idle-timeout wind-down)
# ---------------------------------------------------------------------------

def _run_batch_job(job_id: str, batch: BatchMapRequest) -> None:
    """Background thread: generate batch PDF/ZIP and update job status."""
    try:
        t0 = time.monotonic()
        pairs = [(_resolve_extent(m), m) for m in batch.maps]
        log.info("async batch job %s started  %d maps", job_id, len(pairs))

        if batch.output == "pdf":
            tmp = tempfile.NamedTemporaryFile(
                prefix="fastmap_batch_", suffix=".pdf", delete=False
            )
            tmp.close()
            try:
                generate_multi_pdf(
                    [(extent, _req_kwargs(m)) for extent, m in pairs], tmp.name
                )
            except Exception:
                _remove_quietly([tmp.name])
                raise
            filename = f"fastmap_{len(pairs)}pages_{_timestamp()}.pdf"
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["path"] = tmp.name
                _jobs[job_id]["filename"] = filename
                _jobs[job_id]["media_type"] = "application/pdf"
        else:
            # ZIP of individual PDFs
            pdf_paths: list[str] = []
            for i, (extent, req) in enumerate(pairs, start=1):
                log.info("async batch job %s  map %d/%d", job_id, i, len(pairs))
                result = generate_pdf_to_temp(extent, **_req_kwargs(req))
                pdf_paths.append(result.path)

            zip_tmp = tempfile.NamedTemporaryFile(
                prefix="fastmap_maps_", suffix=".zip", delete=False
            )
            zip_tmp.close()
            with zipfile.ZipFile(zip_tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, (path, (_, req)) in enumerate(zip(pdf_paths, pairs), start=1):
                    name_title = req.title or f"Kartta {i}"
                    zf.write(path, arcname=f"{i:02d}_{_slug(name_title)}.pdf")
            _remove_quietly(pdf_paths)

            filename = f"fastmap_{len(pairs)}maps_{_timestamp()}.zip"
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["path"] = zip_tmp.name
                _jobs[job_id]["filename"] = filename
                _jobs[job_id]["media_type"] = "application/zip"

        log.info("async batch job %s done in %.1fs  -> %s", job_id, time.monotonic() - t0, filename)
    except Exception as exc:
        log.warning("async batch job %s failed: %s", job_id, exc)
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)


@router.post("/generate-maps-batch-async")
def generate_maps_batch_async(batch: BatchMapRequest):
    """Start batch generation in background, return job ID for polling."""
    if not MML_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Server is missing MML_API_KEY configuration.",
        )
    try:
        # Validate extents eagerly so bad input fails fast
        for m in batch.maps:
            _resolve_extent(m)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "pending"}

    t = threading.Thread(target=_run_batch_job, args=(job_id, batch), daemon=True)
    t.start()
    return {"job_id": job_id}


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
        log.warning("tile fetch failed  %s %d", url, resp.status_code)
        raise HTTPException(
            status_code=502, detail=f"MML tile fetch failed ({resp.status_code})"
        )

    return Response(
        content=resp.content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
