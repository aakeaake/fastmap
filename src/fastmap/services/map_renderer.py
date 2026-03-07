import random
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling

import mercantile
from PIL import Image
import requests
from io import BytesIO

OSM_TILE_URL = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
OSM_TILE_SUBDOMAINS = ["a", "b", "c"]
HEADERS = {"User-Agent": "fastmap-dev/0.1 (aakekesala@gmail.com)"}


def latlon_to_tile(lat, lon, zoom):
    """Return x,y tile coordinates at given zoom."""
    tile = mercantile.tile(lon, lat, zoom)
    return tile.x, tile.y

def fetch_tile(x, y, z):
    s = random.choice(OSM_TILE_SUBDOMAINS)
    url = OSM_TILE_URL.format(s=s, x=x, y=y, z=z)
    r = requests.get(url, headers=HEADERS)
    r.raise_for_status()
    return Image.open(BytesIO(r.content))

def merge_tiles(tiles):
    """Merge a 2D list of PIL images into one image."""
    if not tiles:
        raise ValueError("No tiles to merge")

    row_images = []
    for row_tiles in tiles:
        width = 256 * len(row_tiles)
        row_img = Image.new("RGB", (width, 256))
        x_offset = 0
        for tile in row_tiles:
            row_img.paste(tile, (x_offset, 0))
            x_offset += 256
        row_images.append(row_img)

    # Combine rows vertically
    total_width = row_images[0].width
    total_height = sum(r.height for r in row_images)
    out = Image.new("RGB", (total_width, total_height))
    y_offset = 0
    for r in row_images:
        out.paste(r, (0, y_offset))
        y_offset += r.height

    return out

def render_osm_map(min_lat, min_lon, max_lat, max_lon, zoom=15):
    # Convert bounding box to tiles
    min_x, min_y = latlon_to_tile(max_lat, min_lon, zoom)  # note y is flipped
    max_x, max_y = latlon_to_tile(min_lat, max_lon, zoom)
    
    tiles = []
    for y in range(min_y, max_y+1):
        row = []
        for x in range(min_x, max_x+1):
            tile = fetch_tile(x, y, zoom)
            row.append(tile)
        tiles.append(row)
    
    img = merge_tiles(tiles)
    return img

def extract_raster_bbox(raster_path: str, minx, miny, maxx, maxy, out_path: str):
    """
    Extract a bounding box from a raster and save as a new image.
    """
    with rasterio.open(raster_path) as src:
        # Create a window from the bbox in the raster CRS
        window = from_bounds(minx, miny, maxx, maxy, src.transform)

        # Read the window data
        data = src.read(
            window=window,
            out_shape=(
                src.count,
                int(window.height),
                int(window.width)
            ),
            resampling=Resampling.nearest
        )

        # Update transform for cropped raster
        transform = src.window_transform(window)

        # Write to new GeoTIFF
        profile = src.profile
        profile.update({
            "height": data.shape[1],
            "width": data.shape[2],
            "transform": transform
        })

        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data)

    return out_path