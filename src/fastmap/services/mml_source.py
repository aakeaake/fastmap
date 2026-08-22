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

import io
import math

import requests
from PIL import Image

from fastmap.core.config import (
    MAX_RENDER_PIXELS,
    MML_API_KEY,
    MML_WMS_URL,
    MML_WMTS_URL,
    USER_AGENT,
)
from fastmap.services.print_layout import Extent

WMTS_TILE_SIZE = 256
# Tile matrix set "ETRS-TM35FIN": resolution = 8192 / 2**level. The open
# service serves levels 0-13 (0.5 m/px would be level 14 - contract only).
WMTS_MAX_LEVEL = 13
WMTS_ORIGIN = (-548576.0, 8388608.0)  # top-left corner of level-0 mosaic

MML_LAYERS = ("maastokartta", "taustakartta", "selkokartta", "ortokuva")

_HEADERS = {"User-Agent": USER_AGENT}


class MMLError(RuntimeError):
    """Raised when MML services cannot deliver an image."""


def _require_api_key() -> str:
    if not MML_API_KEY:
        raise MMLError(
            "MML API key is not configured. Set MML_API_KEY in .env "
            "(see .env.example)."
        )
    return MML_API_KEY


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _on_white(img: Image.Image) -> Image.Image:
    """Flatten transparency onto white so no-data areas print as white."""
    rgba = img.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(bg, rgba).convert("RGB")


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
    resp = requests.get(url, headers=_HEADERS, timeout=60)
    if resp.status_code != 200:
        raise MMLError(
            f"WMS GetMap failed ({resp.status_code}): {resp.text[:200]}"
        )
    try:
        return _on_white(Image.open(io.BytesIO(resp.content)))
    except Exception as exc:  # noqa: BLE001
        raise MMLError(f"WMS returned a non-image payload: {exc}") from exc


# ---------------------------------------------------------------------------
# WMTS
# ---------------------------------------------------------------------------

def wmts_resolution(level: int) -> float:
    return 8192.0 / 2 ** level


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
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    if resp.status_code != 200:
        raise MMLError(f"WMTS tile fetch failed ({resp.status_code}) for {url}")
    return _on_white(Image.open(io.BytesIO(resp.content)))


def fetch_wmts_mosaic(
    extent: Extent,
    width_px: int,
    height_px: int,
    layer: str = "maastokartta",
) -> Image.Image:
    """Stitch WMTS tiles covering extent, crop and resize to exact pixels."""
    if width_px * height_px > MAX_RENDER_PIXELS:
        raise MMLError("Requested render is too large")

    target_res = extent.width_m / width_px
    level = pick_wmts_level(target_res)
    res = wmts_resolution(level)

    col_min, row_min, col_max, row_max = tile_range(extent, level)
    n_cols = col_max - col_min + 1
    n_rows = row_max - row_min + 1
    if n_cols * n_rows > 400:
        raise MMLError("Requested area needs too many tiles at chosen level")

    mosaic_w = n_cols * WMTS_TILE_SIZE
    mosaic_h = n_rows * WMTS_TILE_SIZE
    mosaic = Image.new("RGB", (mosaic_w, mosaic_h))

    for r in range(n_rows):
        for c in range(n_cols):
            tile = fetch_wmts_tile(col_min + c, row_min + r, level, layer)
            mosaic.paste(tile, (c * WMTS_TILE_SIZE, r * WMTS_TILE_SIZE))

    # Crop precisely to the extent within the mosaic
    ox, oy = WMTS_ORIGIN
    left = (extent.minx - (ox + col_min * WMTS_TILE_SIZE * res)) / res
    top = ((oy - row_min * WMTS_TILE_SIZE * res) - extent.maxy) / res
    right = left + extent.width_m / res
    bottom = top + extent.height_m / res
    cropped = mosaic.crop(
        (round(left), round(top), round(right), round(bottom))
    )

    return cropped.resize((width_px, height_px), Image.LANCZOS)


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
