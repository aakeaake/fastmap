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
                           draggable paper-footprint rectangle, scale presets,
                           optional grid overlay selector)
src/fastmap/
├── api/routes.py          POST /generate-map, POST /generate-maps-batch,
│                          GET /api/nls-tiles proxy, GET /api/attribution,
│                          GET /health
├── schemas/               Pydantic request models + validation
├── services/
│   ├── print_layout.py    Pure maths: paper sizes, extents, pixel dims
│   ├── mml_source.py      MML WMTS tile stitching (open data) + optional WMS
│   └── pdf_generator.py   ReportLab page composition, grid lines, text overlays
└── core/config.py         Env-based configuration
```

The browser never sees the MML API key: preview tiles are proxied through
`/api/nls-tiles/{z}/{x}/{y}.png`.

## Features

* **True-to-scale PDFs** — content area matches the printed rectangle exactly.
* **Multiple rectangles** — draw several maps on one session; click a list row
  to edit, drag to move, double-click to re-centre.
* **Scale presets** — 10 000 / 15 000 / 20 000 / 25 000 / 30 000 / 50 000.
* **Optional grid lines** — south-north (vertical) or full (vertical +
  horizontal), each with optional coordinate labels. Spacing selectable: 500 /
  1 000 / 2 000 / 5 000 m.
* **Batch export** — download all rectangles as one multi-page PDF (mixed page
  sizes allowed) or a ZIP of individual files.
* **Layer selection** — Maastokartta, Taustakartta, Selkokartta, Ortoilmakuva.
* **Timestamped filenames** — downloads include date/time to avoid collisions.
* **Persistent state** — rectangle list saved in your browser and restored on
  the next visit.
* **GPX track overlay** — upload a GPX file to display the track on the preview
  map and render it on exported PDFs. Customisable colour, width, and opacity.

## MML open-data service notes

* The free "Karttakuva avoin" service is **WMTS-only** (WMS GetMap requires a
  contract licence; set `MML_WMS_URL` in `.env` if you have one).
* The `ETRS-TM35FIN` matrix set is served at levels 0–13
  (resolution 8192 m/px → 1 m/px); FastMap caps rendering accordingly.
* Areas outside Finland's map coverage render as blank white — e.g. a bbox
  accidentally centred across the eastern border.

## Setup

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev        # creates .venv from the committed uv.lock
cp .env.example .env       # then paste your own MML API key into it
```

Without uv:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Get a free API key for the Karttakuva service at
<https://www.maanmittauslaitos.fi/kartat-ja-aineistot-rajapinnassa/palvelut-ja-rajapinnat>.

## Run

```bash
uv run uvicorn fastmap.main:app --reload      # or: uv run python run_server.py
```

Open <http://127.0.0.1:8000/> — the UI is served by the same server.

At most `RENDER_WORKERS` maps (default 2) render at once; up to
`MAX_PENDING_JOBS` (default 10) may be queued or rendering, and further
requests get **503** with `Retry-After`. Finished results that are never
downloaded are deleted after `JOB_TTL_S` (default 30 min). Map tiles download
in parallel, at most `TILE_FETCH_WORKERS` (default 8) at once for the whole
process, shared by all renders; lower it if MML starts answering 429. Failed
MML requests are retried up to 3 attempts (not read timeouts). See
`.env.example`.

## Usage

* The panel lists your rectangles: **red = active** (drag it, double-click to
  re-centre), **grey = locked**. Click a list row to edit or ✕ to delete.
* **+ Uusi kartta** adds a rectangle at the view centre; settings
  (paper, orientation, scale, margin, layer, title, grid mode/spacing) are
  stored per rectangle.
* The rectangle shows the printable *content area* (paper minus margins),
  so what you see is exactly what prints.
* **Ruudukko** selector toggles grid lines (Ei / Pystyviivat / Täysi) with
  selectable spacing. Greys out when off.
* **GPX-reitti** button uploads a GPX file; the track appears as a coloured
  line on the preview map and is included in exported PDFs. Use
  **GPX-lisäasetukset** to adjust colour, width, and opacity.
* **Lataa aktiivinen PDF** downloads the current map;
  **Lataa kaikki** renders every rectangle as either one multi-page PDF
  (mixed page sizes allowed) or a ZIP of individual PDFs.
* The rectangle list is saved in your browser and restored on the next visit.

### PDF output

Each generated PDF contains:

* The map raster filling the area inside the margins exactly, except for a
  3 mm band at the bottom (no frame or border).
* **Footer line** in that band, below the map, in Courier: `title · scale`
  on the left (just the scale without a title; a long title is shortened
  with "…") and `© Maanmittauslaitos MM/YYYY` on the right.
* **Grid lines** (optional) — thin grey lines at the selected spacing, with
  optional coordinate labels in TM35FIN metres ÷ 100 (E 385 500 → `3855`,
  N 6 672 500 → `66725`). Labels sit outside the map, in the margin: east
  labels above the top edge, north labels left of the map, rotated 90°
  anticlockwise. In a margin under 3 mm they go inside the map edges.
* **GPX route** (optional) — coloured polyline clipped to the content area,
  with configurable colour, width, and opacity.

### API

```bash
curl -X POST http://127.0.0.1:8000/generate-map \
  -H 'Content-Type: application/json' \
  -d '{
        "bbox": {"minx": 428100, "miny": 6665230, "maxx": 431900, "maxy": 6670770},
        "scale": 20000,
        "paper_size": "A4",
        "orientation": "portrait"
      }' \
  -o map.pdf

# Batch: up to 25 maps as one multi-page PDF ("output":"pdf", default)
# or a ZIP of individual files ("output":"zip")
curl -X POST http://127.0.0.1:8000/generate-maps-batch \
  -H 'Content-Type: application/json' \
  -d '{
        "output": "pdf",
        "maps": [
          {"bbox": {"minx": 640220, "miny": 6998835, "maxx": 650220, "maxy": 7013405}, "scale": 20000},
          {"center_x": 379667, "center_y": 6673891, "scale": 25000, "orientation": "landscape"}
        ]
      }' \
  -o batch.pdf
```

Either `bbox` (EPSG:3067 metres) or `center_x`, `center_y` + `scale` must be
given per map. Optional fields: `dpi` (default 300), `margin_mm` (default 7),
`title`, `grid_mode` (`"off"` / `"vertical"` / `"vertical_coords"` / `"full"` /
`"full_coords"`, default `"off"`),
`grid_spacing_m` (500 / 1000 / 2000 / 5000, default 1000),
`gpx_routes` (list of coordinate arrays in EPSG:3067),
`gpx_color` (hex, default `"#ff00ff"`),
`gpx_width` (1–20 pt, default 5),
`gpx_opacity` (0.1–1.0, default 0.6). See `/docs` for the interactive schema.

## Tests

```bash
uv run pytest
```

Unit tests cover the scale/pixel maths, WMTS tile-index geometry, WMS URL
building and offline PDF generation; no network access is needed for the test
suite. The GPX test uses `pdftoppm` (`poppler-utils`).

## Development workflow

FastMap uses [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow):
`main` is always deployable and is what Render deploys.

1. Branch off `main`: `feat/…`, `fix/…`, `chore/…` or `docs/…`.
2. Before pushing, run the same checks as CI:
   ```bash
   uv run ruff check . && uv run ruff format --check . && uv run pytest
   ```
3. Open a pull request to `main`. CI runs tests (Python 3.10 and 3.12), ruff
   and a Docker build; all must pass before merging.
4. **Squash merge.** Render deploys `main` automatically once checks pass.

**Releases:** in one PR, bump `version` in `pyproject.toml` (the only place it
lives) and add an entry to `CHANGELOG.md`; merge it, then tag the merge commit:

```bash
git switch main && git pull
git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z
```

## License notes

Map data © Maanmittauslaitos, licensed CC BY 4.0. Every generated PDF carries
the required attribution.
