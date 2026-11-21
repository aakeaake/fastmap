"""Per-scale rendering profiles for the vector map."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleProfile:
    scale: int
    tile_level: int
    px_mm: float
    zoom_offset: float
    overrides: dict[str, dict]


PROFILES: dict[int, ScaleProfile] = {
    25000: ScaleProfile(25000, 12, 0.28, 0.0, {}),
    50000: ScaleProfile(50000, 11, 0.28, 0.0, {}),
}
