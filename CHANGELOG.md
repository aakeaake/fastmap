# Changelog

All notable changes to FastMap. Versions are tagged `vX.Y.Z` on `main`.

## Unreleased

### Added
- Info button at the top right: a popup that explains what FastMap is for
  and how to use maps, route covering, atlases and the route tool. It opens
  by itself on the first visit.
- GPX waypoints show as named circles on the map and on printouts, and are
  kept in exported GPX files.
- Course look for a drawn or imported route: start triangle, numbered
  controls and finish circle, like an orienteering course. Line stays the
  default; choose Course in the route tool. A course has its own width,
  thin (0.4 mm) by default.
- Route tool: a route button on the map opens a card to draw, import, name,
  edit, export (GPX) or remove the route and to set how it prints, from any
  mode. Removing the route can be undone. On phones the card takes the
  bottom sheet's place.
- Clear all in Route and Atlas, with Undo, like in Maps.
- Route mode says when the route was changed after its maps were made
  ("Route changed — the maps still follow the old one") and offers Update.

### Changed
- The route is drawn in its chosen colour, fully opaque, instead of the
  default blue.
- Route mode only covers the route with maps; the route itself is in the
  route tool.
- The route width is set in mm (default 1.1 mm, about 3 pt; was 5 pt). The
  API's `gpx_width` (points, 1–20, default 5) now also accepts decimals.
- The route on the map follows its print colour, width and opacity, and the
  print style is remembered across visits.
- The settings panel folds to the sidebar while a route or area is drawn or
  edited, and comes back after.
- The vector map's style, per-scale settings and symbols are fastmap's own data
  files now (`vector/styles/*.json`), edited directly; the printed map is unchanged.
- Vector PDFs render about 5x faster and are about 3x smaller (A4 1:50 000:
  65 s -> 11 s of CPU, 12.4 -> 4.2 MB), with the same print quality; output
  is now identical between runs. Raster PDFs render about 5x faster and are
  about a quarter smaller (indexed images with an exact palette).
- Vector map colours and lines follow the printed reference map more
  closely: water areas #6DCFF6, shorelines and streams #0071BC, fields
  #FFD98F; auxiliary contours at 1:25 000 are long dashes (1.6 mm dash,
  0.4 mm gap); road edges at 1:25 000 print 0.10 mm, and shorelines are
  narrower (0.10 mm at 1:25 000, 0.07 mm at 1:50 000).
- The conifer, deciduous and mixed-forest, radio mast, spring and fireplace
  symbols are copied from the printed reference map, at its size.
- Small open-rock dots are a little bigger and print under the contours;
  point symbols are drawn in style order with the other layers.
- The map preview loads faster: the tile proxy keeps its connections to MML
  open instead of opening a new one per tile, and retries MML's brief
  overload errors like the PDF renderer does.

### Fixed
- Vector maps fill the sea blue. The style left sea areas out of the water
  fill (its source fills them from OpenStreetMap, which fastmap doesn't use),
  so the sea printed white with only a shoreline.
- The Route/Atlas sheet index is a radio group for screen readers (arrow
  keys move the selection), and a download no longer makes them re-read the
  focused cell.
- Undoing a set's first Create leaves keyboard focus on the Create button
  instead of nowhere.
- No hand cursor over sheets while drawing a route or area.
- Download and delete on unselected Maps rows stay reachable by screen
  readers.
- On phones, a long route or atlas name in the header keeps its sheet label
  (" 12/25", " B3").

## 0.2.0 — 2026-11-22

A new, single-panel UI with three ways to make sheets, a vector map,
route drawing and route/area coverage, and an English/Finnish interface.

### Added
- **Three modes in one panel: Maps · Route · Atlas** (Kartat · Reitti ·
  Kartasto). Each mode keeps its own sheets; only the current mode's sheets
  are on the map, in its list and in Download all. Undo restores only the
  set it came from. Saved maps from earlier versions load as Maps-mode maps.
- **Route mode:** load a GPX file or draw a route on the map (click to add
  points, edit by dragging, remove points), download it as GPX, name it and
  choose whether and how it prints. **Create maps** covers it with print
  sheets in walking order ("Kungsleden 1/8"), each with the route kept clear
  of the edges and a chosen overlap at every handover.
- **Atlas mode:** draw an area and **Create atlas** fills it with a grid of
  sheets titled by row and column ("Atlas B3"), with overlap 0–20 %; no
  sheet is printed for a sliver its neighbour already holds.
- Route and Atlas have their own print settings (paper, orientation, scale,
  map type, grid, overlap). Changing them after a Create shows "Settings
  changed" and an **Update** button. A set holds at most 25 maps, so
  Download all always works.
- A compact **sheet index** for Route and Atlas: the atlas as its grid (gaps
  stay empty), the route as a 1…N strip, a summary line and the selected
  sheet with download and delete; arrow keys move the selection.
- **Click a sheet on the map** to select it.
- **"Maastokartta, vector (beta)"** map type. It draws MML's open vector
  tiles (Topographic Database) into the PDF as vector paths, so lines and
  text stay sharp at any print size. Supported at exactly 1:25 000 and
  1:50 000; other scales are rejected with 422, and the UI only offers it at
  those scales. Styled after the raster Maastokartta and tuned for print;
  adjacent protected-area polygons of one class draw one outer border, and
  trails and borders are wider at 1:50 000. The browser preview still shows
  raster tiles. `tools/compare_vector.py` renders a sheet both ways for
  tuning.
- **English and Finnish UI** with a globe language menu; numbers group
  thousands with a space in both ("1:20 000").
- **PDF footer line** (title · scale on the left, the licence line on the
  right) instead of boxes on the map; grid labels sit outside the map.
- **Phone layout:** the panel is a bottom sheet (peek / half / full) with
  44 px touch targets; a "move here" button places the selected map in the
  visible area.
- Pop-up notices for download progress, results and errors.

### Changed
- The second "Route and precision" pane is gone. Margin, print DPI and map
  level are under **Advanced**; margin is one setting for all maps, and the
  map type sits next to the scale.
- The map always stays north up (no pinch or Alt+Shift rotation).
- The licence line reads `© Maanmittauslaitos, CC BY 4.0, MM/YYYY`, in the
  PDF footer and on screen.
- Renders are about 3× faster and PDFs about 20 % smaller: tiles download in
  parallel (`TILE_FETCH_WORKERS`, 8) and PDF streams are no longer ASCII85.
- The frontend is split into `styles.css` and ES modules (no build step);
  frontend files are served with no-cache.
- Accessibility: keyboard-reachable lists and controls, named icon buttons,
  WCAG AA contrast, screen-reader announcements; delete and clear all offer
  Undo.
- Requires `mapbox-vector-tile` and `shapely>=2.1`.

### Fixed
- The MML API key could appear in urllib3's retry and debug logs; those log
  records are now redacted.
- Grid coordinates print black instead of grey.

## 0.1.9 — 2026-11-18

### Fixed
- The MML API key could appear in error messages and logs when a tile or
  WMS request failed. Errors now name the tile, never the URL.
- PDFs with a GPX track failed (422): tracks are now sent one line per
  segment, and points with elevation/time are accepted.
- Grid labels at 500 m spacing were ambiguous (`428` twice); half-km lines
  now read `428.5`. Dense grids show fewer labels instead of overlapping.
- An invalid GPX colour crashed PDF generation; it is now rejected (422).
- The attribution month was fixed at server start; it is now dated per PDF,
  in Finnish time, and the UI shows the same line (`GET /api/attribution`).
- The GPX label in the UI showed a waypoint's name instead of the track's.

### Changed
- Failed MML requests are retried (up to 3 attempts, honouring
  `Retry-After`); read timeouts fail at once.
- At most `RENDER_WORKERS` (2) maps render at once and `MAX_PENDING_JOBS`
  (10) can be queued; beyond that the server answers 503 with `Retry-After`.
  Synchronous endpoints need an idle worker and never queue.
- Results that are never downloaded are deleted after `JOB_TTL_S` (30 min).
- Invalid map areas on background requests now get an immediate 422.

### Development
- GitHub Flow with CI (tests on Python 3.10 and 3.12, ruff, Docker build),
  `uv.lock`, and the version read from `pyproject.toml` only.

## 0.1.8 and earlier

See the git tags `v0.1.4` … `v0.1.8`.
