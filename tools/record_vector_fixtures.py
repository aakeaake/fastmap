"""Record 3x3 vector tiles around the test point at levels 11 and 12.

Needs MML_API_KEY (``set -a; . ./.env; set +a``). Writes
tests/fixtures/vector/{level}/{row}/{col}.pbf. Data (c) Maanmittauslaitos, CC BY 4.0.
"""

from __future__ import annotations

from pathlib import Path

from fastmap.services import mml_source
from fastmap.services.print_layout import Extent
from fastmap.vector import tiles

CENTER = (371500.0, 6687500.0)
OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "vector"


def main() -> None:
    cx, cy = CENTER
    point = Extent(cx, cy, cx, cy)
    for level in (11, 12):
        col, row, _, _ = mml_source.tile_range(point, level)
        for r in range(row - 1, row + 2):
            for c in range(col - 1, col + 2):
                data = tiles.fetch_tile(level, r, c)
                if data is None:
                    print(f"{level}/{r}/{c}: no data")
                    continue
                path = OUT / str(level) / str(r) / f"{c}.pbf"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                print(f"{level}/{r}/{c}: {len(data)} bytes")


if __name__ == "__main__":
    main()
