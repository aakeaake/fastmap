import logging
import os
from collections.abc import Mapping

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
# Quiet the tile-proxy access logs (hundreds per request)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

MML_API_KEY = os.environ.get("MML_API_KEY", "")

# The free open-data service ("Karttakuva avoin") is WMTS-only; WMS GetMap
# exists only for contract licence customers. Leave empty to use WMTS
# stitching, or point at your own licensed endpoint to enable the WMS path.
MML_WMS_URL = os.environ.get("MML_WMS_URL", "")
# Tile path template: {z} / {y}=TileRow / {x}=TileCol  (REST order per MML).
MML_WMTS_URL = os.environ.get(
    "MML_WMTS_URL",
    "https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wmts/1.0.0/"
    "{layer}/default/ETRS-TM35FIN/{z}/{y}/{x}.png",
)

USER_AGENT = "fastmap/0.1 (print-ready maps of Finland)"

DEFAULT_ZOOM = 11
MAX_RENDER_PIXELS = 60_000_000  # safety cap for WMS image size

# Rendering limits (see fastmap.services.jobs). One A4 render holds tens of
# MB of raster, so keep RENDER_WORKERS small on small instances.


def _env_number(env: Mapping[str, str], name: str, default: str, kind: type):
    raw = env.get(name, default)
    try:
        return kind(raw)
    except ValueError:
        raise ValueError(f"{name} must be a {kind.__name__}, got {raw!r}") from None


def parse_render_limits(env: Mapping[str, str]) -> tuple[int, int, float]:
    """(RENDER_WORKERS, MAX_PENDING_JOBS, JOB_TTL_S), checked; errors name the variable."""
    workers = _env_number(env, "RENDER_WORKERS", "2", int)
    max_pending = _env_number(env, "MAX_PENDING_JOBS", "10", int)
    ttl_s = _env_number(env, "JOB_TTL_S", "1800", float)
    if workers < 1:
        raise ValueError(f"RENDER_WORKERS must be at least 1, got {workers}")
    if max_pending < workers:
        raise ValueError(
            f"MAX_PENDING_JOBS must be at least RENDER_WORKERS ({workers}), got {max_pending}"
        )
    if not ttl_s > 0:
        raise ValueError(f"JOB_TTL_S must be greater than 0, got {ttl_s}")
    return workers, max_pending, ttl_s


# JOB_TTL_S: seconds a finished but never downloaded result is kept.
RENDER_WORKERS, MAX_PENDING_JOBS, JOB_TTL_S = parse_render_limits(os.environ)
