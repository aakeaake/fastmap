"""Fetching MML (National Land Survey of Finland) raster map images.

Both paths are in EPSG:3067 (ETRS-TM35FIN) so printed scale is true:

* ``fetch_wmts_mosaic`` - stitches WMTS ETRS-TM35FIN tiles and crops to
  the bbox. Primary path: the free open-data service ("Karttakuva avoin")
  offers WMTS only, at matrix levels 0-13.
* ``fetch_wms_image``  - WMS GetMap returns exactly the requested bbox at
  the exact pixel size in a single request. Only used when ``MML_WMS_URL``
  is configured (contract licence customers); otherwise skipped silently.
"""

from __future__ import annotations

import http.cookiejar
import io
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.exceptions import ReadTimeoutError
from urllib3.util.retry import Retry

from fastmap.core.config import (
    MAX_RENDER_PIXELS,
    MML_API_KEY,
    MML_WMS_URL,
    MML_WMTS_URL,
    RENDER_WORKERS,
    TILE_FETCH_WORKERS,
    USER_AGENT,
)
from fastmap.services.print_layout import Extent

WMTS_TILE_SIZE = 256
# Tile matrix set "ETRS-TM35FIN": resolution = 8192 / 2**level. The open
# service serves levels 0-13 (0.5 m/px would be level 14 - contract only).
WMTS_MAX_LEVEL = 13
WMTS_ORIGIN = (-548576.0, 8388608.0)  # top-left corner of level-0 mosaic

VECTOR_LAYER = "maastokartta_vektori"
MML_LAYERS = ("maastokartta", "taustakartta", "selkokartta", "ortokuva", VECTOR_LAYER)

# Retries for every MML request (tiles and WMS), done by urllib3 on the
# shared session: up to 2 retries for connection errors and for 429/5xx
# (no wait before the 1st retry, 1 s before the 2nd; a 429's Retry-After is
# honoured, capped). Dropped connections (reset, RemoteDisconnected) count
# as read errors and ARE retried; read *timeouts* are not, and connects time
# out after 5 s, so an unresponsive MML fails a tile in ~30 s instead of
# ~90 s and doesn't keep the render workers busy.
TILE_TIMEOUT = (5, 30)  # (connect, read) seconds
WMS_TIMEOUT = (5, 60)
MAX_RETRY_AFTER_S = 10.0


class _Retry(Retry):
    def increment(self, method=None, url=None, response=None, error=None, **kwargs):
        # Re-raise the timeout itself (not MaxRetryError), so requests maps it
        # to requests.ReadTimeout and the error names the actual cause.
        if isinstance(error, ReadTimeoutError):
            raise error
        return super().increment(method, url, response=response, error=error, **kwargs)

    def get_retry_after(self, response):
        seconds = super().get_retry_after(response)
        return None if seconds is None else min(seconds, MAX_RETRY_AFTER_S)


_RETRY = _Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    respect_retry_after_header=True,
    raise_on_status=False,  # hand back the last response so errors name its status
)

# urllib3 logs request URLs, query string included, so the API key: WARNING
# when it retries a broken connection, DEBUG for every request and retry.
# Redact it before any handler sees the record. A logger's filters only see
# records logged on that logger itself (not on its children), so the filter
# goes on every urllib3 logger. They all exist by now: urllib3 creates them
# at import, and importing requests imported it.
_API_KEY_RE = re.compile(r"(api-key=)[^&\s'\"#]+", re.IGNORECASE)


class _RedactApiKey(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # urllib3 passes the URL in record.args; render the message first so
        # neither msg nor args (nor any object's repr) keeps the key.
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - malformed record: redact what we can
            message = f"{record.msg} {record.args}"
        record.msg = _API_KEY_RE.sub(r"\1REDACTED", message)
        record.args = None
        return True


def _install_log_redaction() -> None:
    names = {"urllib3"} | {
        name for name in list(logging.Logger.manager.loggerDict) if name.startswith("urllib3.")
    }
    for name in sorted(names):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _RedactApiKey) for f in logger.filters):
            logger.addFilter(_RedactApiKey())


_install_log_redaction()


# One process-wide pool downloads tiles for every render, so MML never sees
# more than TILE_FETCH_WORKERS tile requests at once, however many renders
# run. A failed render cancels its queued tiles; its in-flight ones finish
# inside the same limit and are closed (see fetch_wmts_mosaic).
_tile_pool = ThreadPoolExecutor(max_workers=TILE_FETCH_WORKERS, thread_name_prefix="tiles")


def shutdown_tile_pool() -> None:
    """Cancel queued tile downloads (at app shutdown)."""
    _tile_pool.shutdown(wait=False, cancel_futures=True)


# One Session is shared by the tile threads and the render workers. That is
# safe here: urllib3's connection pool is thread-safe, the adapters and
# headers are set once at import and only read afterwards, and the cookie
# jar is disabled (MML sets load-balancer cookies the tiles don't need), so
# no per-request state is shared between threads.
_HEADERS = {"User-Agent": USER_AGENT}
_session = requests.Session()
_session.headers.update(_HEADERS)
_session.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
# Enough pooled connections for every request that can be in flight at
# once: the tile pool, one WMS request per render worker, and the preview
# proxy's tiles (a browser loads a map view a few dozen tiles at a time).
# Fewer, and urllib3 discards and reopens (TLS) connections.
_PREVIEW_CONNECTIONS = 16
_POOL_MAXSIZE = TILE_FETCH_WORKERS + RENDER_WORKERS + _PREVIEW_CONNECTIONS
_session.mount("https://", HTTPAdapter(max_retries=_RETRY, pool_maxsize=_POOL_MAXSIZE))
_session.mount("http://", HTTPAdapter(max_retries=_RETRY, pool_maxsize=_POOL_MAXSIZE))


class MMLError(RuntimeError):
    """Raised when MML services cannot deliver an image."""


def _require_api_key() -> str:
    if not MML_API_KEY:
        raise MMLError("MML API key is not configured. Set MML_API_KEY in .env (see .env.example).")
    return MML_API_KEY


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _on_white(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white so no-data areas print as white."""
    if img.mode == "RGB":
        return img
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])
    img.close()
    return bg


# ---------------------------------------------------------------------------
# WMS
# ---------------------------------------------------------------------------


def build_wms_url(
    extent: Extent,
    width_px: int,
    height_px: int,
    layer: str,
) -> str:
    """Build a WMS 1.1.1 GetMap URL (1.1.1 keeps bbox axis order x,y)."""
    if not MML_WMS_URL:
        raise MMLError(
            "No WMS endpoint configured. The free MML open-data service is "
            "WMTS-only; set MML_WMS_URL to use a contract licence."
        )
    key = _require_api_key()
    params = {
        "service": "WMS",
        "version": "1.1.1",
        "request": "GetMap",
        "layers": layer,
        "styles": "",
        "srs": "EPSG:3067",
        "bbox": ",".join(str(v) for v in extent.as_tuple()),
        "width": width_px,
        "height": height_px,
        "format": "image/png",
        "api-key": key,
    }
    return MML_WMS_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())


def fetch_wms_image(
    extent: Extent,
    width_px: int,
    height_px: int,
    layer: str = "maastokartta",
) -> Image.Image:
    url = build_wms_url(extent, width_px, height_px, layer)
    try:
        resp = _session.get(url, timeout=WMS_TIMEOUT)  # retried by the adapter
    except requests.RequestException as exc:
        # never echo the URL: it carries the API key
        raise MMLError(f"WMS GetMap failed ({type(exc).__name__})") from None
    if resp.status_code != 200:
        raise MMLError(f"WMS GetMap failed ({resp.status_code}): {resp.text[:200]}")
    try:
        img = _on_white(Image.open(io.BytesIO(resp.content)))
        resp.close()
        return img
    except Exception as exc:  # noqa: BLE001
        raise MMLError(f"WMS returned a non-image payload: {exc}") from exc


# ---------------------------------------------------------------------------
# WMTS
# ---------------------------------------------------------------------------


def wmts_resolution(level: int) -> float:
    return 8192.0 / 2**level


def pick_wmts_level(target_res: float) -> int:
    """Closest matrix level to target ground resolution (ties -> finer)."""
    best = min(
        range(WMTS_MAX_LEVEL + 1),
        key=lambda z: (abs(wmts_resolution(z) - target_res), wmts_resolution(z)),
    )
    return best


def tile_range(extent: Extent, level: int) -> tuple[int, int, int, int]:
    """Tile index range (col_min, row_min, col_max, row_max) covering extent."""
    res = wmts_resolution(level)
    ts = WMTS_TILE_SIZE * res
    ox, oy = WMTS_ORIGIN
    col_min = math.floor((extent.minx - ox) / ts)
    col_max = math.ceil((extent.maxx - ox) / ts) - 1
    row_min = math.floor((oy - extent.maxy) / ts)
    row_max = math.ceil((oy - extent.miny) / ts) - 1
    return col_min, row_min, col_max, row_max


def fetch_wmts_tile(x: int, y: int, level: int, layer: str) -> Image.Image:
    """Fetch one tile. REST path order is {z}/{TileRow}/{TileCol}."""
    key = _require_api_key()
    url = MML_WMTS_URL.format(layer=layer, z=level, y=y, x=x) + f"?api-key={key}"
    # Error messages reach clients and logs: name the tile, never the URL
    # (it carries the API key, and requests' own messages include it).
    tile = f"{layer} {level}/{y}/{x}"
    try:
        resp = _session.get(url, timeout=TILE_TIMEOUT)  # retried by the adapter
    except requests.RequestException as exc:
        raise MMLError(f"WMTS tile fetch failed ({type(exc).__name__}) for {tile}") from None
    if resp.status_code != 200:
        raise MMLError(f"WMTS tile fetch failed ({resp.status_code}) for {tile}")
    img = _on_white(Image.open(io.BytesIO(resp.content)))
    resp.close()
    return img


def fetch_wmts_mosaic(
    extent: Extent,
    width_px: int,
    height_px: int,
    layer: str = "maastokartta",
) -> Image.Image:
    """Stitch WMTS tiles covering extent, crop to extent at native resolution."""
    if width_px * height_px > MAX_RENDER_PIXELS:
        raise MMLError("Requested render is too large")

    target_res = extent.width_m / width_px
    level = pick_wmts_level(target_res)
    res = wmts_resolution(level)

    col_min, row_min, col_max, row_max = tile_range(extent, level)
    n_cols = col_max - col_min + 1
    n_rows = row_max - row_min + 1
    if n_cols * n_rows > 600:
        raise MMLError("Requested area needs too many tiles at chosen level")

    # Pre-compute crop bounds in mosaic pixel space
    ox, oy = WMTS_ORIGIN
    crop_left = (extent.minx - (ox + col_min * WMTS_TILE_SIZE * res)) / res
    crop_top = ((oy - row_min * WMTS_TILE_SIZE * res) - extent.maxy) / res
    crop_right = crop_left + extent.width_m / res
    crop_bottom = crop_top + extent.height_m / res

    crop_left_px = round(crop_left)
    crop_top_px = round(crop_top)
    crop_right_px = round(crop_right)
    crop_bottom_px = round(crop_bottom)
    out_w = crop_right_px - crop_left_px
    out_h = crop_bottom_px - crop_top_px
    output = Image.new("RGB", (out_w, out_h))

    def paste(r: int, c: int, tile: Image.Image) -> None:
        # Tile bounds in mosaic pixel space, intersected with the crop region
        tx = c * WMTS_TILE_SIZE
        ty = r * WMTS_TILE_SIZE
        src_left = max(0, crop_left_px - tx)
        src_top = max(0, crop_top_px - ty)
        src_right = min(WMTS_TILE_SIZE, crop_right_px - tx)
        src_bottom = min(WMTS_TILE_SIZE, crop_bottom_px - ty)
        if src_left < src_right and src_top < src_bottom:
            tile_crop = tile.crop((src_left, src_top, src_right, src_bottom))
            output.paste(tile_crop, (tx + src_left - crop_left_px, ty + src_top - crop_top_px))
            tile_crop.close()
        tile.close()

    def fetch(r: int, c: int):
        return r, c, fetch_wmts_tile(col_min + c, row_min + r, level, layer)

    # Download tiles on the shared pool (network-bound); paste on this thread
    # as they arrive. On the first failure, cancel this render's queued tiles
    # and close whatever its in-flight downloads still return.
    futures = []
    try:
        for r in range(n_rows):
            for c in range(n_cols):
                futures.append(_tile_pool.submit(fetch, r, c))
        for future in as_completed(futures):
            paste(*future.result())
    except BaseException:
        for future in futures:
            if not future.cancel():  # running or finished: close its tile when done
                future.add_done_callback(_close_abandoned_tile)
        output.close()
        raise

    return to_palette(output)


def to_palette(img: Image.Image) -> Image.Image:
    """The image as a palette image; exact when it has at most 256 colours.

    MML's raster maps use a small fixed palette (about 120 colours on a sheet), so
    the palette image is lossless and lets the PDF store one byte per pixel.
    """
    colours = img.getcolors(256)
    if colours is None:
        return img.quantize(colors=256)
    flat = [v for _, rgb in colours for v in rgb]
    palette = Image.new("P", (1, 1))
    palette.putpalette(flat + [0] * (768 - len(flat)))
    return img.quantize(palette=palette, dither=Image.Dither.NONE)


def _close_abandoned_tile(future) -> None:
    if not future.cancelled() and future.exception() is None:
        future.result()[2].close()  # closing a tile already pasted is harmless


def render_extent_image(
    extent: Extent,
    width_px: int,
    height_px: int,
    layer: str = "maastokartta",
) -> Image.Image:
    """Render via WMS when configured, otherwise via WMTS stitching."""
    try:
        return fetch_wms_image(extent, width_px, height_px, layer)
    except MMLError:
        return fetch_wmts_mosaic(extent, width_px, height_px, layer)
