import os

from dotenv import load_dotenv

load_dotenv()

MML_API_KEY = os.environ.get("MML_API_KEY", "")

MML_WMS_URL = "https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wms/1.0.1/"
MML_WMTS_URL = "https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wmts/1.0.0/{layer}/default/ETRS-TM35FIN/{z}/{y}/{x}.png"

USER_AGENT = "fastmap/0.1 (print-ready maps of Finland)"

DEFAULT_DPI = 300
MAX_RENDER_PIXELS = 60_000_000  # safety cap for WMS image size
