"""Entry point: draw the vector map for an extent into a ReportLab canvas."""

from __future__ import annotations

from collections import defaultdict

from reportlab.pdfgen.canvas import Canvas

from fastmap.services.print_layout import Extent

from .draw import MapFrame, background_color, draw_fill_line_layers
from .geometry import clip_features, merge_by_mtk_id
from .labels import collect_candidates, place
from .labels import draw as draw_labels
from .model import Feature
from .profiles import PROFILES
from .style import scale_to_zoom, style_for
from .symbols import Symbols, draw_icon_layers
from .tiles import load_tiles

CLIP_BUFFER_FRACTION = 0.02


def render_vector_map(
    c: Canvas,
    extent: Extent,
    rect: tuple[float, float, float, float],
    scale: int,
) -> None:
    """Draw the map for ``extent`` into ``rect`` = (x, y, w, h) in pt, clipped to it."""
    try:
        profile = PROFILES[scale]
    except KeyError:
        raise ValueError("Vector map supports 1:25 000 and 1:50 000 only") from None
    style = style_for(profile)
    northing = (extent.miny + extent.maxy) / 2
    zoom = scale_to_zoom(scale, northing) + profile.zoom_offset

    features = load_tiles(extent, profile.tile_level)
    features = merge_by_mtk_id(features)
    features = clip_features(features, extent, CLIP_BUFFER_FRACTION * extent.width_m)
    by_layer: dict[str, list[Feature]] = defaultdict(list)
    for f in features:
        by_layer[f.layer].append(f)

    x, y, w, h = rect
    frame = MapFrame(extent, x, y, w, h)
    c.saveState()
    clip = c.beginPath()
    clip.rect(x, y, w, h)
    c.clipPath(clip, stroke=0, fill=0)
    r, g, b, a = background_color(style, zoom)
    c.setFillColorRGB(1, 1, 1)
    c.rect(x, y, w, h, stroke=0, fill=1)
    if a > 0:
        c.setFillColorRGB(r, g, b)
        c.setFillAlpha(a)
        c.rect(x, y, w, h, stroke=0, fill=1)
        c.setFillAlpha(1)
    symbols = Symbols()
    draw_fill_line_layers(c, frame, style, by_layer, zoom, profile.px_mm, symbols)
    draw_icon_layers(c, frame, style, by_layer, zoom, profile.px_mm, symbols)
    candidates = collect_candidates(style, by_layer, zoom, frame, profile.px_mm)
    draw_labels(c, place(candidates, frame))
    c.restoreState()
