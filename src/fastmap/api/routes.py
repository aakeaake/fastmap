from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from fastmap.schemas.map_request import MapRequest
from fastmap.services.map_renderer import render_osm_map
from fastmap.services.pdf_generator import generate_pdf

import tempfile
import os

router = APIRouter()


@router.post("/generate-map")
def generate_map(req: MapRequest):
    """
    Generate a PDF into a unique temporary file and return it to the client.

    The visible filename presented to the user is a sensible name based on
    lat/lon (no spaces). The server stores the PDF in a unique temp file
    (to avoid collisions) and removes it after the response is complete.
    """
    # Create a unique temporary file for the output PDF
    tmp = tempfile.NamedTemporaryFile(prefix="fastmap_", suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()

    # A sensible filename to present to the user (Content-Disposition)
    display_name = f"fastmap_{req.lat:.4f}_{req.lon:.4f}.pdf"

    # Generate the PDF into the temporary file
    pdf_file = generate_pdf(
        lat=req.lat,
        lon=req.lon,
        scale=req.scale,
        paper_size=req.paper_size,
        orientation=req.orientation,
        out_pdf_path=tmp_path,
        zoom=15,
    )

    # Ensure the file is removed after the response is finished
    return FileResponse(
        pdf_file,
        media_type="application/pdf",
        filename=display_name,
        background=BackgroundTask(os.remove, pdf_file),
    )
@router.get("/health")
def health():
    return {"status": "ok"}


