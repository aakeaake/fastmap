"""Per-scale rendering profiles for the vector map."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleProfile:
    """How the style is drawn at one print scale.

    ``px_mm`` is the paper size of one style pixel (line widths, icons, spacing);
    ``zoom_offset`` is added to the scale's style zoom; ``overrides`` are per-layer
    style overrides (see ``style._apply_overrides``). ``text_scale`` and ``halo_scale``
    multiply text sizes and halo widths on top of ``px_mm``.
    """

    scale: int
    tile_level: int
    px_mm: float
    zoom_offset: float
    overrides: dict[str, dict]
    text_scale: float = 1.0
    halo_scale: float = 1.0


_INDEX_CONTOUR = ["==", ["%", ["get", "korkeusarvo"], 20000], 0]  # 20 m index lines

PROFILES: dict[int, ScaleProfile] = {
    25000: ScaleProfile(
        25000,
        12,
        0.115,  # px_mm: contour/road weights match the MML raster 1:25 000
        0.15,  # zoom_offset: style zoom >= 13 everywhere in Finland (contours, symbols)
        {
            # 2.5 m dashed contours fully drawn, as on the raster (style fades them < 13.5)
            "korkeus_apuviiva": {"paint": {"line-opacity": 1}},
            # lake surface heights, shown on the raster
            "mml-vedenpinta": {"minzoom": 13},
        },
        text_scale=0.85,  # names the size of the raster's (F5)
        halo_scale=0.4,  # thin halo (F1): at most ~0.09 mm
    ),
    50000: ScaleProfile(
        50000,
        11,
        0.07,  # px_mm: thin, light lines like the 1:50 000 reference (F2)
        1.15,  # zoom_offset: the 1:25 000 style zoom, i.e. the same detail drawn finer
        {
            # 5 m contours, 20 m index contours thicker (the reference's interval)
            "korkeus_viiva": {
                "paint": {
                    "line-width": [
                        "interpolate",
                        ["linear"],
                        ["zoom"],
                        12,
                        ["case", _INDEX_CONTOUR, 2.4, 1.0],
                        14,
                        ["case", _INDEX_CONTOUR, 2.8, 1.2],
                    ]
                }
            },
            "korkeus_apuviiva": {"visibility": "none"},  # no 2.5 m contours at 1:50 000
            "mml-vedenpinta": {"minzoom": 13},  # lake surface heights, as on the reference
        },
        text_scale=1.5,  # small names as on the reference, readable at px_mm 0.07 (F5)
        halo_scale=0.4,  # hairline halo (F1): at most ~0.06 mm
    ),
}
