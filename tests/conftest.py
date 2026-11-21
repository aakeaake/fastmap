import os

os.environ.setdefault("MML_API_KEY", "test-key")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "vector"
FIXTURE_CENTER = (371500.0, 6687500.0)


@pytest.fixture
def offline_tiles(monkeypatch):
    """Serve vector tiles from tests/fixtures/vector; missing file -> None (404)."""
    from fastmap.vector import tiles

    def fake_fetch(level: int, row: int, col: int):
        path = FIXTURE_DIR / str(level) / str(row) / f"{col}.pbf"
        return path.read_bytes() if path.exists() else None

    monkeypatch.setattr(tiles, "fetch_tile", fake_fetch)
    return FIXTURE_CENTER
