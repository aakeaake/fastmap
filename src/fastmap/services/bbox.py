from pyproj import Transformer
from reportlab.lib.pagesizes import A4, A3, landscape, portrait

# Transformers
WGS84_TO_3067 = Transformer.from_crs("EPSG:4326", "EPSG:3067", always_xy=True)
_3067_TO_WGS84 = Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)

# Paper sizes in mm
PAPER_SIZES_MM = {
    "A4": (210, 297),
    "A3": (297, 420)
}

def get_paper_size(paper_size: str, orientation: str):
    """Return ReportLab page size in points for PDF generation"""
    size = {"A4": A4, "A3": A3}[paper_size.upper()]
    return landscape(size) if orientation.lower() == "landscape" else portrait(size)

# ----------------------------
# Bounding box for EPSG:3067 (NLS datasets)
# ----------------------------
def calculate_bbox_epsg3067(lat: float, lon: float, scale: int, paper_size: str, orientation: str):
    """
    Returns bounding box in EPSG:3067 (minx, miny, maxx, maxy)
    """
    center_x, center_y = WGS84_TO_3067.transform(lon, lat)

    width_mm, height_mm = PAPER_SIZES_MM[paper_size.upper()]
    if orientation.lower() == "landscape":
        width_mm, height_mm = height_mm, width_mm

    width_m = (width_mm / 1000.0) * scale
    height_m = (height_mm / 1000.0) * scale

    minx = center_x - width_m / 2
    maxx = center_x + width_m / 2
    miny = center_y - height_m / 2
    maxy = center_y + height_m / 2

    return minx, miny, maxx, maxy

# ----------------------------
# Bounding box for WGS84 (OSM / web tiles)
# ----------------------------
def calculate_bbox_wgs84(lat: float, lon: float, scale: int, paper_size: str, orientation: str):
    """
    Returns bounding box in WGS84 (lat/lon) for web tiles
    """
    # First get bbox in EPSG:3067
    minx, miny, maxx, maxy = calculate_bbox_epsg3067(lat, lon, scale, paper_size, orientation)

    # Convert back to WGS84
    min_lon, min_lat = _3067_TO_WGS84.transform(minx, miny)
    max_lon, max_lat = _3067_TO_WGS84.transform(maxx, maxy)

    return min_lat, min_lon, max_lat, max_lon

# ----------------------------
# Test example
# ----------------------------
if __name__ == "__main__":
    lat, lon = 60.1699, 24.9384
    scale = 25000
    paper_size = "A4"
    orientation = "portrait"

    bbox_3067 = calculate_bbox_epsg3067(lat, lon, scale, paper_size, orientation)
    bbox_wgs84 = calculate_bbox_wgs84(lat, lon, scale, paper_size, orientation)

    print("EPSG:3067 bbox:", bbox_3067)
    print("WGS84 bbox:", bbox_wgs84)