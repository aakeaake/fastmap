# FastMap

Print-ready PDF maps of Finland. Draw an A4/A3-sized rectangle anywhere on a
map of Finland in your browser, pick a paper size and scale, and download a
geometrically exact, 300-dpi PDF built from [MML](https://www.maanmittauslaitos.fi/)
(National Land Survey of Finland) raster data.

## Why the maps are true to scale

Everything is computed in **EPSG:3067** (ETRS-TM35FIN), a metric projection:

1. Paper size minus margins gives a content area in millimetres.
2. `content_mm / 1000 × scale` gives the ground extent in metres.
3. That extent is rendered at `mm / 25.4 × dpi` pixels and placed at *exactly*
   that rectangle on the PDF page — no aspect-ratio fitting, no Web-Mercator
   distortion.

A map labelled 1 : 20 000 measures exactly 1 : 20 000 on paper.

## Architecture

```
frontend/index.html        Single-file UI (OpenLayers v10 via CDN, EPSG:3067,
                           draggable paper-footprint rectangle)
src/fastmap/
├── api/routes.py          POST /generate-map, GET /api/nls-tiles proxy, /health
├── schemas/               Pydantic request models + validation
├── services/
│   ├── print_layout.py    Pure maths: paper sizes, extents, pixel dims, scale bar
│   ├── mml_source.py      MML WMTS tile stitching (open data) + optional WMS
│   └── pdf_generator.py   ReportLab page composition, scale bar, attribution
└── core/config.py         Env-based configuration
```

The browser never sees the MML API key: preview tiles are proxied through
`/api/nls-tiles/{z}/{x}/{y}.png`.

## MML open-data service notes

* The free "Karttakuva avoin" service is **WMTS-only** (WMS GetMap requires a
  contract licence; set `MML_WMS_URL` in `.env` if you have one).
* The `ETRS-TM35FIN` matrix set is served at levels 0–13
  (resolution 8192 m/px → 1 m/px); FastMap caps rendering accordingly.
* Areas outside Finland's map coverage render as blank white — e.g. a bbox
  accidentally centred across the eastern border.

## Setup

Requires Python ≥ 3.10.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env       # then paste your own MML API key into it
```

Get a free API key for the Karttakuva service at
<https://www.maanmittauslaitos.fi/kartat-ja-aineistot-rajapinnassa/palvelut-ja-rajapinnat>.

## Run

```bash
uvicorn fastmap.main:app --reload      # or: python run_server.py
```

Open <http://127.0.0.1:8000/> — the UI is served by the same server.

## Usage

* Drag the red rectangle to position the print area.
* Double-click to centre it somewhere new.
* Choose paper (A4/A3), orientation, scale, base layer, optional title.
* **Lataa PDF** downloads the finished file.

### API

```bash
curl -X POST http://127.0.0.1:8000/generate-map \
  -H 'Content-Type: application/json' \
  -d '{
        "bbox": {"minx": 428100, "miny": 6665230, "maxx": 431900, "maxy": 6670770},
        "scale": 20000,
        "paper_size": "A4",
        "orientation": "portrait",
        "layer": "maastokartta"
      }' \
  -o map.pdf
```

Either `bbox` (EPSG:3067 metres) or `center_x`, `center_y` + `scale` must be
given. Optional fields: `dpi` (default 300), `margin_mm` (default 10),
`title`. See `/docs` for the interactive schema.

## Tests

```bash
pytest
```

Unit tests cover the scale/pixel maths, WMTS tile-index geometry, WMS URL
building and offline PDF generation; no network access is needed for the test
suite.

## License notes

Map data © Maanmittauslaitos, licensed CC BY 4.0. Every generated PDF carries
the required attribution.
