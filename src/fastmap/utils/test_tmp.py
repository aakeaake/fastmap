import random
import requests
from PIL import Image
from io import BytesIO
import mercantile

# --- Settings ---
OSM_TILE_URL = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
OSM_TILE_SUBDOMAINS = ["a", "b", "c"]
HEADERS = {"User-Agent": "fastmap-dev/0.1 (aake.kesala@gmail.com)"}

# Coordinates near Espoo center
lat, lon = 60.2055, 24.6559  # Espoo, Finland
zoom = 15  # zoom level (higher = more detail)

# Convert lat/lon to tile coordinates
tile = mercantile.tile(lon, lat, zoom)
x, y, z = tile.x, tile.y, tile.z
print(f"Fetching tile at x={x}, y={y}, z={z}")

# Pick a random subdomain
s = random.choice(OSM_TILE_SUBDOMAINS)
url = OSM_TILE_URL.format(s=s, x=x, y=y, z=z)

# Fetch the tile
response = requests.get(url, headers=HEADERS)
response.raise_for_status()  # raise error if blocked

# Open and save the image
img = Image.open(BytesIO(response.content))
img.save("espoo_tile.png")
print("Tile saved as espoo_tile.png")