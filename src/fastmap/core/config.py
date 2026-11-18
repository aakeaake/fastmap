import logging
import os

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
RENDER_WORKERS = int(os.environ.get("RENDER_WORKERS", "2"))
MAX_PENDING_JOBS = int(os.environ.get("MAX_PENDING_JOBS", "10"))
JOB_TTL_S = float(os.environ.get("JOB_TTL_S", "1800"))  # undownloaded results
