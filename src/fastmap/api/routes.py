from fastapi import APIRouter
from fastmap.schemas.map_request import MapRequest
from fastmap.services.map_renderer import render_osm_map
from fastmap.services.pdf_generator import generate_pdf

router = APIRouter()

@router.post("/generate-map")
def generate_map(req: MapRequest):
    pdf_file = generate_pdf(
        lat=req.lat,
        lon=req.lon,
        scale=req.scale,
        paper_size=req.paper_size,
        orientation=req.orientation,
        out_pdf_path="output_map.pdf",
        zoom=15
    )
    return {"message": "PDF generated", "file": pdf_file}

@router.get("/health")
def health():
    return {"status": "ok"}


