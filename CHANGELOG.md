# Changelog

All notable changes to FastMap. Versions are tagged `vX.Y.Z` on `main`.

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
