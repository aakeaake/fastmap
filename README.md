FastMap Project Roadmap
=======================

Project Goal:
-------------
Build a web service to generate printable maps (PDF) of Finland using topographic maps or OpenStreetMap tiles, with correct scaling and selectable bounding boxes.

---

1. Project Setup (Completed)
---------------------------
- Initialize FastAPI project (`fastmap`)
- Create virtual environment and install dependencies:
    - fastapi, uvicorn, pillow, requests, mercantile, pyproj, reportlab, rasterio
- Basic folder structure:
    fastmap/
        ├── src/fastmap/
        │   ├── api/
        │   │   └── routes.py
        │   ├── services/
        │   │   ├── map_renderer.py
        │   │   └── bbox.py
        │   ├── main.py
        ├── tests/
        ├── output/ (generated PDFs)
        ├── pyproject.toml
        └── README.md

- Barebones endpoint `/generate-map` returning a PDF
- Bounding box calculation working for WGS84 (OSM) and EPSG:3067 (future NLS)
- Tile fetching with User-Agent and subdomain support
- Tile merging and PDF generation

---

2. Input Validation & Error Handling
-----------------------------------
- Validate input parameters (lat/lon, scale, paper size, orientation)
- Catch tile download errors:
    - Return placeholders if some tiles fail
- Handle edge cases (tiny bbox, extremely high zoom)
- Return clear API error messages instead of 500 Internal Server Error

---

3. Tile Caching & Performance
-----------------------------
- Implement caching for OSM/OpenTopoMap tiles:
    - Save tiles locally (`cache/{z}/{x}/{y}.png`)
    - Check cache before downloading
- Optional: use `functools.lru_cache` for small-scale testing
- Optimize tile merging:
    - Use Numpy arrays for large maps (optional)
- Consider **async requests** for faster tile downloads

---

4. Frontend Integration
----------------------
- Allow users to select center, scale, paper size, and orientation
- Options:
    1. **Simple HTML form** (for quick testing)
    2. **React / Vue frontend**:
        - Leaflet.js or OpenLayers for interactive map
        - Draw bounding box / center selection
        - Submit parameters to FastAPI `/generate-map` endpoint
- Display PDF download link or embed in browser

---

5. PDF Enhancements
------------------
- Add scale bar
- Optional: add title, date, coordinates
- Proper DPI handling for printing
- Maintain aspect ratio and center map on page
- Optional: include gridlines for topographic maps

---

6. NLS Data Integration (Finland Topo)
--------------------------------------
- Prepare EPSG:3067 workflow for NLS datasets
- Integrate raster/vector layers from National Land Survey of Finland
- Extract bounding boxes using `rasterio` or vector clipping
- Generate map images from NLS data
- Keep OSM/OpenTopoMap as fallback for testing

---

7. Deployment & Scalability
--------------------------
- Deploy using Uvicorn/Gunicorn
- Optional: Docker containerization
- Configure storage for generated PDFs and tile cache
- Consider **rate limiting** and tile usage policies
- Optional: CDN / S3 for large-scale PDF delivery

---

8. Testing & QA
---------------
- Unit tests for:
    - Bounding box calculations
    - Tile fetching / merging
    - PDF generation
- Integration tests: API returns valid PDFs
- Manual verification: maps look correct in Finland, scale accurate

---

9. Optional Advanced Features
-----------------------------
- User accounts / saved maps
- Multiple layers (contours, roads, water)
- Export in other formats (GeoTIFF, PNG)
- Interactive web preview before PDF generation

---

10. Maintenance & Documentation
-------------------------------
- Document API endpoints
- Write README with usage examples
- Maintain changelog for future features
- Track NLS dataset updates

---

Milestones
----------
- Milestone 1: Barebones API + working OSM PDF (done)
- Milestone 2: Input validation + error handling
- Milestone 3: Tile caching and improved performance
- Milestone 4: Frontend integration
- Milestone 5: PDF enhancements (scale bars, proper layout)
- Milestone 6: NLS data integration
- Milestone 7: Deployment & scalability
