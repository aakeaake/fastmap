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

# MML tags each place name with the smallest map scale it belongs on
# (mittakaavarelevanssi); names tagged 25 000 are 1:25 000 detail, and untagged
# (0) entries are service points (churches, museums, malls), not map names.
_NAMES_FOR_50K = {"filter": [">=", ["coalesce", ["get", "mittakaavarelevanssi"], 0], 50000]}

# Fell-vegetation ticks (symbol class 32715): the heath and open-land colours
# already show this, so the symbol is left out at every scale.
_NO_FELL_TICKS = {"filter": ["!=", ["get", "kohdeluokka"], 32715]}

# At 1:50 000 the lines are drawn finer (px_mm), so the thin linework people
# navigate by (trails, fences, borders) gets wider again.
_WIDER = {"line-width-scale": 1.5}
_WIDER_AT_50K = {
    lid: _WIDER
    for lid in (
        "mml-polku",
        "mml-ajopolku",
        "mml-kavely-pyoratie",
        "mml-aita",
        "mml-aita-helmet",
        "protected_area-outline-outer-mml",
        "hallintorajat",
    )
}

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
            "mml-symboli": _NO_FELL_TICKS,
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
            # only names meant for 1:50 000 maps (national parks and municipalities
            # have their own layers and keep their names)
            "nimisto-maasto-vedet": _NAMES_FOR_50K,
            "nimisto-maasto-vedet-mat-prio": _NAMES_FOR_50K,
            "nimisto": _NAMES_FOR_50K,
            "mml-symboli": _NO_FELL_TICKS,
            **_WIDER_AT_50K,
        },
        text_scale=1.5,  # small names as on the reference, readable at px_mm 0.07 (F5)
        halo_scale=0.4,  # hairline halo (F1): at most ~0.06 mm
    ),
}
