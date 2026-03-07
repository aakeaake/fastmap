from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from PIL import Image

from fastmap.services.map_renderer import render_osm_map
from fastmap.services.bbox import calculate_bbox_wgs84, get_paper_size

def generate_pdf(lat, lon, scale, paper_size, orientation, out_pdf_path="map.pdf", zoom=15):
    # 1️⃣ Calculate bounding box in EPSG:3067
    min_lat, min_lon, max_lat, max_lon = calculate_bbox_wgs84(lat, lon, scale, paper_size, orientation)

    # # 2️⃣ Convert bbox to lat/lon (for OSM)
    # min_lat, min_lon = miny, minx
    # max_lat, max_lon = maxy, maxx

    # 3️⃣ Render map image
    map_img = render_osm_map(min_lat, min_lon, max_lat, max_lon, zoom=zoom)
    map_img_path = "temp_map.png"
    map_img.save(map_img_path)

    # 4️⃣ Get PDF page size in points
    width_pt, height_pt = get_paper_size(paper_size, orientation)

    # 5️⃣ Create PDF
    c = canvas.Canvas(out_pdf_path, pagesize=(width_pt, height_pt))

    # 6️⃣ Resize image to fill page (maintain aspect ratio)
    img_width, img_height = map_img.size
    aspect = img_width / img_height
    page_aspect = width_pt / height_pt

    if aspect > page_aspect:
        # Image wider than page
        display_width = width_pt
        display_height = width_pt / aspect
    else:
        display_height = height_pt
        display_width = height_pt * aspect

    # Center on page
    x = (width_pt - display_width) / 2
    y = (height_pt - display_height) / 2

    c.drawImage(map_img_path, x, y, display_width, display_height)

    # Optional: add title, scale bar, etc.
    c.setFont("Helvetica", 12)
    c.drawString(10*mm, 10*mm, f"Center: {lat:.5f}, {lon:.5f}  Scale 1:{scale}")

    c.showPage()
    c.save()
    return out_pdf_path